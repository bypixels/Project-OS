# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`project-os` is a zero-dependency Python 3.11+ CLI + local web UI that inspects a Claude Code (and
Codex CLI) environment: agents, skills, hooks, docs, usage. Its core invariant, stated in
`pyproject.toml` and enforced by tests: **it measures, warns and blocks — it never repairs, deletes
or edits on its own.** Every write goes through a guard, and every guard has a break-test. Keep it
that way when adding features (see "Guards" below).

## Commands

```sh
python -m unittest discover -s tests -v                        # full suite (stdlib unittest, no pytest)
python -m unittest discover -s tests -p "test_contract.py"     # one file
python -m unittest discover -s tests -p "test_breaks.py" -k hash   # one test by substring
(cd tests && python -m unittest test_guard.TestGuard.test_write_valid_agent_allowed -v)  # one method
PYTHONPATH=src python -m project_os check                      # run the CLI from source
PYTHONPATH=src python -m project_os --help                     # all subcommands (also `ui --port/--no-open`, `agents refs NAME`)
pip install . && project-os --version && project-os config --example   # what CI does after the tests
```

`python -m unittest tests.test_x` does NOT work: tests import `_helpers` (a `sys.path` shim that
adds `src/`), so always run via `discover -s tests` or from inside `tests/`. CI runs the suite on
Linux/macOS/Windows x Python 3.11–3.13 (`.github/workflows/ci.yml`); there is no linter or
formatter configured. `project-os fleet` needs curses (unavailable on some Pythons) — the web UI
is the portable path.

## Architecture (the parts that span files)

**Cache-first data flow.** `scan.py` walks `cfg["roots"]` for every `.claude/` dir plus the global
`~/.claude` and `~/.codex`, and writes ONE file: `<state_dir>/scan.json`. Everything else reads
that cache via `scan.ensure(cfg)` (`roster.py`, `skills.py`, `harness.py`, `projects.py`,
`check.py`, `server.py`, `mcp.py`, `snapshot.py`). `ensure()` only scans when NO cache exists;
after that everything reads the stale cache until `project-os scan` or the UI's `/api/rescan`.
`scan.project_roots(cfg, data)` -> `{name: abs_root}` (incl. `"global"`) is the shared "which
project owns this path" map used by `usage.py`, `docs.py`, `live.py` and `guard.py`. Slow parts
are opt-in (`--worktrees` runs `du`, `--mcp` shells out to `claude mcp list`) and gated by
`cfg["scan"]`. If a feature needs new data about the environment, add it to the scan output rather
than re-walking the disk in a consumer. The MCP tab (`App.api_mcp()`, `GET /api/mcp`) is a pure
reader of `data["mcp"]` — the servers `scan.py`'s `mcp_servers()` already collected under
`--mcp` — sorted failed > auth > unverified > ok with counts; it never triggers a scan or shells
out itself, and it is absent from `project-os hub` by omission (`"mcp"` is simply not in the hub half
of `VIEWS` in `static/index.html`), so there is no hub route to guard.

**One contract, four consumers.** `contract.py` is the single validator for agent frontmatter
(categories: `valid` / `warnings` / `invalid` / `document` / `error`; `document` = `.md` without
frontmatter, deliberately NOT an agent and NOT a fix suggestion). Severity of each field is
config-driven (`contract.critical` / `contract.warn`), and per-tool defaults (`TOOL_DEFAULTS`:
Codex agents are TOML with only name+description) layer over the generic config. Consumers:
`check.py` (health), `roster.py` (CLI `agents` + UI + create guard), `guard.py` (PreToolUse hook —
reconstructs the post-Edit file text and validates *that*), `repo.py` (`check --repo`, CI mode:
reads `.project-os.toml` from the repo root only — a separate path that never goes through
`config.load`; no home, no cache). Change validation rules in `contract.py` only.

**Config and platform paths.** `config.py` has `DEFAULTS` for every key; `host.default_dirs()`
picks XDG (`~/.config/project-os`, `~/.local/share/project-os`) vs `%APPDATA%`/`%LOCALAPPDATA%` on
Windows. Tool homes are always `~/.claude` and `~/.codex`. `$PROJECT_OS_CONFIG` overrides the
config path.
`grep` (`roster.py` `references()`) and `du` (`scan.py` worktree sizes) are used when present with
pure-Python fallbacks (Windows) — keep both branches when touching them. `host.notify()` passes text to `osascript`/PowerShell via env vars,
never interpolated into the script (injection guard, `tests/test_platform.py`).

**Usage is best-effort, incremental, and attributed by cwd.** `usage.refresh()` (called by
`roster.py`/`server.py`/`check.py`) no longer re-greps the whole `~/.claude/projects/` tree on
every call: `<state_dir>/usage-history.json` keeps a byte-`offset` per source `.jsonl`, so a
refresh only reads what was appended since last time (same idea as `sessions.py`'s registry,
independent implementation — `usage._read_new_lines`/`_scan_file` duplicate `sessions.py`'s
reader rather than import it, to avoid a cycle). Each new line's `subagent_type` / `Skill` hit is
credited to the project whose root contains the line's `cwd` (longest root wins, symlinks
resolved on both sides), which is what distinguishes homonymous agents across projects. Per-file
baselines are aggregated and reconciled against `<state_dir>/usage-agents.json` /
`usage-skills.json` via `usage._accumulate`/`_file_delta` — a diff against the registry's
previous total, not a raw re-count, so a file that shrinks (rotated/rewritten) corrects the total
instead of double-counting it; `usage.merge` still guarantees dates never regress
(break-tested). A single `refresh()` call updates BOTH `usage-agents.json` and
`usage-skills.json` under the hood (`_refresh_both`), and the whole read-scan-write sequence is
serialized by a module-level lock (`server.py` runs `ThreadingHTTPServer`). There is no
`grep` path anymore: `_read_new_lines`/`_scan_file` (plain `open()`, incremental by byte offset,
substring pre-filter before any regex) is the only reader on every platform, so `usage.py` no
longer needs a Windows fallback. If the transcript format changes, usage becomes "unknown" —
nothing else may break.

**Sessions carry `entrypoint` and reasoning tokens, both backfilled once.** `sessions.py`'s
per-session state also tracks the raw `entrypoint` string a transcript line carries (observed
values `cli`, `sdk-py`, `sdk-ts`, `sdk-cli`) and `tokens.thinking` / `tokens.thinking_lines`, both
in `SUMMARY_FIELDS` and `PARTIAL_STATE_FIELDS` alongside the older fields. Because `refresh()`
reads each transcript incrementally by byte offset, a session already parsed past the line that
carries `entrypoint` would keep it `None` forever — that was a real, measured defect (735 sessions
stuck at `None`) before `_backfill_entrypoint()` was added: a bounded, one-time head scan
(`_HEAD_LINES = 40`) that recovers it for exactly those pre-existing records, entirely outside the
incremental machinery (it never touches `offset`, never calls `_merge_lines`, never moves a
turn/token counter). Do not remove this backfill to "simplify" the parser — without it, every
session recorded before the field existed stays blank forever, since its offset never revisits
that line again. `entrypoint` does not reach `project-os export`, `project-os hub`, or the MCP
  server: `snapshot._detail_row` is an explicit whitelist that omits both `entrypoint` and all
  reasoning keys. The exported detail token object is itself restricted to the historical `in`,
  `out`, `cache_read`, and `cache_write` counters. Therefore neither entrypoint nor reasoning
  reaches `project-os export`, `project-os hub`, or the MCP server; these are local counters,
  never exported text.
  `tokens.thinking_lines == 0`
means the transcript predates the field (before 2026-08-12), not "no reasoning happened" —
callers must render that as unknown (the UI's "n/a"), never as a bare zero.

**Server = thin HTTP over the same modules.** `server.py` defaults to `127.0.0.1` and accepts only
localhost or a configured loopback address (LAN addresses are rejected before server creation), serves
`static/index.html` (single file, `__TOKEN__`/`__LANG__` substituted), and requires an
`X-ProjectOS-Token` header (per-process `secrets.token_urlsafe`) on every POST. Every request (server
and hub) must carry a localhost/loopback `Host` header (`host_allowed`, 421 otherwise) and every
POST a localhost/loopback `Origin` when present (`origin_allowed`, 403) — no other configured
address is trusted. This is the anti-DNS-rebinding guard, without which a malicious page could
read the token off `/`. POST routes are the only write
paths in the whole program: archive agent/skill, create agent, save doc, open (confined to project
roots + tool homes + state dir, `_open_allowed`), commit, rescan, hooks-install (`guard.hooks_write`
only ever wires `project-os` itself — `_cmd_is_project_os`, never bypassed by `force`). `gitops.commit_path` only ever runs `git add -A -- <path>` + `git commit -- <path>` (never
a bare `-A`) and refuses mid-merge/rebase. `docs.py` guards saves with a content hash taken at
read time, an allowlist of roots (no `../`), a "live agent working here" check, and a backup +
atomic write — backups mirror the document's own subdirectory under
`<state_dir>/doc-backups/<project>/` (`Docs._backup_loc`, confined inside the project's backups
dir independently of `_resolve`'s own confinement to the project root), so two documents with the
same basename in different subdirectories keep separate histories instead of interleaving one
flat directory. `Docs.versions()` / `version_text()` are read-only siblings of `save()` — no
restore path lives in `docs.py` itself. A version's `ambiguous` flag means its listing came from
the flat directory that same-named documents once shared before this fix; it stays true for new
backups of a root-level document too (mirroring an empty subdirectory is a no-op), so it is a
warning about possible contamination, not an age marker. Three read-only GETs were added on top
of this, no new POST: `GET /api/mcp` (above), and `GET /api/doc-versions` / `GET /api/doc-version`
— the latter also builds a unified diff against the current file and a restore `command`, same
discipline as `worktrees.py`'s `script()`: generated for the user to review and run, never
executed by project-os, and `null` with a `command_reason` when either path is unsafe to embed in a
shell argument (`WT._is_unsafe`, reused rather than reimplemented).

**Codex + drift.** `scan.py` also reads `~/.codex` (agents `*.toml`, skills, sessions);
`drift.py` compares the two tools: twin agents with different bodies, `CLAUDE.md` vs `AGENTS.md`
per project (`linked` / `copy` / `bridge` / `diverged`), and copied skills that no longer match.
Every roster row carries a `tool` of `claude` or `codex`.

**Strings.** All user-facing CLI/UI text lives in `i18n.py` `STRINGS["en"]` and `["es"]`, keyed
like `check.dead_hooks` / `check.dead_hooks.d`. Add both languages when adding a message. The web
UI has its own, separate `I18N` string table (en/es) embedded in `static/index.html` — it does not
read from `i18n.py`.

**Hooks (`guard.py`).** `project-os guard` exits 2 with a reason on stderr to block a write, 0
otherwise. Any failure of the guard itself must exit 0 — a broken guard must never lock the user
out. `project-os hooks --write` merges into `settings.json` idempotently with a backup.

## Guards and break-tests (the rule that matters most)

Every place that refuses or protects a write is a "guard": kebab/filename rule in `contract.py`,
hash / allowlist / working / backup checks in `docs.py`, dead-hook detection in `harness.py`,
non-regressing usage merge. `tests/test_breaks.py` disables each guard in memory with
`mock.patch.object` and asserts a canary would go red — so a guard cannot be silently deleted.
**When you add a new guard, add a matching break-test there**; when you add a write path, it needs
a guard first. Do not add auto-repair, auto-archive, or unconfirmed writes: "tell the user the exact
command" is the design, not a missing feature.

## Test fixtures

`tests/_env.py` builds a synthetic environment in a temp dir (global `~/.claude`, one project
`alpha` with a shadowing agent, a document-in-agents/, one wired + one dead hook, a `MEMORY.md`,
fake transcript lines, and a synthetic `~/.codex` with a twin agent and a copied skill), and
returns `Env.cfg` merged over `config.DEFAULTS` with `live.provider = "none"` and slow scans off.
Use it instead of touching the real home; call `env.cleanup()`.

## Conventions

- Module docstrings state exactly what the module writes (usually "nothing"). Keep that contract
  honest when editing.
- No third-party dependencies (`dependencies = []`); stdlib only, including `tomllib`.
- README's test count is a moving number; the suite is the source of truth.
