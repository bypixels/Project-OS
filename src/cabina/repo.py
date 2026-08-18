"""`cabina check --repo PATH` — validate ONE repository on its own, for CI.
Needs no user home, no cache, no history: only the repo. The contract can be tuned per repo in
`.cabina.toml` at the repo root; without it, defaults apply. Exit 1 on invalid agents (or on
warnings too when `[check] strict = true`)."""
import os, tomllib
from .contract import Contract
from . import drift


def load_repo_config(root):
    p = os.path.join(root, ".cabina.toml")
    if not os.path.isfile(p):
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def check_repo(root):
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        return {"root": root, "agents_total": 0, "invalid": [], "warnings": [], "documents": [],
                "agents_md": "none", "strict": False, "exit": 2, "error": f"repo path does not exist: {root}"}
    rc = load_repo_config(root)
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
        return f"cabina check --repo {r['root']}\n  error: {r['error']}\n  result: FAIL (usage error)"
    out = [f"cabina check --repo {r['root']}", f"  agents: {r['agents_total']} · invalid: {len(r['invalid'])} · warnings: {len(r['warnings'])} · documents: {len(r['documents'])} · AGENTS.md: {r['agents_md']}"]
    for x in r["invalid"]:
        out.append(f"  INVALID  {x['name']}: " + "; ".join(x["reasons"]))
    for x in r["warnings"]:
        out.append(f"  warning  {x['name']}: " + "; ".join(x["reasons"]))
    if r["documents"]:
        out.append(f"  documents in agents/ (not agents): {', '.join(r['documents'])}")
    out.append("  result: " + ("FAIL" if r["exit"] else "ok") + (" (strict)" if r["strict"] else ""))
    return "\n".join(out)


EXAMPLE_TOML = '''# .cabina.toml — contract for THIS repository (used by `cabina check --repo .`, e.g. in CI)
[contract]
models = ["sonnet", "opus", "haiku"]
critical = ["name", "description"]
warn = ["model", "tools"]

[check]
strict = false        # true: warnings also fail the check
'''

CI_YAML = '''# .github/workflows/cabina.yml
name: cabina
on: [pull_request]
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install cabina
      - run: cabina check --repo .
'''
