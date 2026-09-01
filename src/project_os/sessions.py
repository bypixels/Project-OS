"""Session activity, read from Claude Code's own transcripts. Read-only: never edits or
deletes a transcript. Parses each .jsonl into a per-session SUMMARY — counts and metadata
only, never prompt/response text (the one exception is `title`, the AI-generated one-line
title Claude Code itself already writes to the transcript as an `ai-title` line).

Incremental by BYTE OFFSET: <state_dir>/sessions.json keyed by source_path -> {offset, size,
mtime, partial_state, summary, entrypoint_checked}. A refresh() only reads the bytes appended
after `offset`; if the file is now shorter than `offset` (rotated/rewritten) it is re-parsed
from scratch. `entrypoint_checked` is registry bookkeeping, not a session field — it is never
in SUMMARY_FIELDS/PARTIAL_STATE_FIELDS and never reaches a consumer; it only remembers whether
_backfill_entrypoint's head scan has already run for this file, so a miss is never retried
(see _backfill_entrypoint). The transcript format is internal and undocumented: parsing is
best-effort per line — a bad line is skipped, never fatal.

Retention: summaries survive their source file disappearing (rotation is normal; history is
the point, same as usage.py). They are pruned only once `ended` is older than
cfg.activity.retention_days (default 365).
"""
import json, os, re, tempfile, threading, time

from . import scan, usage

_COMMIT = re.compile(r"\bgit\s+commit\b")
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

_HEAD_LINES = 40   # guard for _backfill_entrypoint: observed worst case is line 5, this is 8x that

SUMMARY_FIELDS = ("session_id", "project", "cwd_changed", "cwd", "branch", "tool", "title",
                   "started", "ended", "duration_s", "turns", "tool_calls", "files_touched",
                   "agents", "skills", "commits", "tokens", "subagent_tokens", "subagents",
                   "sidechain_lines", "version", "source_path", "size", "mtime", "offset",
                   "entrypoint", "last_tools", "subagent_rows")

PARTIAL_STATE_FIELDS = ("session_id", "cwd_counts", "branch", "version", "title", "started",
                        "ended", "turns", "tool_calls", "files_touched", "agents", "skills",
                        "commits", "tokens", "sidechain_lines", "subagent_files", "entrypoint",
                        "last_tools")

_LAST_TOOLS_CAP = 8
_TOOL_DETAIL_CAP = 120
_BASH_DETAIL_CAP = 80
_DETAIL_FILE_TOOLS = ("Read", "Edit", "Write", "NotebookEdit")

_REFRESH_LOCK = threading.Lock()


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
    return {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "thinking_lines": 0}


def _hydrate_tokens(tok):
    """Back-compat: a tokens dict persisted before thinking/thinking_lines existed. Filled in
    place, in ADDITION to whatever it already has (never overwrites a real accumulated value)."""
    tok.setdefault("thinking", 0)
    tok.setdefault("thinking_lines", 0)
    return tok


def _hydrate_state(state):
    """Back-compat: a partial_state persisted before entrypoint/thinking/last_tools existed.
    setdefault only — never clobbers a value already parsed. A session recorded before
    last_tools existed renders an empty list, never None: there is nothing meaningful to
    backfill (unlike entrypoint, a rolling "last 8" has no single value sitting near the top of
    an already-consumed transcript to recover). Defensive: last_tools must be a LIST -- a
    corrupt or hand-edited registry (None, a dict, a stray string) is coerced back to [] rather
    than left to break `.append`/`len()` on the next refresh."""
    state.setdefault("entrypoint", None)
    if not isinstance(state.get("last_tools"), list):
        state["last_tools"] = []
    _hydrate_tokens(state.setdefault("tokens", _empty_tokens()))
    return state


def _new_state():
    return {"session_id": None, "cwd_counts": {}, "branch": None, "version": None, "title": None,
            "started": None, "ended": None, "turns": 0, "tool_calls": {}, "files_touched": [],
            "agents": {}, "skills": {}, "commits": 0, "tokens": _empty_tokens(), "sidechain_lines": 0,
            "entrypoint": None, "last_tools": []}


def _tool_detail(name, inp):
    """One short, local-only descriptor for a tool_use block -- never exported (SUMMARY_FIELDS
    carries it, but snapshot._detail_row is a separate explicit whitelist that does not)."""
    if name == "Agent":
        d = inp.get("subagent_type") or ""
    elif name == "Skill":
        d = inp.get("skill") or ""
    elif name in _DETAIL_FILE_TOOLS:
        fp = inp.get("file_path") or ""
        d = os.path.basename(fp) if fp else ""
    elif name == "Bash":
        d = (inp.get("command") or "")[:_BASH_DETAIL_CAP]
    else:
        d = ""
    return d[:_TOOL_DETAIL_CAP]


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
        if d.get("entrypoint") and not state["entrypoint"]:
            state["entrypoint"] = d["entrypoint"]
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
            if "output_tokens_details" in usg:
                state["tokens"]["thinking_lines"] += 1
                otd = usg.get("output_tokens_details") or {}
                if isinstance(otd, dict):
                    state["tokens"]["thinking"] += otd.get("thinking_tokens", 0) or 0
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
                state["last_tools"].append({"name": name, "detail": _tool_detail(name, inp), "ts": ts})
                if len(state["last_tools"]) > _LAST_TOOLS_CAP:
                    state["last_tools"] = state["last_tools"][-_LAST_TOOLS_CAP:]
    return state


def _git_project_fallback(cwd, cfg_roots):
    """Fallback for a session whose cwd matches no scanned project (scan.py only registers a
    project when it finds a `.claude/` dir there): walk up from `cwd` looking for a git repo
    root (a `.git` dir or file, e.g. a worktree) while still inside one of `cfg_roots`. Found ->
    attribute the session to that repo, so project-os never silently hides real work just because
    the repo has no project-os-visible assets yet. Name is ALWAYS the path relative to the
    containing cfg root (e.g. root ~/Documents, repo ~/Documents/Webs/acme -> "Webs/acme") —
    deterministic regardless of what else happens to be scanned; a repo directly under a root
    naturally reduces to its basename. Returns (name, git_root) so the caller can also
    relativize files_touched against it, or None if no `.git` turns up before leaving every cfg
    root (or cwd/cfg_roots is empty)."""
    if not cwd:
        return None
    cfg_roots_r = [os.path.realpath(r) for r in (cfg_roots or [])]
    if not cfg_roots_r:
        return None
    cur = os.path.realpath(cwd)         # walked/matched in realpath form (robust to symlinked roots)
    raw_cur = cwd                       # walked in lockstep, kept in `cwd`'s own form: files_touched
                                         # entries come from the same raw domain as cwd, so the
                                         # returned git_root must match it or relativizing them fails
    while True:
        containing = next((r for r in cfg_roots_r if cur == r or cur.startswith(r.rstrip("/") + "/")), None)
        if containing is None:
            return None
        if os.path.exists(os.path.join(cur, ".git")):
            return os.path.relpath(cur, containing), raw_cur
        parent, raw_parent = os.path.dirname(cur), os.path.dirname(raw_cur)
        if parent == cur:
            return None
        cur, raw_cur = parent, raw_parent


def _guess_project_from_encoded_dir(source_path, roots):
    """Best-effort fallback when a session has no cwd-bearing lines at all: Claude Code encodes
    the cwd into the directory name by replacing '/' with '-'. Lossy (a real '-' in a path looks
    the same as an encoded '/'), so this is a guess, never treated as fact elsewhere."""
    enc = os.path.basename(os.path.dirname(source_path))
    return usage._project_of(enc.replace("-", "/"), roots) or "unknown"


def _subagents_dir(source_path):
    sid = os.path.splitext(os.path.basename(source_path))[0]
    return os.path.join(os.path.dirname(source_path), sid, "subagents")


def _subagents_count(source_path):
    d = _subagents_dir(source_path)
    if not os.path.isdir(d):
        return 0
    return sum(1 for f in os.listdir(d) if f.endswith(".jsonl"))


def _subagents_grew(source_path, subagent_files_state):
    """True if any subagents/*.jsonl file is now larger than the byte offset already recorded
    for it in `subagent_files_state` -- used in _refresh to defeat the PARENT transcript's own
    unchanged-mtime/size fast path, which would otherwise never re-run _subagent_tokens even
    though a subagent can keep writing long after the parent stops changing (the parent's own
    stat never reflects that growth)."""
    d = _subagents_dir(source_path)
    if not os.path.isdir(d):
        return False
    subagent_files_state = subagent_files_state or {}
    for f in os.listdir(d):
        if not f.endswith(".jsonl"):
            continue
        fp = os.path.join(d, f)
        try:
            size = os.path.getsize(fp)
        except OSError:
            continue
        entry = subagent_files_state.get(fp)
        recorded = entry.get("offset", 0) if isinstance(entry, dict) else 0
        if size > recorded:
            return True
    return False


def _subagent_tokens(source_path, state):
    """Tokens spent by subagents of this session — read INCREMENTALLY by byte offset, same idea
    as the session file's own parsing (Tarea 17): some of these transcripts grow past a few MB,
    and re-reading them in full on every refresh does not scale (R2). Progress per subagent file
    is kept in state["subagent_files"] = {path: {"offset", "tokens"}}, mutated in place so it
    rides along with the rest of the partial_state that refresh() persists. Kept SEPARATE from
    the session's own `tokens` (R3: never summed together)."""
    d = _subagents_dir(source_path)
    files_state = state.setdefault("subagent_files", {})
    total = _empty_tokens()
    if not os.path.isdir(d):
        return total
    for f in os.listdir(d):
        if not f.endswith(".jsonl"):
            continue
        fp = os.path.join(d, f)
        try:
            size = os.path.getsize(fp)
        except OSError:
            continue
        entry = files_state.get(fp)
        if entry is None or size < entry.get("offset", 0):
            entry = {"offset": 0, "tokens": _empty_tokens()}    # new, or shrunk/rotated: reparse from scratch
        _hydrate_tokens(entry.setdefault("tokens", _empty_tokens()))
        try:
            lines, new_offset = _read_new_lines(fp, entry["offset"])
        except Exception:
            lines, new_offset = [], entry["offset"]
        for raw in lines:
            try:
                d2 = json.loads(raw)
            except Exception:
                continue
            # Asymmetry, deliberate: the PARENT transcript's R6 skip excludes isSidechain lines
            # because they duplicate work already counted elsewhere in that same transcript. A
            # SUBAGENT transcript carries no such duplication -- every line in it is marked
            # isSidechain:true simply because it happened off the main conversation branch, and
            # skipping them here would fabricate 0 tokens for every subagent (confirmed on real
            # data: a 30-line subagent transcript, all isSidechain, ~916k real tokens read as 0).
            usg = ((d2.get("message") or {}).get("usage")) or {}
            entry["tokens"]["in"] += usg.get("input_tokens", 0) or 0
            entry["tokens"]["out"] += usg.get("output_tokens", 0) or 0
            entry["tokens"]["cache_read"] += usg.get("cache_read_input_tokens", 0) or 0
            entry["tokens"]["cache_write"] += usg.get("cache_creation_input_tokens", 0) or 0
            if "output_tokens_details" in usg:
                entry["tokens"]["thinking_lines"] += 1
                otd = usg.get("output_tokens_details") or {}
                if isinstance(otd, dict):
                    entry["tokens"]["thinking"] += otd.get("thinking_tokens", 0) or 0
        entry["offset"] = new_offset
        files_state[fp] = entry
        for k in total:
            total[k] += entry["tokens"][k]
    return total


_HASH_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$", re.IGNORECASE)


def _subagent_display_name(fp):
    """Human-readable name for a subagent transcript. Prefers the sibling <stem>.meta.json
    Claude Code writes next to it ("name" or "agentType") over the raw filename stem, which is
    often <type>-<16 hex chars>.jsonl -- showing that stem as-is would put a meaningless hash in
    front of the user. Falls back to the stem with a trailing 16-hex-char suffix stripped when
    there is no usable meta.json."""
    stem = os.path.splitext(os.path.basename(fp))[0]
    meta_path = os.path.join(os.path.dirname(fp), stem + ".meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if isinstance(meta, dict):
            name = meta.get("name") or meta.get("agentType")
            if isinstance(name, str) and name.strip():
                return name.strip()
    except Exception:
        pass
    return _HASH_SUFFIX_RE.sub("", stem)


def _subagent_rows(files_state):
    """One row per subagent transcript already tracked in state["subagent_files"] (populated by
    _subagent_tokens, called just before this in _finalize) -- no new state, purely derived.
    "tokens" is the sum of the four summable dimensions (in/out/cache_read/cache_write);
    thinking/thinking_lines are excluded, same convention as the aggregate. Honesty: an entry
    with no "tokens" dict at all (never actually measured -- a missing/corrupt state entry)
    reports tokens=None, never a fabricated 0; 0 is reported only once a real read summed to
    zero. Sorted by tokens descending, unmeasured (None) rows last."""
    rows = []
    for fp, entry in (files_state or {}).items():
        name = _subagent_display_name(fp)
        tok = entry.get("tokens") if isinstance(entry, dict) else None
        total = sum(tok.get(k, 0) or 0 for k in ("in", "out", "cache_read", "cache_write")) if isinstance(tok, dict) else None
        rows.append({"name": name, "tokens": total})
    rows.sort(key=lambda r: (r["tokens"] is None, -(r["tokens"] or 0)))
    return rows


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
    fd, tmp = tempfile.mkstemp(prefix=".sessions-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            json.dump(reg, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _backfill_entrypoint(fp):
    """Bounded scan of the first _HEAD_LINES lines of `fp` for a top-level `entrypoint` — for
    records parsed before the field existed, whose byte offset already sits past it. This
    function itself has no memory: it is refresh()'s `entrypoint_checked` marker that makes each
    call to it one-time per file, including a MISS (never found within the bound) — without that
    marker a file that genuinely never carries `entrypoint` would be rescanned on every refresh
    forever. Completely independent of the incremental machinery: never touches offset, never
    feeds _merge_lines, never moves a token/turn counter. Read-only, best-effort — any failure
    (missing file, bad JSON) yields None, never raises."""
    try:
        with open(fp, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= _HEAD_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("entrypoint"):
                    return d["entrypoint"]
    except Exception:
        pass
    return None


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


def _refresh(cfg, days=30):
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
            offset, state, checked = 0, _new_state(), False
        elif st.st_mtime == cached.get("mtime") and st.st_size == cached.get("size") and \
                not _subagents_grew(fp, (cached.get("partial_state") or {}).get("subagent_files")):
            # The parent transcript itself is unchanged, but a subagent can still be writing
            # long after the parent stops -- that growth is invisible to the parent's own stat,
            # so it must be checked separately before taking this fast path (falls through to
            # the incremental-resume branch below when it has).
            if not (cached.get("summary") or {}).get("entrypoint") and not cached.get("entrypoint_checked"):
                ep = _backfill_entrypoint(fp)
                cached["entrypoint_checked"] = True    # remember the LOOK, not just a hit -- a miss is never retried
                if ep:
                    cached.setdefault("summary", {})["entrypoint"] = ep
                    cached.setdefault("partial_state", {})["entrypoint"] = ep
                reg[fp] = cached
            continue
        elif st.st_size < cached.get("offset", 0):
            offset, state, checked = 0, _new_state(), False   # rotated/rewritten: reparse from scratch, one fresh look
        else:
            offset, state = cached["offset"], _hydrate_state(cached["partial_state"])
            checked = cached.get("entrypoint_checked", False)
            if not state.get("entrypoint") and not checked:
                state["entrypoint"] = _backfill_entrypoint(fp)
                checked = True
        try:
            new_lines, new_offset = _read_new_lines(fp, offset)
            state = _redact_partial_state(_merge_lines(state, new_lines))
            summary = _redact_unknown_fields(_finalize(state, fp, roots, new_offset, cfg_roots=cfg.get("roots") or []))
            reg[fp] = {"offset": new_offset, "size": st.st_size, "mtime": st.st_mtime,
                       "partial_state": state, "summary": summary,
                       "entrypoint_checked": checked or bool(summary.get("entrypoint"))}
        except Exception:
            continue                                     # one unreadable/corrupt transcript never aborts the rest
    from datetime import datetime
    now_local = datetime.now().astimezone()
    kept = _prune_by_retention(reg, retention_days, now_local)
    _save_registry(path, kept)
    return sorted((e["summary"] for e in kept.values()), key=lambda s: s.get("started") or "", reverse=True)


def refresh(cfg, days=30):
    """Refresh the registry while serializing the complete read/merge/write transaction."""
    with _REFRESH_LOCK:
        return _refresh(cfg, days)


def load(cfg):
    """Read the cached registry only — never opens a transcript. Used where a request must not
    pay parsing cost (server GET handler, MCP tool)."""
    reg = _load_registry(registry_path(cfg))
    return sorted((e["summary"] for e in reg.values()), key=lambda s: s.get("started") or "", reverse=True)


def _finalize(state, source_path, roots, offset, cfg_roots=()):
    from datetime import datetime
    roots = roots or {}
    counts = state["cwd_counts"]
    fallback_root = None
    if counts:
        cwd = max(counts, key=counts.get)
        cwd_changed = len(counts) > 1
        project = usage._project_of(cwd, roots)
        if project is None and cwd:
            fb = _git_project_fallback(cwd, cfg_roots)
            if fb:
                project, fallback_root = fb
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
    project = project or "unknown"                        # one sentinel for "no project", never None (R8)
    files = state["files_touched"]
    base = fallback_root or (roots.get(project) if project else None)
    if base:
        files = [os.path.relpath(f, base) if os.path.isabs(f) and (f == base or f.startswith(base + os.sep)) else f for f in files]
    try:
        st = os.stat(source_path)
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0
    subagent_tokens = _subagent_tokens(source_path, state)   # mutates state["subagent_files"] in place
    return {
        "session_id": state["session_id"] or os.path.splitext(os.path.basename(source_path))[0],
        "project": project, "cwd_changed": cwd_changed, "cwd": cwd, "branch": state["branch"],
        "tool": "claude", "title": state["title"], "entrypoint": state["entrypoint"],
        "started": started, "ended": ended,
        "duration_s": duration_s, "turns": state["turns"], "tool_calls": state["tool_calls"],
        "files_touched": files, "agents": state["agents"], "skills": state["skills"],
        "commits": state["commits"], "tokens": state["tokens"], "version": state["version"],
        "sidechain_lines": state["sidechain_lines"], "source_path": source_path,
        "size": size, "mtime": mtime, "offset": offset,
        "subagent_tokens": subagent_tokens, "subagents": _subagents_count(source_path),
        "last_tools": state.get("last_tools") or [],
        "subagent_rows": _subagent_rows(state.get("subagent_files")),
    }
