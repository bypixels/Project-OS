"""Desired state: a project can declare in its OWN `.project-os.toml` ([desired] table) what
its agent environment SHOULD have, and `check` reports gaps against the scan. Read-only —
writes nothing, ever; it only ever compares.

Vocabulary (all sub-tables optional):
    [desired.agents]  required = [...]   # by name, project's own claude agents OR global
    [desired.skills]  required = [...]   # same, excluding entries flagged invalid
    [desired.mcp]     required = [...]   # by name in data["mcp"]["servers"]
    [desired.memory]  max_age_days = N   # <root>/.claude/MEMORY.md, live-read (like drift.rules_file)
    [desired.docs]    agents_md = "..."  # compared to drift.rules_file(root)["status"]

`gaps()` never raises, no matter what `.project-os.toml` contains: syntactically invalid TOML
and structurally valid-but-wrong-typed TOML (a string where a list was expected, a table where a
scalar was expected, etc.) both become a gap in the returned list instead of an exception --
`check.run()` calls this once per project with no try/except of its own, so a crash here would
take down the whole `check` run, not just this project's row.
"""
import math, os, time, tomllib
from . import drift

_KNOWN_TABLES = {"agents", "skills", "mcp", "memory", "docs"}
_KNOWN_SUBKEYS = {
    "agents": {"required"},
    "skills": {"required"},
    "mcp": {"required"},
    "memory": {"max_age_days"},
    "docs": {"agents_md"},
}
_DOC_STATUSES = {"linked", "copy", "bridge", "diverged", "missing", "only-agents", "broken-link", "unreadable"}


def load(root):
    """The `[desired]` table of `<root>/.project-os.toml`. Empty dict if the file is absent or
    has no `[desired]` table -- callers must treat that as silent opt-out, never a gap. If the
    file is not even valid TOML (a genuine syntax error), this must not raise: it returns
    `{"_malformed": True}` so `gaps()` can surface it as a single `malformed` gap instead of
    `check` crashing on a broken file. The `[desired]` key itself can also be present in
    otherwise-VALID TOML but not be a table at all (e.g. `desired = 1`, `desired = "x"`, or a
    FALSY wrong type like `desired = false` / `""` / `[]`) -- that is returned as-is (not coerced
    to `{}` and not treated as `_malformed`, since the file parsed fine) so `gaps()` can flag it
    as a `bad_value` instead, a different diagnosis from a syntax error; a bare `doc.get("desired")
    or {}` would silently swallow a falsy wrong type into this same opt-out, which is why the
    dict-type check happens BEFORE the emptiness check below. Only a genuinely ABSENT key, or a
    present key whose value actually IS a dict (empty or not), reaches the opt-out/normal path."""
    p = os.path.join(root, ".project-os.toml")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "rb") as f:
            doc = tomllib.load(f)
    except Exception:
        return {"_malformed": True}
    if "desired" not in doc:
        return {}
    return doc["desired"]


def _agent_names(rows):
    return {r["name"] for r in rows if r.get("frontmatter")}


def _skill_names(rows):
    return {r["name"] for r in rows if not r.get("invalid")}


def _required_list(table, table_name, out):
    """Validates `table["required"]` (if present) as a list of str -- the only shape every
    caller below may safely iterate. Appends a `bad_value` gap (dotted "<table_name>.required")
    and returns None for anything else, INCLUDING a bare string: a string is iterable in Python,
    so without this check `required = "reviewer"` would silently iterate its characters and
    report each one as a missing agent named `r`, `e`, `v`, ... Returns `[]` (not a gap) when the
    key is simply absent -- that means "no requirement declared", not "declared wrong"."""
    if "required" not in table:
        return []
    val = table["required"]
    if isinstance(val, list) and all(isinstance(x, str) for x in val):
        return val
    out.append({"kind": "bad_value", "field": f"{table_name}.required"})
    return None


def gaps(cfg, project_entry, data):
    """Gap dicts for one project's declared [desired] table against the scan `data`. Each gap is
    {"kind": ..., ...fields for that kind}; empty list if there is no [desired] table (or it is
    empty) -- that is the "opt-out, stay silent" case `check.py` relies on. Never raises: a
    genuine TOML syntax error is the only case that becomes `malformed`; every wrong-typed value
    in otherwise-valid TOML (a subtable that isn't a table, `required` that isn't a list of str,
    `max_age_days` that isn't a finite non-negative number, `agents_md` that isn't a string, or
    `[desired]` itself not being a table) becomes a `bad_value` gap naming the dotted key instead
    of a crash -- `malformed` and `bad_value` are deliberately different diagnoses (syntax error
    vs. wrong type) so the message points the user at the right fix. A typo'd key INSIDE a known
    subtable is reported via the same `unknown_key` gap as a typo'd top-level table -- it must
    never disappear silently."""
    root = project_entry["path"]
    desired = load(root)
    # The type check MUST run before the emptiness check: a FALSY wrong type (`desired = false`
    # / `""` / `[]`) must reach `bad_value` below, not the silent opt-out that only genuinely
    # applies to an absent key or an (empty or non-empty) TABLE.
    if not isinstance(desired, dict):
        return [{"kind": "bad_value", "field": "desired"}]
    if not desired:
        return []
    if desired.get("_malformed"):
        return [{"kind": "malformed"}]

    out = []
    unknown = set(desired) - _KNOWN_TABLES

    def subtable(name):
        """desired[name] if it is a dict (and records any unknown keys inside it); appends a
        `bad_value` gap and returns None if it is present but not a dict; None if absent."""
        val = desired.get(name)
        if val is None:
            return None
        if not isinstance(val, dict):
            out.append({"kind": "bad_value", "field": name})
            return None
        unknown.update(f"{name}.{k}" for k in set(val) - _KNOWN_SUBKEYS[name])
        return val

    ag = subtable("agents")
    if ag is not None:
        req = _required_list(ag, "agents", out)
        if req:
            have = _agent_names(project_entry.get("agents", [])) | _agent_names(data.get("global", {}).get("agents", []))
            for name in req:
                if name not in have:
                    out.append({"kind": "agent", "name": name})

    sk = subtable("skills")
    if sk is not None:
        req = _required_list(sk, "skills", out)
        if req:
            have = _skill_names(project_entry.get("skills", [])) | _skill_names(data.get("global", {}).get("skills", []))
            for name in req:
                if name not in have:
                    out.append({"kind": "skill", "name": name})

    mcp = subtable("mcp")
    if mcp is not None:
        req = _required_list(mcp, "mcp", out)
        if req:
            mcp_data = data.get("mcp", {}) or {}
            checked = bool(mcp_data.get("checked"))
            servers = {s["name"] for s in mcp_data.get("servers", [])}
            for name in req:
                if not checked:
                    out.append({"kind": "mcp_unverifiable", "name": name})
                elif name not in servers:
                    out.append({"kind": "mcp_missing", "name": name})

    mem = subtable("memory")
    if mem is not None and "max_age_days" in mem:
        max_age = mem["max_age_days"]
        # bool is an int subclass in Python -- isinstance(True, int) is True -- so it must be
        # excluded explicitly, ahead of the numeric check, or `max_age_days = true` would pass.
        # nan/inf must be rejected too: `nan < 0` is False and every later comparison against a
        # non-finite value (`age_days > max_age`) is also False, so without `math.isfinite` the
        # staleness check would silently never fire again instead of erroring loudly now.
        if (isinstance(max_age, bool) or not isinstance(max_age, (int, float))
                or max_age < 0 or not math.isfinite(max_age)):
            out.append({"kind": "bad_value", "field": "memory.max_age_days"})
        else:
            mpath = os.path.join(root, ".claude", "MEMORY.md")
            if not os.path.isfile(mpath):
                out.append({"kind": "memory_missing"})
            else:
                try:
                    mtime = os.path.getmtime(mpath)
                except OSError:
                    # TOCTOU: deleted between the isfile() check above and here. Same gap as if
                    # isfile() itself had caught the deletion -- accurate at this instant.
                    out.append({"kind": "memory_missing"})
                else:
                    # Compare fractional days, not an int-truncated value -- truncating first
                    # tolerated up to just under a full extra day past max_age before ever
                    # reporting stale. The displayed value is rounded to one decimal, not
                    # truncated to a whole day, for the same reason (14.3 must not read as 14).
                    age_days = (time.time() - mtime) / 86400
                    if age_days > max_age:
                        out.append({"kind": "memory_stale", "age_days": round(age_days, 1), "max_age_days": max_age})

    docs = subtable("docs")
    if docs is not None and "agents_md" in docs:
        want = docs["agents_md"]
        if not isinstance(want, str):
            out.append({"kind": "bad_value", "field": "docs.agents_md"})
        elif want not in _DOC_STATUSES:
            out.append({"kind": "docs_invalid_value", "value": want})
        else:
            actual = drift.rules_file(root)["status"]
            if actual != want:
                out.append({"kind": "docs_mismatch", "expected": want, "actual": actual})

    if unknown:
        out.insert(0, {"kind": "unknown_key", "keys": sorted(unknown)})

    return out
