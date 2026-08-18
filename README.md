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

## Install

```sh
pipx install cabina          # or: pip install cabina
cabina scan                  # first cache (~2 s)
cabina                       # opens http://127.0.0.1:8930
```

Requires Python 3.11+. No other dependencies. `git` is used for project status; `herdr` is optional
(powers the Live tab).

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

### Run the health check on a schedule

```sh
# cron (Linux/macOS): Mondays 09:00, desktop notification if anything to see
0 9 * * 1  cabina check --notify >> ~/.local/share/cabina/check.log 2>&1
```

## Development

```sh
git clone … && cd cabina
python -m unittest discover -s tests -v      # 68 tests, stdlib only
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
