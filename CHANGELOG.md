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

### Fixed

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
