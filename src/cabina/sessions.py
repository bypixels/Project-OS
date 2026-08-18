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
