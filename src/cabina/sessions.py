"""Session activity, read from Claude Code's own transcripts. Read-only: never edits or
deletes a transcript. Parses each .jsonl into a per-session SUMMARY — counts and metadata
only, never prompt/response text (the one exception is `title`, the AI-generated one-line
title Claude Code itself already writes to the transcript as an `ai-title` line).

Incremental by BYTE OFFSET: <state_dir>/sessions.json keyed by source_path -> {offset, size,
mtime, partial_state, summary}. A refresh() only reads the bytes appended after `offset`; if
the file is now shorter than `offset` (rotated/rewritten) it is re-parsed from scratch. The
transcript format is internal and undocumented: parsing is best-effort per line — a bad line
is skipped, never fatal.

Retention: summaries survive their source file disappearing (rotation is normal; history is
the point, same as usage.py). They are pruned only once `ended` is older than
cfg.activity.retention_days (default 365).
"""
import json, os, re, time

from . import scan, usage

_COMMIT = re.compile(r"\bgit\s+commit\b")
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

SUMMARY_FIELDS = ("session_id", "project", "cwd_changed", "cwd", "branch", "tool", "title",
                   "started", "ended", "duration_s", "turns", "tool_calls", "files_touched",
                   "agents", "skills", "commits", "tokens", "subagent_tokens", "subagents",
                   "sidechain_lines", "version", "source_path", "size", "mtime", "offset")

PARTIAL_STATE_FIELDS = ("session_id", "cwd_counts", "branch", "version", "title", "started",
                        "ended", "turns", "tool_calls", "files_touched", "agents", "skills",
                        "commits", "tokens", "sidechain_lines")


def _redact_unknown_fields(summary):
    """Guard: keep only keys in SUMMARY_FIELDS — an allowlist, not a denylist of 'known-bad'
    names. Any accidental new field (e.g. raw text) is dropped, not exposed. `cwd` and
    `source_path` are LOCAL-ONLY: they stay in this local registry but must never leave the
    machine — export.py and mcp.py filter them out separately (Fase 1b / Fase 2)."""
    return {k: v for k, v in summary.items() if k in SUMMARY_FIELDS}


def _redact_partial_state(state):
    """Same idea as _redact_unknown_fields, but for `partial_state` — the accumulator that
    Tarea 17 persists into sessions.json as-is (to resume incremental parsing). Without this,
    an accidental future addition to _merge_lines that captured raw text would land on disk
    unfiltered, even though the final `summary` was already safe."""
    return {k: v for k, v in state.items() if k in PARTIAL_STATE_FIELDS}


def _read_new_lines(path, offset):
    """Bytes after `offset` -> (list of non-empty line strings, new_offset). Never consumes a
    partial trailing line (a transcript being appended by a live Claude Code session): only
    bytes up to and including the last b"\\n" in the chunk are considered read; if the chunk has
    no newline at all, nothing is returned and `offset` is unchanged (wait for the line to
    complete)."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    last_nl = data.rfind(b"\n")
    if last_nl == -1:
        return [], offset
    new_offset = offset + last_nl + 1
    complete = data[:last_nl]
    lines = [l for l in complete.decode("utf-8", "replace").splitlines() if l.strip()]
    return lines, new_offset


def _empty_tokens():
    return {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}


def _new_state():
    return {"session_id": None, "cwd_counts": {}, "branch": None, "version": None, "title": None,
            "started": None, "ended": None, "turns": 0, "tool_calls": {}, "files_touched": [],
            "agents": {}, "skills": {}, "commits": 0, "tokens": _empty_tokens(), "sidechain_lines": 0}


def _merge_lines(state, lines):
    """Parse new raw JSON lines into `state` (mutated in place, also returned)."""
    for raw in lines:
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if not state["session_id"] and d.get("sessionId"):
            state["session_id"] = d["sessionId"]
        if d.get("version"):
            state["version"] = d["version"]
        if d.get("type") == "ai-title" and d.get("aiTitle"):
            state["title"] = d["aiTitle"]
        if d.get("isSidechain"):
            state["sidechain_lines"] += 1
            continue                                  # R6: excluded from started/ended/cwd/turns/tool_calls/tokens
        ts = d.get("timestamp")
        if ts:
            state["started"] = state["started"] or ts
            state["ended"] = ts
        if d.get("cwd"):
            cw = d["cwd"]; state["cwd_counts"][cw] = state["cwd_counts"].get(cw, 0) + 1
        if d.get("gitBranch") and not state["branch"]:
            state["branch"] = d["gitBranch"]
        msg = d.get("message") or {}
        content = msg.get("content")
        if d.get("type") == "user" and msg.get("role") == "user" and isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "text" for b in content):
                state["turns"] += 1
        if d.get("type") == "assistant" and isinstance(content, list):
            usg = msg.get("usage") or {}
            state["tokens"]["in"] += usg.get("input_tokens", 0) or 0
            state["tokens"]["out"] += usg.get("output_tokens", 0) or 0
            state["tokens"]["cache_read"] += usg.get("cache_read_input_tokens", 0) or 0
            state["tokens"]["cache_write"] += usg.get("cache_creation_input_tokens", 0) or 0
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name = b.get("name", "?")
                state["tool_calls"][name] = state["tool_calls"].get(name, 0) + 1
                inp = b.get("input") or {}
                if name == "Agent" and inp.get("subagent_type"):
                    k = inp["subagent_type"]; state["agents"][k] = state["agents"].get(k, 0) + 1
                if name == "Skill" and inp.get("skill"):
                    k = inp["skill"]; state["skills"][k] = state["skills"].get(k, 0) + 1
                if name in FILE_TOOLS and inp.get("file_path") and inp["file_path"] not in state["files_touched"]:
                    state["files_touched"].append(inp["file_path"])
                if name == "Bash" and _COMMIT.search(inp.get("command") or ""):
                    state["commits"] += 1
    return state


def _git_project_fallback(cwd, cfg_roots, roots):
    """Fallback for a session whose cwd matches no scanned project (scan.py only registers a
    project when it finds a `.claude/` dir there): walk up from `cwd` looking for a git repo
    root (a `.git` dir or file, e.g. a worktree) while still inside one of `cfg_roots`. Found ->
    attribute the session to that repo, so cabina never silently hides real work just because
    the repo has no cabina-visible assets yet. Name follows scan._unique_name's convention:
    basename, or — if that basename is already a DIFFERENT project in `roots` — the path
    relative to the containing cfg root. None if no `.git` turns up before leaving every cfg
    root (or cwd/cfg_roots is empty)."""
    if not cwd:
        return None
    cfg_roots_r = [os.path.realpath(r) for r in (cfg_roots or [])]
    if not cfg_roots_r:
        return None
    cur = os.path.realpath(cwd)
    while True:
        containing = next((r for r in cfg_roots_r if cur == r or cur.startswith(r.rstrip("/") + "/")), None)
        if containing is None:
            return None
        if os.path.exists(os.path.join(cur, ".git")):
            name = os.path.basename(cur)
            existing = roots.get(name)
            if existing is not None and os.path.realpath(existing) != cur:
                name = os.path.relpath(cur, containing)
            return name
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def _guess_project_from_encoded_dir(source_path, roots):
    """Best-effort fallback when a session has no cwd-bearing lines at all: Claude Code encodes
    the cwd into the directory name by replacing '/' with '-'. Lossy (a real '-' in a path looks
    the same as an encoded '/'), so this is a guess, never treated as fact elsewhere."""
    enc = os.path.basename(os.path.dirname(source_path))
    return usage._project_of(enc.replace("-", "/"), roots) or "unknown"


def _subagents_count(source_path):
    sid = os.path.splitext(os.path.basename(source_path))[0]
    d = os.path.join(os.path.dirname(source_path), sid, "subagents")
    if not os.path.isdir(d):
        return 0
    return sum(1 for f in os.listdir(d) if f.endswith(".jsonl"))


def _subagent_tokens(source_path):
    """Tokens spent by subagents of this session — read in full each refresh (these files are
    small), kept SEPARATE from the session's own `tokens` (R3: never summed together)."""
    sid = os.path.splitext(os.path.basename(source_path))[0]
    d = os.path.join(os.path.dirname(source_path), sid, "subagents")
    tokens = _empty_tokens()
    if not os.path.isdir(d):
        return tokens
    for f in os.listdir(d):
        if not f.endswith(".jsonl"):
            continue
        try:
            with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        d2 = json.loads(raw)
                    except Exception:
                        continue
                    if d2.get("isSidechain"):
                        continue
                    usg = ((d2.get("message") or {}).get("usage")) or {}
                    tokens["in"] += usg.get("input_tokens", 0) or 0
                    tokens["out"] += usg.get("output_tokens", 0) or 0
                    tokens["cache_read"] += usg.get("cache_read_input_tokens", 0) or 0
                    tokens["cache_write"] += usg.get("cache_creation_input_tokens", 0) or 0
        except Exception:
            pass
    return tokens


def _to_local_iso(ts):
    if not ts:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().isoformat()
    except Exception:
        return None


def registry_path(cfg):
    return os.path.join(cfg["state_dir"], "sessions.json")


def _load_registry(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_registry(path, reg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _iter_session_files(claude_home):
    """Every <claude_home>/projects/<encoded-cwd>/<sessionId>.jsonl — flat, NOT the
    subagents/ ones (R3: subagent transcripts are never sessions on their own)."""
    pdir = os.path.join(claude_home, "projects")
    if not os.path.isdir(pdir):
        return
    for enc in os.listdir(pdir):
        edir = os.path.join(pdir, enc)
        if not os.path.isdir(edir):
            continue
        for f in os.listdir(edir):
            if f.endswith(".jsonl"):
                yield os.path.join(edir, f)


def _age_days(ended, now_local):
    """Days between `ended` (a local-aware ISO string) and `now_local`. 0 if `ended` is
    missing or unparsable — never ages out something we cannot date."""
    if not ended:
        return 0
    try:
        from datetime import datetime
        return (now_local - datetime.fromisoformat(ended)).days
    except Exception:
        return 0


def _prune_by_retention(reg, retention_days, now_local):
    """Guard (R4): keep an entry unless its summary's `ended` is older than retention_days.
    Whether the SOURCE FILE still exists on disk is never part of this decision — rotation is
    normal, history is the point (same spirit as usage.py's accumulating registry)."""
    return {k: v for k, v in reg.items()
            if _age_days((v.get("summary") or {}).get("ended"), now_local) <= retention_days}


def refresh(cfg, days=30):
    """Parse new/changed bytes of every session file (bounded to `days` for files never seen
    before), merge into the registry, prune by retention, save, return every kept summary —
    newest first. Never call this on an HTTP request thread (see server.py, Fase 1b Tarea 22)."""
    path = registry_path(cfg)
    reg = _load_registry(path)
    roots = scan.project_roots(cfg)
    cutoff = time.time() - days * 86400
    retention_days = (cfg.get("activity") or {}).get("retention_days", 365)
    for fp in _iter_session_files(cfg["claude_home"]):
        try:
            st = os.stat(fp)
        except Exception:
            continue
        cached = reg.get(fp)
        if cached is None:
            if st.st_mtime < cutoff:
                continue
            offset, state = 0, _new_state()
        elif st.st_mtime == cached.get("mtime") and st.st_size == cached.get("size"):
            continue
        elif st.st_size < cached.get("offset", 0):
            offset, state = 0, _new_state()             # rotated/rewritten: reparse from scratch
        else:
            offset, state = cached["offset"], cached["partial_state"]
        try:
            new_lines, new_offset = _read_new_lines(fp, offset)
            state = _redact_partial_state(_merge_lines(state, new_lines))
            summary = _redact_unknown_fields(_finalize(state, fp, roots, new_offset, cfg_roots=cfg.get("roots") or []))
            reg[fp] = {"offset": new_offset, "size": st.st_size, "mtime": st.st_mtime,
                       "partial_state": state, "summary": summary}
        except Exception:
            continue                                     # one unreadable/corrupt transcript never aborts the rest
    from datetime import datetime
    now_local = datetime.now().astimezone()
    kept = _prune_by_retention(reg, retention_days, now_local)
    _save_registry(path, kept)
    return sorted((e["summary"] for e in kept.values()), key=lambda s: s.get("started") or "", reverse=True)


def load(cfg):
    """Read the cached registry only — never opens a transcript. Used where a request must not
    pay parsing cost (server GET handler, MCP tool)."""
    reg = _load_registry(registry_path(cfg))
    return sorted((e["summary"] for e in reg.values()), key=lambda s: s.get("started") or "", reverse=True)


def _finalize(state, source_path, roots, offset, cfg_roots=()):
    from datetime import datetime
    roots = roots or {}
    counts = state["cwd_counts"]
    if counts:
        cwd = max(counts, key=counts.get)
        cwd_changed = len(counts) > 1
        project = usage._project_of(cwd, roots)
        if project is None and cwd:
            project = _git_project_fallback(cwd, cfg_roots, roots)
    else:
        cwd, cwd_changed = None, False
        project = _guess_project_from_encoded_dir(source_path, roots)
    started, ended = _to_local_iso(state["started"]), _to_local_iso(state["ended"])
    duration_s = 0
    try:
        if started and ended:
            duration_s = max(0, int((datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds()))
    except Exception:
        pass
    files = state["files_touched"]
    base = roots.get(project) if project else None
    if base:
        files = [os.path.relpath(f, base) if os.path.isabs(f) and (f == base or f.startswith(base + os.sep)) else f for f in files]
    try:
        st = os.stat(source_path)
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0
    return {
        "session_id": state["session_id"] or os.path.splitext(os.path.basename(source_path))[0],
        "project": project, "cwd_changed": cwd_changed, "cwd": cwd, "branch": state["branch"],
        "tool": "claude", "title": state["title"], "started": started, "ended": ended,
        "duration_s": duration_s, "turns": state["turns"], "tool_calls": state["tool_calls"],
        "files_touched": files, "agents": state["agents"], "skills": state["skills"],
        "commits": state["commits"], "tokens": state["tokens"], "version": state["version"],
        "sidechain_lines": state["sidechain_lines"], "source_path": source_path,
        "size": size, "mtime": mtime, "offset": offset,
        "subagent_tokens": _subagent_tokens(source_path), "subagents": _subagents_count(source_path),
    }
