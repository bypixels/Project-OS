"""Desired state: a project can declare in its OWN `.project-os.toml` ([desired] table) what
its agent environment SHOULD have, and `check` reports gaps against the scan. Read-only —
writes nothing, ever; it only ever compares.

Vocabulary (all sub-tables optional):
    [desired.agents]  required = [...]   # by name, project's own claude agents OR global
    [desired.skills]  required = [...]   # same, excluding entries flagged invalid
    [desired.mcp]     required = [...]   # by name in data["mcp"]["servers"]
    [desired.memory]  max_age_days = N   # <root>/.claude/MEMORY.md, live-read (like drift.rules_file)
    [desired.docs]    agents_md = "..."  # compared to drift.rules_file(root)["status"]
"""
import os, time, tomllib
from . import drift

_KNOWN_TABLES = {"agents", "skills", "mcp", "memory", "docs"}
_DOC_STATUSES = {"linked", "copy", "bridge", "diverged", "missing", "only-agents", "broken-link", "unreadable"}


def load(root):
    """The `[desired]` table of `<root>/.project-os.toml`. Empty dict if the file is absent or
    has no `[desired]` table -- callers must treat that as silent opt-out, never a gap. If the
    file exists but is not valid TOML, this must not raise: it returns `{"_malformed": True}` so
    `gaps()` can surface it as a single gap instead of `check` crashing on a broken file."""
    p = os.path.join(root, ".project-os.toml")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "rb") as f:
            doc = tomllib.load(f)
    except Exception:
        return {"_malformed": True}
    return doc.get("desired") or {}


def _agent_names(rows):
    return {r["name"] for r in rows if r.get("frontmatter")}


def _skill_names(rows):
    return {r["name"] for r in rows if not r.get("invalid")}


def gaps(cfg, project_entry, data):
    """Gap dicts for one project's declared [desired] table against the scan `data`. Each gap is
    {"kind": ..., ...fields for that kind}; empty list if there is no [desired] table (or it is
    empty) -- that is the "opt-out, stay silent" case `check.py` relies on."""
    root = project_entry["path"]
    desired = load(root)
    if not desired:
        return []
    if desired.get("_malformed"):
        return [{"kind": "malformed"}]

    out = []
    unknown = sorted(set(desired) - _KNOWN_TABLES)
    if unknown:
        out.append({"kind": "unknown_key", "keys": unknown})

    ag = desired.get("agents")
    if isinstance(ag, dict):
        have = _agent_names(project_entry.get("agents", [])) | _agent_names(data.get("global", {}).get("agents", []))
        for name in ag.get("required") or []:
            if name not in have:
                out.append({"kind": "agent", "name": name})

    sk = desired.get("skills")
    if isinstance(sk, dict):
        have = _skill_names(project_entry.get("skills", [])) | _skill_names(data.get("global", {}).get("skills", []))
        for name in sk.get("required") or []:
            if name not in have:
                out.append({"kind": "skill", "name": name})

    mcp = desired.get("mcp")
    if isinstance(mcp, dict):
        mcp_data = data.get("mcp", {}) or {}
        checked = bool(mcp_data.get("checked"))
        servers = {s["name"] for s in mcp_data.get("servers", [])}
        for name in mcp.get("required") or []:
            if not checked:
                out.append({"kind": "mcp_unverifiable", "name": name})
            elif name not in servers:
                out.append({"kind": "mcp_missing", "name": name})

    mem = desired.get("memory")
    if isinstance(mem, dict) and "max_age_days" in mem:
        max_age = mem["max_age_days"]
        mpath = os.path.join(root, ".claude", "MEMORY.md")
        if not os.path.isfile(mpath):
            out.append({"kind": "memory_missing"})
        else:
            age_days = int((time.time() - os.path.getmtime(mpath)) / 86400)
            if age_days > max_age:
                out.append({"kind": "memory_stale", "age_days": age_days, "max_age_days": max_age})

    docs = desired.get("docs")
    if isinstance(docs, dict) and "agents_md" in docs:
        want = docs["agents_md"]
        if want not in _DOC_STATUSES:
            out.append({"kind": "docs_invalid_value", "value": want})
        else:
            actual = drift.rules_file(root)["status"]
            if actual != want:
                out.append({"kind": "docs_mismatch", "expected": want, "actual": actual})

    return out
