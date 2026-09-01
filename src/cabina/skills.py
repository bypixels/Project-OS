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


def _canonical_origin_allowed(path, allowed_root):
    """Validate the link/directory location without resolving a skill symlink target."""
    if not allowed_root:
        return True
    try:
        root = os.path.realpath(allowed_root)
        parent = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    except OSError:
        return False
    return parent == root


MAX_BODY_BYTES = 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_LIST_FILES = 200
MAX_LIST_DEPTH = 6
_BINARY_SNIFF = 8192


def _confined(path, base):
    """True if `path` (already realpath'd) is `base` itself or strictly inside it."""
    return path == base or path.startswith(base + os.sep)


def _list_files(root, max_depth=MAX_LIST_DEPTH, max_files=MAX_LIST_FILES):
    """Recursive listing of a skill's own directory: {"path","size","mtime"} per file,
    sorted by path. Skips dotfiles; a symlink (file or dir) is only followed when its
    realpath stays inside `root` -- one pointing outside is skipped entirely."""
    root_real = os.path.realpath(root)
    out = []

    def add(p, rel_root):
        try:
            st = os.stat(p)
        except OSError:
            return
        out.append({"path": os.path.relpath(p, rel_root), "size": st.st_size, "mtime": st.st_mtime})

    def walk(d, depth):
        if depth > max_depth or len(out) >= max_files:
            return
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            return
        for e in entries:
            if len(out) >= max_files:
                return
            if e.startswith("."):
                continue
            p = os.path.join(d, e)
            if os.path.islink(p):
                try:
                    real = os.path.realpath(p)
                except OSError:
                    continue
                if not _confined(real, root_real):
                    continue
            if os.path.isdir(p):
                walk(p, depth + 1)
            elif os.path.isfile(p):
                add(p, root)

    walk(root, 0)
    out.sort(key=lambda f: f["path"])
    return out


def read_body(path, max_bytes=MAX_BODY_BYTES, max_files=MAX_LIST_FILES, max_depth=MAX_LIST_DEPTH):
    """Read-only: <path>/SKILL.md (capped at `max_bytes`, decoded as UTF-8 with replacement)
    plus a recursive listing of the skill's own directory. {"ok": False, "message"} on anything
    unreadable; never raises."""
    if not os.path.isdir(path):
        return {"ok": False, "message": "skill directory does not exist"}
    sk = os.path.join(path, "SKILL.md")
    if not os.path.isfile(sk):
        return {"ok": False, "message": "no SKILL.md"}
    try:
        with open(sk, "rb") as f:
            raw = f.read(max_bytes + 1)
    except OSError as e:
        return {"ok": False, "message": str(e)}
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    return {"ok": True, "content": raw.decode("utf-8", "replace"), "truncated": truncated,
            "bytes": len(raw), "files": _list_files(path, max_depth, max_files)}


def read_file(path, rel):
    """Read-only preview of ONE file inside a skill's own directory. Confinement: `rel` must
    resolve (symlinks included) strictly inside realpath(path); "../", an absolute path, or a
    symlink escaping the skill directory are all refused. Capped at MAX_FILE_BYTES (rejected,
    never truncated). Binary detection: a null byte in the first 8 KB.
    Threat model: this confinement stops a malformed request (a bad `rel`) from reading outside
    the skill directory. It is not a defense against an attacker who already has concurrent
    local write access to the disk (TOCTOU, hardlinks) -- anyone who can write to the filesystem
    can already read it without cabina."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or "\x00" in rel:
        return {"ok": False, "message": "invalid path"}
    try:
        base = os.path.realpath(path)
        p = os.path.realpath(os.path.join(base, rel))
    except (OSError, ValueError) as e:
        return {"ok": False, "message": str(e)}
    if p == base or not _confined(p, base):
        return {"ok": False, "message": "path outside the skill"}
    if not os.path.isfile(p):
        return {"ok": False, "message": "not a file"}
    try:
        size = os.path.getsize(p)
    except OSError as e:
        return {"ok": False, "message": str(e)}
    if size > MAX_FILE_BYTES:
        return {"ok": False, "message": "file larger than 1 MB"}
    try:
        with open(p, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {"ok": False, "message": str(e)}
    if b"\x00" in raw[:_BINARY_SNIFF]:
        return {"ok": True, "binary": True, "content": None, "size": size}
    return {"ok": True, "binary": False, "content": raw.decode("utf-8", "replace"), "size": size}


def archive_path(path, project, archive_base, allowed_root=None):
    """Move a skill (dir or symlink) to <archive_base>/<today>/skills/<project>/.
    A symlink is moved AS a link: the real target is never touched."""
    if not os.path.lexists(path):
        return False, "does not exist"
    if not _canonical_origin_allowed(path, allowed_root):
        return False, "skill path outside allowed canonical root"
    dest_dir = os.path.join(archive_base, date.today().isoformat(), "skills", project)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    if os.path.lexists(dest):
        return False, f"something already at {dest}"
    if os.path.islink(path):
        target = os.readlink(path)
        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(os.path.dirname(path), target))
        try:
            os.symlink(target, dest)          # Windows: needs Developer Mode or admin
        except OSError as e:
            return False, f"cannot create the archived link ({e}); nothing was moved"
        os.unlink(path)
    else:
        shutil.move(path, dest)
    return True, f"archived to {dest}"
