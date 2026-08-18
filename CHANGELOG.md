# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Session activity: `sessions.py` parses Claude Code transcripts incrementally (by byte offset)
  into per-session summaries — turns, tokens, tool calls, files touched, agents/skills used,
  commits — attributing sessions outside a `.claude/` dir to their git repo as a fallback.
- `cabina activity` CLI command and an Activity tab in the UI: session list, per-session detail,
  a 14-day timeline, an "active Ns ago" badge, and an aggregated project x machine view when no
  per-session detail is loaded.
- `cabina export --activity` (aggregated per project by default; `--detail` for per-session rows,
  `--titles` for session titles, `--project` to restrict to one project) — never exports `cwd` or
  absolute file paths.
- `cabina compare` now reports activity deltas between two exports when both carry activity data.
- MCP tool `cabina_activity` (requires a project; never returns titles, `cwd` or paths).
- `cabina brief` now includes a line with the last session recorded in the current project.
- `live.TranscriptProvider`: an additive "active" signal derived from transcript mtimes, layered
  on top of `herdr` rather than replacing it.
- `cabina hub DIR`: a read-only server that merges N `cabina export --activity` files from a
  shared folder into the same UI — no Live/Docs tabs, no write buttons, agent/project/harness
  rows keyed by name + machine so two machines with a same-named project or agent don't collide.
- **Health tab** in the UI: the same findings `cabina check` prints (severity, detail, exact
  fix with a Copy button), first tab and default view; hidden in hub mode. `GET /api/health`.
- **Install hooks from the Harness tab**: status of `guard`/`brief` in `settings.json`, editable
  command with live PATH resolution, Preview of the exact JSON to be merged, confirmation, backup.
  Guarded: refuses to wire a command that does not resolve on PATH (a dead hook) unless forced.
  `GET /api/hooks`, `POST /api/hooks-install`; break-tested. Backup names never collide.
- **Rescan with options** (`--mcp`, `--worktrees`) from the UI, plus `GET /api/scan-status`: the
  UI polls until the scan really finishes (no more fixed 45 s wait) and shows "scan: N ago".
- **Export** (`GET /api/export?activity&detail`, downloads a JSON; `--titles` deliberately not
  exposed) and **Compare** (upload another machine's export, see the delta) from the UI.
- **Health over time (Fase 3)**: `healthlog.py` keeps `<state_dir>/health.jsonl`, one
  `{when, crit, warn, info}` line per `cabina check` (full runs only, and `GET /api/health`),
  appended only when the counts change or a day has passed, pruned to `check.history_days`
  (default 180) atomically. `GET /api/health-history?days=N` serves the series.
- **Projects at a glance**: `GET /api/tiles` — one read-only tile per project with
  `last_session`, `active`, per-project `health` (crit/warn/info) and `open_findings_count`,
  active first; rendered as a compact grid with a 30-day health sparkline at the top of the
  Projects tab (never in hub mode). Nothing task-like by design (no status/assignee/free text).
- `cabina check` findings carry an optional `projects` list when the finding is genuinely about
  specific projects (invalid/warn agents, docs-in-agents, dead/broken hooks, stale worktrees,
  rules drift, never-invoked agents) — never guessed from text; global findings carry no key.

### Security

- The web server (and the hub) now reject any request whose `Host` header is not loopback or the
  configured bind host (HTTP 421), and any POST whose `Origin` is foreign (403) — closes the
  DNS-rebinding path by which a malicious page could read the per-process token off `/` and then
  POST with it. Break-tested.
- `POST /api/hooks-install` (and `cabina hooks --write --cmd`) only ever wire `cabina` itself
  (`cabina…` on PATH or `<python> -m cabina`; shell metacharacters refused; `force` cannot bypass
  it) — before, any command that resolved on PATH (`bash -c '…'`) could be written into
  `settings.json` as a hook. Break-tested.
- `POST /api/open` is confined to project roots, `~/.claude`, `~/.codex` and the state dir —
  before, any path on the machine could be handed to the OS opener. Break-tested.

### Fixed

- `usage.refresh()` no longer aborts (server 500 / CLI traceback) when a transcript disappears or
  becomes unreadable between `stat` and read: that file is skipped and retried next pass, the rest
  is counted — matching the module's "usage degrades to unknown, nothing else breaks" contract.
- `cabina mcp` refreshes its roster/scan every 30 s like the web server, instead of caching them
  for the whole (session-long) process: `cabina_agent` / `cabina_references` no longer answer
  from a snapshot taken at startup.
- UI: the I18N key `checking` was defined twice per language, so the Health "Re-check" and Compare
  busy states showed "checking references…"; the archive dialog now uses `checkingRefs`. A
  structural test asserts no duplicate keys and en/es parity in the UI string table.
- `export --detail` never carries absolute file paths (a username leak); they are counted as
  `files_outside` instead.
- `export --activity` refreshes the session registry itself, so a freshly exported machine is
  not reported empty.
- Sessions that map to no project use one sentinel (`unknown`) instead of falling through
  silently.
- `TranscriptProvider` reads the tail of the transcript, not the head.
- `sessions._read_new_lines` never consumes a partial trailing line from a transcript that is
  still being appended to.
- Hub: skips non-regular files in the shared folder (a FIFO there would hang every endpoint), and
  never crashes on an export missing optional fields.
- `cabina hooks` (with or without `--write`) reached the web server instead of its own code: the
  `--cmd` flag shared argparse's `dest="cmd"` with the subcommand name. Renamed to `hook_cmd`.
- `cabina check --repo PATH` reported `ok`/exit 0 for a path that does not exist (a typo in CI
  passed the job); now `error` + exit 2. A real repo without `.claude/agents/` still passes.
- `cabina compare` with a missing or invalid file printed a Python traceback; now a one-line
  `error:` on stderr and exit 2.
- The grouped agent-warning summary in `cabina check` cut the `overrides: global` hint at the
  colon inside the backticks; the `agents` table no longer truncates the detail mid-word.
- `/api/skills` refreshed usage (a full transcript scan) on every request; now cached for 30 s
  like the roster and invalidated on skill archive and on rescan.
- `/api/activity` ignored `days` in its response and always returned every session (~700 KB);
  it now filters by session start.
- The Live poll ran every second forever, even with the tab hidden; it now pauses while hidden,
  refreshes on return, and slows to every 5 s outside the Live view.
- The UI loaded all seven tabs at boot; Skills/Projects/Harness/Activity/Docs now load the first
  time their tab is opened (Rescan reloads only what was loaded).
- `STRINGS["es"]` carried 7 untranslated duplicate keys (silently shadowed); removed, with a
  structural test that rejects duplicates and enforces en/es parity.
- `cabina config --example` omitted several `DEFAULTS` keys (`[activity]`, `[hub]`,
  `contract.known_fields`, `scan.skip_dirs`, `live.active_seconds`, `docs.max_per_dir`) and
  showed a hardcoded Unix `state_dir`; now complete and per-platform.

### Changed

- Usage (`usage.py`) is incremental: it keeps a per-file byte-offset registry
  (`<state_dir>/usage-history.json`) and reads only new bytes, updating agents and skills in one
  pass. `cabina agents` and the first UI load drop from ~9-11 s to ~0.1 s warm (~3-5 s on the
  first run over 1.4 GB of history). Counts become a sum of per-file deltas (a rotated or truncated
  file corrects its own share; a deleted one never lowers the total); existing registries migrate
  without losing dates or counts. `n_window` was removed (no consumers). The `grep` path and its
  Windows fallback are gone — one reader on every platform.
- `cabina agents` prints a one-line "scanning usage history…" hint on stderr (TTY only, i18n)
  before a refresh; README documents `activity`, `hub` and the full command surface.

## [0.1.0]

### Added

- Agent roster with a contract (`name`/`description` critical, `model`/`tools` warning,
  config-driven severity) and real usage counts attributed per project.
- Skills roster.
- Harness view: wired vs. dead hooks.
- Docs view: read and save `MEMORY.md`/`CLAUDE.md`/`AGENTS.md` with hash-checked, backed-up,
  atomic writes.
- Health check (`cabina check`), 9 detectors, exit code 1 on critical findings; `--notify` for
  cron/launchd/systemd.
- Live provider integration (`cabina fleet`, Live tab) via `herdr`.
- Codex CLI support alongside Claude Code: agent/skill roster, `CLAUDE.md`/`AGENTS.md` drift
  detection, twin-agent comparison.
- MCP server (`cabina mcp`), read-only, so agents can consult the control plane before acting.
- `cabina export`/`cabina compare` for comparing environments across machines.
- `cabina check --repo` (CI mode): validates a single repository's agents against `.cabina.toml`,
  no user home or cache involved.
- Hooks for Claude Code: `cabina guard` (PreToolUse, blocks writes that break the contract) and
  `cabina brief` (SessionStart, a few lines of context).
- Opt-in git commit from the UI, scoped to a single path (`git add -A -- <path>`, never a bare
  `-A`).
