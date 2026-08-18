"""Configuration: ~/.config/cabina/config.toml (or $CABINA_CONFIG). Everything has a default."""
import os, sys, tomllib, copy

HOME = os.path.expanduser("~")

DEFAULTS = {
    "language": "en",                                   # "en" | "es"
    "claude_home": "~/.claude",                         # Claude Code's own directory
    "roots": ["~/Documents", "~/Desktop"],              # where projects live (any dir with .claude/)
    "state_dir": "~/.local/share/cabina",               # cache, usage registry, doc backups
    "server": {"host": "127.0.0.1", "port": 8930},
    "contract": {
        "required": ["name", "description", "model", "tools"],
        "critical": ["name", "description"],            # missing -> critical
        "warn": ["model", "tools"],                     # missing -> warning
        "models": ["sonnet", "opus", "haiku"],
        "known_fields": ["overrides", "maxTurns", "color", "version"],
    },
    "scan": {
        "measure_worktrees": False,                     # `du` over worktrees: ~2 s each; enable with `cabina scan --worktrees`
        "check_mcp": False,                             # `claude mcp list` (~10 s, needs the CLI)
        "skip_dirs": ["node_modules", ".git", ".next", "dist", "build", ".venv", "__pycache__", "worktrees", "_archive"],
    },
    "live": {"provider": "auto"},                       # "auto" | "herdr" | "none"
    "docs": {"backup_retention_days": 30, "max_per_dir": 60},
    "check": {"worktree_stale_days": 14, "memory_stale_days": 30},
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def config_path():
    return os.environ.get("CABINA_CONFIG") or os.path.join(HOME, ".config", "cabina", "config.toml")


def load(path=None):
    """Load config merged over defaults. Missing file => defaults."""
    p = path or config_path()
    user = {}
    if os.path.isfile(p):
        with open(p, "rb") as f:
            user = tomllib.load(f)
    cfg = _merge(DEFAULTS, user)
    cfg["claude_home"] = os.path.expanduser(cfg["claude_home"])
    cfg["state_dir"] = os.path.expanduser(cfg["state_dir"])
    cfg["roots"] = [os.path.expanduser(r) for r in cfg["roots"]]
    return cfg


def example_toml():
    return '''# cabina configuration — every key is optional; these are the defaults.
language = "en"                 # "en" | "es"
claude_home = "~/.claude"
roots = ["~/Documents", "~/Desktop"]
state_dir = "~/.local/share/cabina"

[server]
host = "127.0.0.1"
port = 8930

[contract]
required = ["name", "description", "model", "tools"]
critical = ["name", "description"]
warn = ["model", "tools"]
models = ["sonnet", "opus", "haiku"]

[scan]
measure_worktrees = false     # slow: ~2 s per worktree
check_mcp = false

[live]
provider = "auto"               # "auto" | "herdr" | "none"

[docs]
backup_retention_days = 30

[check]
worktree_stale_days = 14
memory_stale_days = 30
'''
