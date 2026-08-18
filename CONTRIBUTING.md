# Contributing to cabina

## Running the test suite

Stdlib `unittest`, no pytest, no third-party dependencies.

```sh
python -m unittest discover -s tests -v                        # full suite
python -m unittest discover -s tests -p "test_contract.py"     # one file
python -m unittest discover -s tests -p "test_breaks.py" -k hash   # one test by substring
(cd tests && python -m unittest test_guard.TestGuard.test_write_valid_agent_allowed -v)  # one method
```

`python -m unittest tests.test_x` does **not** work: tests import `_helpers` (a `sys.path` shim
that adds `src/`), so always run via `discover -s tests` or from inside `tests/`.

CI runs the suite on Linux/macOS/Windows x Python 3.11-3.13 (`.github/workflows/ci.yml`). There is
no linter or formatter configured in CI; a `[tool.ruff]` section in `pyproject.toml` exists for
local, opt-in linting only (`ruff check .`) — it never blocks a build.

## The core invariant: guards and break-tests

Cabina's whole design rests on one rule, stated in `pyproject.toml`'s description and enforced by
tests: **it measures, warns and blocks — it never repairs, deletes or edits on its own.** Every
write goes through a "guard" (a kebab/filename rule, a hash/allowlist/backup check, dead-hook
detection, a non-regressing usage merge) and every guard has a break-test in
`tests/test_breaks.py` that disables it in memory (`mock.patch.object`) and asserts a canary goes
red.

- Adding a new write path? It needs a guard first.
- Adding a new guard? Add a matching break-test in `tests/test_breaks.py` in the same change —
  otherwise the guard can be silently deleted later without anything noticing.
- Do not add auto-repair, auto-archive, or unconfirmed writes. "Tell the user the exact command"
  is the design, not a missing feature.

## Adding user-facing strings

All CLI/UI text lives in `src/cabina/i18n.py`, keyed like `check.dead_hooks` /
`check.dead_hooks.d`. When you add a message, add it to **both** `STRINGS["en"]` and
`STRINGS["es"]` — never just one.

## Releasing

```sh
git tag -a v0.1.0 -m "AI Projects Monitor v0.1.0 — agents, skills, harness, docs, health check, live, MCP"
git push origin v0.1.0
```

PyPI publish is a manual step by the owner (`python -m build && twine upload dist/*`), never
automated.

## Workflow

1. Write a test that fails first (TDD: red, then green, then refactor).
2. Keep changes minimal — no third-party dependencies (`dependencies = []` in `pyproject.toml`
   stays empty), stdlib only, including `tomllib`.
3. Run the full suite before committing: `python -m unittest discover -s tests -v`.
4. Commit messages explain the "why", not just the "what".
