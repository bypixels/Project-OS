"""Per-project status: cached scan + live git (cheap). Read-only."""
import os, subprocess, time

DOCS = ("CLAUDE.md", ".claude/HARNESS.md", ".claude/MEMORY.md", "PROGRESS.md")


def _git(path, *a):
    try:
        r = subprocess.run(["git", "-C", path, *a], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def load(data):
    out = []
    for p in data.get("projects", []):
        root = p["path"]; g = p.get("git") or {}; wt = g.get("worktrees", [])
        branch = _git(root, "branch", "--show-current"); dirty = _git(root, "status", "--porcelain")
        hooks = os.path.join(root, ".claude", "hooks")
        wf = os.path.join(root, ".claude", "workflows")
        mem = os.path.join(root, ".claude", "MEMORY.md")
        out.append({
            "name": p["name"], "path": root, "exists": os.path.isdir(root),
            "branch": branch if branch is not None else g.get("branch", ""),
            "dirty": len(dirty.splitlines()) if dirty is not None else g.get("dirty", 0),
            "git": branch is not None,
            "agents": len(p.get("agents", [])), "skills": len(p.get("skills", [])),
            "commands": len(p.get("commands", [])), "rules": len(p.get("rules", [])),
            "hooks": len([f for f in os.listdir(hooks) if not f.startswith(".")]) if os.path.isdir(hooks) else 0,
            "workflows": len([f for f in os.listdir(wf) if f.endswith(".js")]) if os.path.isdir(wf) else 0,
            "worktrees": len(wt), "worktrees_mb": g.get("worktree_mb", 0),
            "worktrees_detail": [{"name": w["name"], "mb": w["mb"], "mtime": w["mtime"], "dirty": w["dirty"]} for w in wt],
            "docs": {os.path.basename(x): os.path.isfile(os.path.join(root, x)) for x in DOCS},
            "memory_days": int((time.time() - os.path.getmtime(mem)) / 86400) if os.path.isfile(mem) else None,
            "last_commit": g.get("last", ""),
        })
    out.sort(key=lambda x: -(x["agents"] + x["skills"]))
    return out
