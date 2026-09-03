"""`project-os check --repo PATH` — validate ONE repository on its own, for CI.
Needs no user home, no cache, no history: only the repo. The contract can be tuned per repo in
`.project-os.toml` at the repo root; without it, defaults apply. Exit 1 on invalid agents (or on
warnings too when `[check] strict = true`). `.project-os.toml`'s `[desired]` table (see
desired.py) is ignored here: it compares against the local scan cache, which CI mode never has."""
import os, tomllib
from .contract import Contract
from . import drift


def load_repo_config(root):
    """The repo's own `.project-os.toml`, or `{}` if absent. Returns `None` (never raises) if
    the file exists but is not valid TOML -- `check_repo` turns that into a clean FAIL rather
    than a raw traceback."""
    p = os.path.join(root, ".project-os.toml")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def check_repo(root):
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        return {"root": root, "agents_total": 0, "invalid": [], "warnings": [], "documents": [],
                "agents_md": "none", "strict": False, "exit": 2, "error": f"repo path does not exist: {root}"}
    rc = load_repo_config(root)
    if rc is None:
        p = os.path.join(root, ".project-os.toml")
        return {"root": root, "agents_total": 0, "invalid": [], "warnings": [], "documents": [],
                "agents_md": "none", "strict": False, "exit": 2, "error": f".project-os.toml could not be parsed as valid TOML: {p}"}
    strict = bool((rc.get("check") or {}).get("strict", False))
    C = Contract({"contract": rc.get("contract", {})})
    agents_dir = os.path.join(root, ".claude", "agents")
    res = C.validate_dir(agents_dir) if os.path.isdir(agents_dir) else []
    inv = [{"name": r.name, "reasons": r.critical} for r in res if r.category in ("invalid", "error")]
    wrn = [{"name": r.name, "reasons": r.warnings} for r in res if r.category == "warnings"]
    docs = [r.name for r in res if r.category == "document"]
    am = drift.rules_file(root)["status"]
    exit_ = 1 if inv or (strict and wrn) else 0
    return {"root": root, "agents_total": sum(1 for r in res if r.is_agent), "invalid": inv, "warnings": wrn,
            "documents": docs, "agents_md": am, "strict": strict, "exit": exit_}


def render(r):
    if r.get("error"):
        return f"project-os check --repo {r['root']}\n  error: {r['error']}\n  result: FAIL (usage error)"
    out = [f"project-os check --repo {r['root']}", f"  agents: {r['agents_total']} · invalid: {len(r['invalid'])} · warnings: {len(r['warnings'])} · documents: {len(r['documents'])} · AGENTS.md: {r['agents_md']}"]
    for x in r["invalid"]:
        out.append(f"  INVALID  {x['name']}: " + "; ".join(x["reasons"]))
    for x in r["warnings"]:
        out.append(f"  warning  {x['name']}: " + "; ".join(x["reasons"]))
    if r["documents"]:
        out.append(f"  documents in agents/ (not agents): {', '.join(r['documents'])}")
    out.append("  result: " + ("FAIL" if r["exit"] else "ok") + (" (strict)" if r["strict"] else ""))
    return "\n".join(out)


EXAMPLE_TOML = '''# .project-os.toml — contract for THIS repository (used by `project-os check --repo .`, e.g. in CI)
[contract]
models = ["sonnet", "opus", "haiku"]
critical = ["name", "description"]
warn = ["model", "tools"]

[check]
strict = false        # true: warnings also fail the check

# [desired]             # optional, ignored by `check --repo` (CI mode has no scan cache); read
#                        # by plain `project-os check` against your local environment scan.
# [desired.agents]
# required = ["code-reviewer"]
# [desired.skills]
# required = ["deploy"]
# [desired.mcp]
# required = ["postgres"]
# [desired.memory]
# max_age_days = 14
# [desired.docs]
# agents_md = "linked"
# [desired.verification]
# ci = true
# tests = "tests"
# gates = ["python -m unittest discover -s tests"]
'''

CI_YAML = '''# .github/workflows/project-os.yml
name: project-os
on: [pull_request]
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install project-os
      - run: project-os check --repo .
'''
