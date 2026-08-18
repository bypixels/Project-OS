"""Real usage of agents and skills, read from Claude Code's session history.

Best effort: the .jsonl transcript format is an internal, undocumented detail of
Claude Code and may change. If it does, usage degrades to "unknown"; nothing else breaks.
The registry accumulates last-use dates so they survive history rotation (~30 days).

Attribution: each transcript line carries the session `cwd`, so an invocation of
`code-reviewer` is credited to the project whose root contains that cwd. This is what
tells apart six homonymous `code-reviewer` agents.
"""
import json, os, re, subprocess, shutil
from datetime import date

_AGENT = re.compile(r'"subagent_type":"([a-zA-Z0-9_-]+)"')
_SKILL = re.compile(r'"name":"Skill","input":\{"skill":"([a-zA-Z0-9:_-]+)"')
_TS = re.compile(r'"timestamp":"(\d{4}-\d{2}-\d{2})')
_CWD = re.compile(r'"cwd":"([^"]+)"')


def _lines(history_dir, needle):
    if not os.path.isdir(history_dir):
        return []
    if shutil.which("grep"):
        try:
            r = subprocess.run(["grep", "-rhF", needle, history_dir, "--include=*.jsonl"],
                               capture_output=True, text=True, timeout=180)
            return r.stdout.splitlines()
        except Exception:
            pass
    # Python fallback (Windows, or grep missing): slower but same result
    if True:
        out = []
        for dp, dn, fn in os.walk(history_dir):
            for f in fn:
                if f.endswith(".jsonl"):
                    try:
                        with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                            out.extend(l for l in fh if needle in l)
                    except Exception:
                        pass
        return out


def _read_new_lines(path, offset):
    """Bytes after `offset` -> (list of non-empty line strings, new_offset). Duplicated (not
    imported) from sessions.py: importing sessions here would create an import cycle
    (sessions.py already does `from . import scan, usage`). ~10 lines, two call sites — under
    the project's own 3+ repetitions rule for extracting duplication, this stays duplicated."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    new_offset = offset + len(data)
    lines = [l for l in data.decode("utf-8", "replace").splitlines() if l.strip()]
    return lines, new_offset


def _scan_file(path, offset, roots):
    """Read the new bytes of one .jsonl since `offset`, extract BOTH agents and skills in a
    single pass (never just one — see the Tarea 43 amendment on the shared history baseline).
    Returns (agents_delta, skills_delta, new_offset), each delta shaped like extract()'s output
    but representing only what THIS pass found, not a running total."""
    lines, new_offset = _read_new_lines(path, offset)
    agents, skills = {}, {}
    roots = roots or {}
    for line in lines:
        ts = _TS.search(line)
        d = ts.group(1) if ts else None
        cw = _CWD.search(line)
        proj = _project_of(cw.group(1) if cw else None, roots)
        for out, pattern in ((agents, _AGENT), (skills, _SKILL)):
            for m in pattern.finditer(line):
                e = out.setdefault(m.group(1), {"n": 0, "last": None, "by_project": {}})
                e["n"] += 1
                if d and (e["last"] is None or d > e["last"]):
                    e["last"] = d
                if proj:
                    e["by_project"][proj] = e["by_project"].get(proj, 0) + 1
    return agents, skills, new_offset


def _project_of(cwd, roots):
    """roots: {project_name: abs_root}. Longest matching root wins. Both sides go through
    os.path.realpath first, so a symlinked root or a symlinked cwd still matches."""
    if not cwd:
        return None
    cwd = os.path.realpath(cwd)
    best, best_len = None, -1
    for name, root in roots.items():
        r = os.path.realpath(root)
        if (cwd == r or cwd.startswith(r.rstrip("/") + "/")) and len(r) > best_len:
            best, best_len = name, len(r)
    return best


def extract(history_dir, pattern, needle, roots=None):
    """{name: {"n": int, "last": "YYYY-MM-DD"|None, "by_project": {project: n}}}"""
    out = {}
    roots = roots or {}
    for line in _lines(history_dir, needle):
        ts = _TS.search(line)
        d = ts.group(1) if ts else None
        cw = _CWD.search(line)
        proj = _project_of(cw.group(1) if cw else None, roots)
        for m in pattern.finditer(line):
            e = out.setdefault(m.group(1), {"n": 0, "last": None, "by_project": {}})
            e["n"] += 1
            if d and (e["last"] is None or d > e["last"]):
                e["last"] = d
            if proj:
                e["by_project"][proj] = e["by_project"].get(proj, 0) + 1
    return out


def extract_agents(history_dir, roots=None):
    return extract(history_dir, _AGENT, '"subagent_type":"', roots)


def extract_skills(history_dir, roots=None):
    return extract(history_dir, _SKILL, '"name":"Skill","input":{"skill":"', roots)


def _file_delta(new_counts, old_counts):
    """`new_counts` ("n"-shaped, e.g. from _scan_file or an aggregate across every known
    source file) vs `old_counts` (registry-shaped, "n_total") — the increment `new_counts`
    represents beyond what `old_counts` already accounted for. Can be NEGATIVE (a file that
    shrank after truncation now contributes less than before) — the only thing that never
    regresses is `last` (a date), same rule as merge()'s historical guarantee. by_project is
    NOT computed here (see _accumulate: it sums directly from the raw delta, not from this)."""
    n = new_counts.get("n", 0) - old_counts.get("n_total", 0)
    last = new_counts.get("last")
    old_last = old_counts.get("last")
    if old_last and (not last or old_last > last):
        last = old_last
    return {"n": n, "last": last}


def _accumulate(registry_items, delta):
    """Apply `delta` (shaped like _scan_file's output: {name: {"n","last","by_project"}}) onto
    `registry_items` (registry-shaped: {name: {"n_total","last","by_project"}}). The actual
    increment applied to n_total is _file_delta(v, registry_items.get(k, {})) — NEVER v's raw
    "n" directly — so re-applying an already-reflected count (e.g. because a file was fully
    reparsed and its new total matches what the registry already has) does not double-count.
    by_project sums directly (extra/unknown by-project keys are additive, not diffed)."""
    out = {k: dict(v) for k, v in registry_items.items()}
    for k, v in delta.items():
        old = out.get(k, {})
        d = _file_delta(v, old)
        e = out.setdefault(k, {"last": None, "n_total": 0, "by_project": {}})
        e["n_total"] = e.get("n_total", 0) + d.get("n", 0)
        if d.get("last") and (e.get("last") is None or d["last"] > e["last"]):
            e["last"] = d["last"]
        bp = dict(e.get("by_project") or {})
        for p, n in (v.get("by_project") or {}).items():
            bp[p] = bp.get(p, 0) + n
        e["by_project"] = bp
    return out


def _grow_counts(base, delta):
    """Fold a _scan_file-shaped delta onto a same-shaped running per-file baseline (both use
    "n", not "n_total") via plain addition. NOT the guarded _accumulate/_file_delta (which
    compares an "n"-shaped fresh value against an "n_total"-shaped PRIOR TOTAL, to correct for
    a full reparse) — growing an already-incremental per-file baseline, or summing several
    per-file baselines into one aggregate, needs simple addition instead."""
    out = {k: dict(v) for k, v in base.items()}
    for k, v in delta.items():
        e = out.setdefault(k, {"n": 0, "last": None, "by_project": {}})
        e["n"] = e.get("n", 0) + v.get("n", 0)
        if v.get("last") and (e.get("last") is None or v["last"] > e["last"]):
            e["last"] = v["last"]
        bp = dict(e.get("by_project") or {})
        for p, n in (v.get("by_project") or {}).items():
            bp[p] = bp.get(p, 0) + n
        e["by_project"] = bp
    return out


def _load_history(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_history(path, registry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def merge(registry, fresh):
    """Registry accumulates the TRUE incremental change, never a raw re-count: n_total is
    corrected via _accumulate/_file_delta so re-applying an unchanged aggregate does not
    double-count (a file that was fully reparsed and shrank can even DECREASE n_total). `last`
    never regresses. by_project sums by key. `fresh` here is expected to be the CURRENT
    AGGREGATE across every known source file (see refresh()), not a single file's own delta —
    comparing that aggregate against the registry's previous total is what makes the guard
    meaningful across an unbounded number of files."""
    out = _accumulate(registry, fresh)
    for k, v in fresh.items():
        out[k]["n_window"] = v.get("n", 0)
    for e in out.values():
        e.setdefault("n_window", 0); e.setdefault("by_project", {})
    return out


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("items", {}) if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(path, items, meta=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"meta": meta or {}, "items": items}, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _scan_history_dir(history_dir, roots, history):
    """Walk `history_dir` (same recursive os.walk as before — includes subagents/), updating
    `history` (mutated in place, keyed by absolute source_path) for every file that grew,
    appeared, or shrank since last time. A file whose SIZE matches what's stored is skipped
    entirely (no open/read) — this is the actual speed win over grep-ing 1.4 GB every call.
    Returns nothing; `history`'s entries are the source of truth after this call."""
    if not os.path.isdir(history_dir):
        return
    for dp, dn, fn in os.walk(history_dir):
        for f in fn:
            if not f.endswith(".jsonl"):
                continue
            fp = os.path.join(dp, f)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            entry = history.get(fp)
            if entry is not None and entry.get("size") == st.st_size:
                continue   # nothing new to read
            if entry is not None and st.st_size >= entry.get("offset", 0):
                offset = entry["offset"]
                base_agents = entry.get("agents", {})
                base_skills = entry.get("skills", {})
            else:
                offset = 0                     # new file, or size < offset: rotated/truncated -> reparse from scratch
                base_agents, base_skills = {}, {}
            agents_delta, skills_delta, new_offset = _scan_file(fp, offset, roots)
            history[fp] = {
                "offset": new_offset, "size": st.st_size, "mtime": st.st_mtime,
                "agents": _grow_counts(base_agents, agents_delta),
                "skills": _grow_counts(base_skills, skills_delta),
            }


def _aggregate(history, kind):
    """Sum the `kind` ("agents"|"skills") baseline of every file EVER recorded in `history` —
    not just the ones touched this pass — into one "n"-shaped dict. A file's cached
    contribution survives it disappearing from disk (rotation is normal), same guarantee as
    usage.py's own never-regressing dates."""
    out = {}
    for entry in history.values():
        out = _grow_counts(out, entry.get(kind, {}))
    return out


def _save_sibling_output(state_dir, kind, items, meta):
    """Save the usage-agents.json/usage-skills.json result for `kind` ("agents"|"skills")."""
    p = os.path.join(state_dir, f"usage-{kind}.json")
    save(p, items, meta)


def _refresh_both(state_dir, history_dir, roots):
    """One pass over `history_dir`'s new bytes feeds BOTH usage-agents.json AND
    usage-skills.json — never just the `kind` that happened to call refresh() first. Fixes the
    bug where two independent refresh() calls (one per kind) on the SAME freshly-scanned file
    used to leave whichever kind's own output file un-persisted until IT was explicitly
    refreshed again — even though `_scan_history_dir` already had the data. Returns
    {"agents": (items, meta), "skills": (items, meta)}."""
    hist_path = os.path.join(state_dir, "usage-history.json")
    history = _load_history(hist_path)
    _scan_history_dir(history_dir, roots or {}, history)
    _save_history(hist_path, history)
    out = {}
    for kind in ("agents", "skills"):
        p = os.path.join(state_dir, f"usage-{kind}.json")
        reg = load(p)
        fresh = _aggregate(history, kind)
        window = min((v["last"] for v in fresh.values() if v.get("last")), default=None)
        items = merge(reg, fresh)
        meta = {"updated": date.today().isoformat(), "history_window_from": window}
        _save_sibling_output(state_dir, kind, items, meta)
        out[kind] = (items, meta)
    return out


def refresh(path, history_dir, kind="agents", roots=None):
    """load -> scan changed files incrementally (via <state_dir>/usage-history.json) ->
    aggregate -> merge -> save. A single call refreshes BOTH usage-agents.json and
    usage-skills.json under the hood (see _refresh_both); `kind` only picks which of the two
    results this call returns. Returns (items, meta)."""
    state_dir = os.path.dirname(path)
    return _refresh_both(state_dir, history_dir, roots)[kind]


def for_agent(items, name, project=None):
    """Usage view for one agent: if by_project data exists, per-project count is exact."""
    e = items.get(name) or {}
    bp = e.get("by_project") or {}
    return {"total": e.get("n_total", 0), "last": e.get("last"),
            "here": bp.get(project) if project else None, "attributed": bool(bp)}


# ---------------------------------------------------------------- Codex
# Codex transcripts (~/.codex/sessions/YYYY/MM/DD/*.jsonl) carry the cwd once, in the first
# session_meta line. As of the versions observed, they record NO agent/skill invocations at all —
# only exec_command and MCP calls — so per-agent usage for Codex is genuinely 0. What we can
# attribute is session activity per project, which is still useful (last time Codex worked there).

def codex_sessions(sessions_dir, roots=None):
    """{project: {"sessions": n, "last": "YYYY-MM-DD"}} from session_meta cwd."""
    out = {}
    roots = roots or {}
    if not os.path.isdir(sessions_dir):
        return out
    for dp, dn, fn in os.walk(sessions_dir):
        for f in fn:
            if not f.endswith(".jsonl"):
                continue
            try:
                with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                    head = fh.readline()
            except Exception:
                continue
            m = _CWD.search(head); ts = _TS.search(head)
            proj = _project_of(m.group(1) if m else None, roots)
            if not proj:
                continue
            e = out.setdefault(proj, {"sessions": 0, "last": None})
            e["sessions"] += 1
            d = ts.group(1) if ts else None
            if d and (e["last"] is None or d > e["last"]):
                e["last"] = d
    return out
