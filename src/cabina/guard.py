"""Hooks for Claude Code (and Codex): the doorman.

  cabina guard   PreToolUse on Edit|Write — validates the resulting agent file against the
                 contract. Invalid => exit 2 + reason on stderr (Claude Code blocks and shows it).
                 Warnings => allowed, surfaced on stdout. Anything else => exit 0, silent.
                 A broken guard must NEVER lock the user out: any failure of our own is exit 0.
  cabina brief   SessionStart — a few lines of context: health, who is working, this project's memory age.
  cabina hooks   print (or --write) the settings.json entries.
"""
import os, sys, json, time, shutil, shlex
from datetime import datetime
from .contract import Contract
from . import scan, live as LIVE, check as CHECK

AGENT_EXT = (".md", ".toml")


def _ago(ts):
    """Local-aware ISO timestamp -> compact 'x minutes/hours/days ago' string. Best-effort.
    sessions.py already stores started/ended converted to local time with an offset (R7), so
    this parses it directly — no 'Z' stripping needed here."""
    if not ts:
        return "?"
    try:
        t0 = datetime.fromisoformat(ts)
        now = datetime.now(t0.tzinfo) if t0.tzinfo else datetime.now()
        secs = (now - t0).total_seconds()
    except Exception:
        return "?"
    mins = int(secs // 60)
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    return f"{hours}h" if hours < 24 else f"{hours // 24}d"


def _is_agent_path(path, cfg):
    p = os.path.realpath(path)
    return os.path.basename(os.path.dirname(p)) == "agents" and p.endswith(AGENT_EXT) and \
        (os.path.basename(os.path.dirname(os.path.dirname(p))) in (".claude", os.path.basename(cfg["claude_home"])) or
         p.startswith(os.path.realpath(cfg.get("codex_home") or "\0")))


def _tool_for(path, cfg):
    cx = os.path.realpath(cfg.get("codex_home") or "\0")
    return "codex" if os.path.realpath(path).startswith(cx + os.sep) else "claude"


def _resulting_text(tool_name, ti, path):
    """The file content AFTER the tool runs. Write: content. Edit: apply old->new to current file."""
    if tool_name == "Write":
        return ti.get("content")
    if tool_name in ("Edit", "MultiEdit"):
        try:
            cur = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            return None
        edits = ti.get("edits") or [ti]
        for e in edits:
            old, new = e.get("old_string", ""), e.get("new_string", "")
            if not old or old not in cur:
                return None                      # Claude Code will fail that edit itself
            cur = cur.replace(old, new) if e.get("replace_all") else cur.replace(old, new, 1)
        return cur
    return None


def run(cfg, stdin_text, out=sys.stdout, err=sys.stderr):
    """Returns the exit code. 0 allow · 2 block."""
    try:
        d = json.loads(stdin_text or "{}")
        tool_name = d.get("tool_name", ""); ti = d.get("tool_input") or {}
        path = ti.get("file_path") or ""
        if tool_name not in ("Write", "Edit", "MultiEdit") or not path or not _is_agent_path(path, cfg):
            return 0
        text = _resulting_text(tool_name, ti, path)
        if text is None:
            return 0
        tool = _tool_for(path, cfg)
        name, ext = os.path.splitext(os.path.basename(path))
        gdir = os.path.join(cfg["claude_home"], "agents")
        shadows = tool == "claude" and os.path.dirname(os.path.realpath(path)) != os.path.realpath(gdir) \
            and os.path.exists(os.path.join(gdir, name + ".md"))
        r = Contract(cfg, tool=tool).validate_text(text, name, shadows_global=shadows, fmt="toml" if ext == ".toml" else "md")
        if r.category in ("invalid", "error"):
            err.write("BLOCKED by cabina: this agent would not meet the contract.\n")
            for c in r.critical: err.write(f"  - {c}\n")
            for w in r.warnings: err.write(f"  - (warning) {w}\n")
            err.write("Fix the frontmatter and write again. Contract: name (kebab-case = filename), description, model, tools.\n")
            return 2
        if r.warnings:
            out.write("cabina: written, with contract warnings — " + "; ".join(r.warnings) + "\n")
        return 0
    except Exception:
        return 0     # never lock the user out because of us


def brief(cfg, cwd=None):
    """SessionStart context, a few lines."""
    lines = []
    try:
        F = CHECK.run(cfg, quick=True)
        nc = sum(1 for f in F if f["sev"] == "crit"); nw = sum(1 for f in F if f["sev"] == "warn")
        lines.append(f"[cabina] health: {nc} critical, {nw} warnings" + (" — run `cabina check`" if nc or nw else " — all clear"))
        for f in [x for x in F if x["sev"] == "crit"][:2]:
            lines.append(f"[cabina]   ! {f['title']}")
    except Exception:
        lines.append("[cabina] health: unavailable")
    try:
        prov = LIVE.get(cfg); roots = scan.project_roots(cfg)
        w = LIVE.working_projects(prov, roots)
        if w:
            lines.append(f"[cabina] agents working right now in: {', '.join(w)} — coordinate before touching shared files there")
    except Exception:
        pass
    try:
        cwd = os.path.realpath(cwd or os.getcwd()); roots = scan.project_roots(cfg)
        here = next((n for n, r in sorted(roots.items(), key=lambda x: -len(x[1])) if n != "global" and (cwd == os.path.realpath(r) or cwd.startswith(os.path.realpath(r) + os.sep))), None)
        if here:
            mem = os.path.join(roots[here], ".claude", "MEMORY.md")
            if os.path.isfile(mem):
                days = int((time.time() - os.path.getmtime(mem)) / 86400)
                lines.append(f"[cabina] {here}: MEMORY.md last touched {days} day(s) ago" + (" — likely stale" if days > cfg['check']['memory_stale_days'] else ""))
            else:
                lines.append(f"[cabina] {here}: no MEMORY.md")
            from . import sessions
            from .i18n import t as _t
            sess = [s for s in sessions.load(cfg) if s.get("project") == here]
            if sess:
                last = sess[0]
                lines.append("[cabina] " + _t(cfg["language"], "brief.last_session",
                                               title=last.get("title") or "(untitled)", ago=_ago(last.get("ended") or last.get("started"))))
    except Exception:
        pass
    return "\n".join(lines) + "\n"


def read_stdin_briefly(timeout=1.0):
    """Hook payloads arrive on stdin and the pipe is closed; a human caller may leave stdin open.
    Never hang: wait at most `timeout` seconds for data (POSIX); on Windows read only if not a tty."""
    try:
        if sys.stdin.isatty():
            return ""
        if os.name != "nt":
            import select
            r, _, _ = select.select([sys.stdin], [], [], timeout)
            if not r:
                return ""
        return sys.stdin.read()
    except Exception:
        return ""


def hooks_snippet(cmd="cabina"):
    return {"hooks": {
        "PreToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": f"{cmd} guard", "timeout": 10}]}],
        "SessionStart": [{"matcher": "startup|resume", "hooks": [{"type": "command", "command": f"{cmd} brief", "timeout": 15}]}],
    }}


def _cmd_resolves(cmd):
    """First whitespace token of `cmd` resolves on PATH (shutil.which), or is itself an
    existing, executable absolute path. Returns (bool, path|None). Never raises — a
    malformed cmd string just fails to resolve."""
    try:
        tok = shlex.split(cmd)[0] if cmd else ""
    except Exception:
        return False, None
    if not tok:
        return False, None
    if os.path.isabs(tok) and os.path.isfile(tok) and os.access(tok, os.X_OK):
        return True, tok
    found = shutil.which(tok)
    return (found is not None), found


def hooks_status(settings_path, cmd="cabina"):
    """Read-only: what's on disk at settings_path, and whether our two hooks are already
    wired there. Never writes."""
    exists = os.path.isfile(settings_path)
    valid_json, error, d = True, None, {}
    if exists:
        try:
            d = json.load(open(settings_path))
        except Exception as e:
            valid_json, error = False, str(e)
    hooks = d.get("hooks") if isinstance(d, dict) else None
    hooks = hooks if isinstance(hooks, dict) else {}

    def _has(event, needle):
        for grp in hooks.get(event) or []:
            for h in grp.get("hooks") or []:
                if needle in (h.get("command") or ""):
                    return True
        return False

    resolves, path = _cmd_resolves(cmd)
    return {
        "settings_path": settings_path, "exists": exists, "valid_json": valid_json, "error": error,
        "guard_installed": _has("PreToolUse", f"{cmd} guard"),
        "brief_installed": _has("SessionStart", f"{cmd} brief"),
        "cmd_resolves": resolves, "cmd_path": path,
        "snippet": hooks_snippet(cmd),
    }


def _unique_backup_path(path):
    """`path` already carries a microsecond-resolution timestamp suffix, but a frozen or
    coarse clock can still repeat it (two writes in the same instant). Never overwrite an
    existing backup: append -1, -2, ... until a free name is found."""
    if not os.path.exists(path):
        return path
    i = 1
    while True:
        cand = f"{path}-{i}"
        if not os.path.exists(cand):
            return cand
        i += 1


def hooks_write(settings_path, cmd="cabina", force=False):
    """Merge our two hooks into an existing settings.json (backup first). Idempotent.
    Guard: refuses to wire a `cmd` that does not resolve on PATH (the exact "dead hook"
    problem cabina flags elsewhere) unless the caller passes force=True."""
    resolves, _ = _cmd_resolves(cmd)
    if not resolves and not force:
        return False, (f"{cmd} is not on PATH: installing it would wire a dead hook (the exact thing "
                        "cabina flags). Install cabina where Claude Code can find it, or pass the full path.")
    try:
        d = json.load(open(settings_path)) if os.path.isfile(settings_path) else {}
    except Exception as e:
        return False, f"cannot parse {settings_path}: {e}"
    if os.path.isfile(settings_path):
        shutil.copy2(settings_path, _unique_backup_path(settings_path + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")))
    hooks = d.setdefault("hooks", {})
    for ev, groups in hooks_snippet(cmd)["hooks"].items():
        lst = hooks.setdefault(ev, [])
        for g in groups:
            want = g["hooks"][0]["command"]
            if any(want in (h.get("command") or "") for grp in lst for h in grp.get("hooks", [])):
                continue
            lst.append(g)
    tmp = settings_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(tmp, settings_path)
    return True, f"hooks written to {settings_path} (backup kept next to it)"
