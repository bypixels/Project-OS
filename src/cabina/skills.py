"""Skill roster (global + projects). Writes only in archive_path (moves ONE dir or symlink)."""
import os, shutil
from datetime import date
from .contract import parse_frontmatter


def scan_dir(d, project):
    """States: ok | no-frontmatter | no-skill-md | broken-link"""
    out = []
    if not os.path.isdir(d):
        return out
    for e in sorted(os.listdir(d)):
        if e.startswith("."):
            continue
        p = os.path.join(d, e)
        link = os.path.islink(p)
        target = os.path.realpath(p) if link else None
        base = {"name": e, "project": project, "path": p, "symlink": link, "target": target, "desc": "", "lines": 0}
        if link and not os.path.exists(p):
            out.append({**base, "target": os.readlink(p), "state": "broken-link"}); continue
        if not os.path.isdir(p):
            continue
        sk = os.path.join(p, "SKILL.md")
        if not os.path.isfile(sk):
            out.append({**base, "state": "no-skill-md"}); continue
        try:
            txt = open(sk, encoding="utf-8", errors="replace").read()
        except Exception:
            txt = ""
        fm, has = parse_frontmatter(txt)
        out.append({**base, "state": "ok" if has else "no-frontmatter",
                    "desc": fm.get("description", "")[:300], "lines": txt.count("\n")})
    return out


def load(cfg, data):
    rows = scan_dir(os.path.join(cfg["claude_home"], "skills"), "global")
    for p in data.get("projects", []):
        rows += scan_dir(os.path.join(p["path"], ".claude", "skills"), p["name"])
    return rows


def archive_path(path, project, archive_base):
    """Move a skill (dir or symlink) to <archive_base>/<today>/skills/<project>/.
    A symlink is moved AS a link: the real target is never touched."""
    if not os.path.lexists(path):
        return False, "does not exist"
    dest_dir = os.path.join(archive_base, date.today().isoformat(), "skills", project)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    if os.path.lexists(dest):
        return False, f"something already at {dest}"
    if os.path.islink(path):
        target = os.readlink(path)
        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(os.path.dirname(path), target))
        os.symlink(target, dest)
        os.unlink(path)
    else:
        shutil.move(path, dest)
    return True, f"archived to {dest}"
