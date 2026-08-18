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
import json, os


def _read_new_lines(path, offset):
    """Bytes after `offset` -> (list of non-empty line strings, new_offset)."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    new_offset = offset + len(data)
    lines = [l for l in data.decode("utf-8", "replace").splitlines() if l.strip()]
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
    return state
