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


def merge(registry, fresh):
    """Registry never loses a date; n_total = max(seen); by_project merged by max."""
    out = {k: dict(v) for k, v in registry.items()}
    for k, v in fresh.items():
        e = out.setdefault(k, {"last": None, "n_total": 0, "by_project": {}})
        if v.get("last") and (e.get("last") is None or v["last"] > e["last"]):
            e["last"] = v["last"]
        e["n_total"] = max(e.get("n_total", 0), v.get("n", 0))
        e["n_window"] = v.get("n", 0)
        bp = dict(e.get("by_project") or {})
        for p, n in (v.get("by_project") or {}).items():
            bp[p] = max(bp.get(p, 0), n)
        e["by_project"] = bp
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


def refresh(path, history_dir, kind="agents", roots=None):
    """load -> extract -> merge -> save. Returns (items, meta)."""
    reg = load(path)
    fresh = (extract_agents if kind == "agents" else extract_skills)(history_dir, roots)
    window = min((v["last"] for v in fresh.values() if v.get("last")), default=None)
    items = merge(reg, fresh)
    meta = {"updated": date.today().isoformat(), "history_window_from": window}
    save(path, items, meta)
    return items, meta


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
