"""Hooks for Claude Code (and Codex): the doorman.

  cabina guard   PreToolUse on Edit|Write — validates the resulting agent file against the
                 contract. Invalid => exit 2 + reason on stderr (Claude Code blocks and shows it).
                 Warnings => allowed, surfaced on stdout. Anything else => exit 0, silent.
                 A broken guard must NEVER lock the user out: any failure of our own is exit 0.
  cabina brief   SessionStart — a few lines of context: health, who is working, this project's memory age.
  cabina hooks   print (or --write) the settings.json entries.
"""
import os, sys, json, time, shutil
from datetime import datetime
from .contract import Contract
from . import scan, live as LIVE, check as CHECK

AGENT_EXT = (".md", ".toml")


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
        # collapse nested projects into their parent (Webs/actanova/apps/api -> actanova)
        rr = {n: os.path.realpath(r) for n, r in roots.items() if n != "global"}
        w = sorted({next((o for o, orr in rr.items() if o != n and rr[n].startswith(orr + os.sep)), n) for n in w})
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


def hooks_write(settings_path, cmd="cabina"):
    """Merge our two hooks into an existing settings.json (backup first). Idempotent."""
    try:
        d = json.load(open(settings_path)) if os.path.isfile(settings_path) else {}
    except Exception as e:
        return False, f"cannot parse {settings_path}: {e}"
    if os.path.isfile(settings_path):
        shutil.copy2(settings_path, settings_path + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
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
