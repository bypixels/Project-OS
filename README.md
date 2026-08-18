# cabina

A control plane for a [Claude Code](https://claude.com/claude-code) environment: **agents, skills,
harness and docs — across all your projects — under one contract, with a health check that runs on
its own.** Zero dependencies. Local only.

> Cabina **measures, warns and blocks. It never repairs, deletes or edits anything on its own.**
> Every write goes through a confirmation and a guard. That is the whole design.

## Why

If you run Claude Code across many projects you end up with dozens of agents, hundreds of skills,
hooks that nobody wired, worktrees that nobody removed, and `MEMORY.md` files that stopped being
true a month ago. None of it fails loudly. Cabina makes it visible — and gives every asset a
contract, a real usage count, and a place in one window.

## Screenshots

<!-- TODO(danny): recorded GIF/PNG of the Agents tab with real (but non-sensitive) data,
     before tagging v0.1.0. Suggested: one GIF showing archive-with-references-check,
     one static shot of the health check output. -->

## What you get

| Command | What it does |
|---|---|
| `cabina` | Opens the UI in your browser (local server on 127.0.0.1) — six tabs: Agents, Live, Skills, Projects, Harness, Docs |
| `cabina check` | Health check. 9 detectors, exit code 1 on critical. Run it from cron / launchd / a systemd timer |
| `cabina agents` | Agent roster with contract state and real usage. `--invalid`, `--unused`, `--project`, `archive` |
| `cabina scan` | Rebuild the environment cache (fast; `--worktrees` and `--mcp` opt into the slow parts) |
| `cabina fleet` | Terminal TUI over the live provider |
| `cabina config` | Show effective config; `--example` prints a starter `config.toml` |

### The contract

Every agent must declare four things. Missing `name`/`description` is **critical** (Claude Code
cannot use it); missing `model`/`tools` is a **warning** (it works, but routing and permissions are
undeclared). All of this is configurable.

```yaml
---
name: tax-reviewer          # kebab-case, must equal the filename
description: when to invoke it
model: sonnet               # one of contract.models
tools: Read, Grep           # "*" is allowed — but say it
overrides: global           # only if it shadows a global agent of the same name
---
```

A `.md` in `agents/` **without frontmatter is a document, not an agent** — cabina says so and
does not suggest "fixing" it.

### Real usage, per project

Usage comes from Claude Code's own session history. Each invocation is attributed to the project
whose root contains the session `cwd`, so six agents named `code-reviewer` each get their own count.
Last-use dates are accumulated in `state_dir` so they survive history rotation (~30 days).

> This reads an **undocumented, internal** transcript format. If Claude Code changes it, usage
> degrades to "unknown" — nothing else breaks.

### The guards

Cabina writes in exactly four places, each behind a guard:

- **Create agent** — refused unless it meets the contract.
- **Archive agent / skill** — refused if any file references it (unless you tick "force"). Moves to
  `_archive/<date>/`, never deletes. A symlinked skill is moved as a link; the target is untouched.
- **Edit a document** — refused if the file changed on disk since you opened it (hash check), or if a
  live agent is working in that project. Previous version is backed up; write is atomic.
- **Open** — hands a path to your OS.

The server binds `127.0.0.1` only and every POST needs a per-session token.

### Claude Code and Codex, side by side

If Codex CLI is installed (`~/.codex`), cabina reads its environment too: agents (`*.toml`, validated
against a per-tool contract), skills, `AGENTS.md` per project, and session activity. Every row carries a
`claude` / `codex` chip; `cabina agents --tool codex`.

More useful than seeing both is seeing **where they drift apart**. The same content copied by hand into
two tools diverges silently, so cabina checks:

- **Twin agents** — same name in both tools, different instruction bodies.
- **`CLAUDE.md` ↔ `AGENTS.md`** — per project: `linked` (a symlink, ideal), `copy` (identical today,
  will drift), `bridge` (a short AGENTS.md that points at CLAUDE.md as canonical — deliberate),
  `diverged` (Codex and Claude read different rules here — with the diff).
- **Copied skills** — Codex skills copied from the shared skills dir that no longer match.

`cabina check` reports drift; the Harness tab shows it with the fix (`ln -sf CLAUDE.md AGENTS.md`).

> Codex transcripts record no agent or skill invocations (only shell and MCP calls), so per-agent
> usage for Codex is genuinely not measurable today. Cabina says so instead of showing zeros as fact.

## Install

```sh
pipx install cabina          # or: pip install cabina
cabina scan                  # first cache (~2 s)
cabina                       # opens http://127.0.0.1:8930
```

Requires Python 3.11+. No other dependencies. `git` is used for project status; `herdr` is optional
(powers the Live tab).

### Platforms

macOS, Linux and Windows. Claude Code and Codex keep their homes at `~/.claude` and `~/.codex` on
every OS; cabina's own files follow each platform's convention:

| | config | state (cache, usage, doc backups) |
|---|---|---|
| macOS / Linux | `~/.config/cabina/config.toml` (or `$XDG_CONFIG_HOME`) | `~/.local/share/cabina` (or `$XDG_DATA_HOME`) |
| Windows | `%APPDATA%\cabina\config.toml` | `%LOCALAPPDATA%\cabina` |

`grep` and `du` are used when present and replaced by pure-Python equivalents when not (Windows).
`cabina fleet` needs a curses terminal and tells you so where there is none; the web UI works everywhere.
Archiving a **symlinked** skill on Windows needs Developer Mode (symlink privilege) — cabina refuses
cleanly and moves nothing if it cannot recreate the link.

## Configure

`~/.config/cabina/config.toml` (or `$CABINA_CONFIG`). Everything is optional:

```toml
language = "en"                              # or "es"
roots = ["~/Documents", "~/Desktop"]         # where your projects live
[contract]
models = ["sonnet", "opus", "haiku"]
critical = ["name", "description"]
warn = ["model", "tools"]
[scan]
measure_worktrees = false                    # ~2 s per worktree when on
```

`cabina config --example` prints the full file.

### The doorman: hooks for Claude Code

Two hooks turn cabina from a Monday inspection into a guard at the door:

- **`cabina guard`** (PreToolUse on `Edit|Write|MultiEdit`) — validates the agent file that *would
  result* from the write (for an Edit it reconstructs the file, it does not just look at the new
  string). Contract not met → the write is blocked and Claude sees why. Warnings → allowed and
  surfaced. Anything that is not an agent file → ignored in ~60 ms. If the guard itself fails, it
  allows: a broken guard must never lock you out.
- **`cabina brief`** (SessionStart) — a few lines of context at session start: health, which projects
  have an agent working *right now*, and how stale this project's `MEMORY.md` is.

```sh
cabina hooks            # prints the settings.json entries
cabina hooks --write    # merges them into ~/.claude/settings.json (backup kept, idempotent)
```

### The contract travels with the repo — CI mode

`cabina check --repo .` validates **one repository on its own**: no user home, no cache, no history.
Drop a `.cabina.toml` in the repo root to tune its contract; run it on pull requests so an agent that
breaks the contract cannot be merged.

```sh
cabina init > .cabina.toml          # example contract for this repo
cabina init --ci > .github/workflows/cabina.yml
cabina check --repo .               # exit 1 on invalid agents ([check] strict = true: warnings too)
```

### Two machines, one picture

```sh
cabina export -o mac.json           # on the Mac
cabina export -o win.json           # on the Windows box
cabina compare mac.json win.json    # agents/skills/projects only on one side; agents whose state differs
```

### Committing what cabina changed (opt-in)

When cabina archives an agent or skill, or saves a document at your request, the dialog offers
*"and commit this change"*. It commits **only that path** (`git add -A -- <path>`, then
`git commit -- <path>`), never `-A`, never automatically, and refuses mid-merge/rebase. Other files
you or an agent had staged are left exactly as they were.

### Let the agents ask — MCP server (read-only)

`cabina mcp` is an MCP server over stdio. Registered in Claude Code and/or Codex, the agents
themselves can consult the control plane **before** acting:

| tool | question it answers |
|---|---|
| `cabina_working` | is any agent working in project X right now? (ask before touching `MEMORY.md`) |
| `cabina_agent` / `cabina_agents` | does this agent meet the contract? where does it exist? how much is it used? |
| `cabina_references` | who references Y? (ask before archiving or renaming) |
| `cabina_project` | branch, uncommitted changes, harness level, dead hooks, memory age |
| `cabina_health` / `cabina_drift` | the same findings `cabina check` reports |

Every tool is read-only; the server has no write path at all.

```sh
cabina mcp --install                     # prints both registrations:
claude mcp add cabina -s user -- cabina mcp
# ~/.codex/config.toml
[mcp_servers.cabina]
command = "cabina"
args = ["mcp"]
```

### Run the health check on a schedule

```sh
# cron (Linux/macOS): Mondays 09:00, desktop notification if anything to see
0 9 * * 1  cabina check --notify >> ~/.local/share/cabina/check.log 2>&1
```

## Development

```sh
git clone … && cd cabina
python -m unittest discover -s tests -v      # 126 tests, stdlib only
PYTHONPATH=src python -m cabina check
```

`tests/test_breaks.py` removes each guard in memory and asserts the canary tests go red — so a
guard cannot be silently deleted later.

## Non-goals

- It will not delete worktrees, repair agents, or auto-archive anything. It tells you the exact
  command and lets you run it.
- It is not an LLM observability tool (traces, cost per call). Look at Langfuse/LangSmith for that.
- It is not Backstage. It is the foreman's notebook, not the HR building.

## License

MIT
