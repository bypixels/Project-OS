# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
