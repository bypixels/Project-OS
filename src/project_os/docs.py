"""Operational documents per project: list, read, save.
The ONLY piece of project-os that edits project files. Guards:
  1. allowlist: .md inside a known root only; never creates files.
  2. optimistic concurrency: save requires the hash you read; changed on disk => refused.
  3. blocked while an agent is working in that project (caller passes the list, from the live provider).
  4. backup of the previous content (mirrored under the doc's own subdirectory, so two docs with
     the same basename in different subdirectories never collide), atomic write (tmp + replace),
     retention pruning. versions()/version_text() are read-only: no restore path here.
"""
import os, re, stat, time, hashlib, tempfile
from datetime import datetime

MAX_PER_DIR = 60

_BACKUP_RE = re.compile(r"^(?P<base>.+)\.(?P<stamp>\d{8}-\d{6})\.md$")
_STAMP_RE = re.compile(r"^\d{8}-\d{6}$")


def _h(txt):
    return hashlib.sha256(txt.encode("utf-8", "replace")).hexdigest()[:16]


def _confined(path, base):
    return path == base or path.startswith(base + os.sep)


def _is_backup_file(name):
    return bool(_BACKUP_RE.match(name))


class Docs:
    def __init__(self, roots, backups_dir, retention_days=30, max_per_dir=MAX_PER_DIR):
        self.roots = roots            # {project: abs_root}, includes 'global'
        self.backups = backups_dir
        self.retention = retention_days
        self.max_per_dir = max_per_dir

    def _resolve(self, project, rel):
        r = self.roots.get(project)
        if not r:
            return None, f"unknown project: {project}"
        if not rel.endswith(".md"):
            return None, "only .md files are editable"
        base = os.path.realpath(r)
        p = os.path.realpath(os.path.join(base, rel))
        if not (p == base or p.startswith(base + os.sep)):
            return None, "path outside the project"
        return p, None

    @staticmethod
    def _info(root, p):
        st = os.stat(p)
        return {"rel": os.path.relpath(p, root), "bytes": st.st_size,
                "mtime": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)),
                "days": int((time.time() - st.st_mtime) / 86400)}

    def list_project(self, project, root):
        out, seen = [], set()
        def add(p):
            if os.path.isfile(p) and p not in seen and p.endswith(".md"):
                seen.add(p); out.append({"project": project, **self._info(root, p)})
        if project == "global":
            for f in sorted(os.listdir(root)):
                add(os.path.join(root, f))
            rd = os.path.join(root, "rules")
            if os.path.isdir(rd):
                for f in sorted(os.listdir(rd)): add(os.path.join(rd, f))
            return out
        for f in ("CLAUDE.md", "PROGRESS.md", "PROGRESS-index.md", "README.md"):
            add(os.path.join(root, f))
        cd = os.path.join(root, ".claude")
        if os.path.isdir(cd):
            for f in sorted(os.listdir(cd)): add(os.path.join(cd, f))
        for sub in ("docs/adr", "docs/reference", "docs"):
            d = os.path.join(root, sub)
            if os.path.isdir(d):
                for f in sorted(os.listdir(d))[:self.max_per_dir]: add(os.path.join(d, f))
        for dp, dn, fn in os.walk(root):
            depth = dp[len(root):].count(os.sep)
            dn[:] = [x for x in dn if x not in {"node_modules", ".git", ".next", "dist", "build", "worktrees", ".claude", "docs"}] if depth < 3 else []
            if "CLAUDE.md" in fn and dp != root:
                add(os.path.join(dp, "CLAUDE.md"))
        return out

    def list_all(self):
        out = []
        for proj, root in self.roots.items():
            if os.path.isdir(root):
                out += self.list_project(proj, root)
        return out

    def read(self, project, rel):
        p, err = self._resolve(project, rel)
        if err:
            return {"ok": False, "message": err}
        if not os.path.isfile(p):
            return {"ok": False, "message": "does not exist"}
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "content": txt, "hash": _h(txt), "path": p, **self._info(self.roots[project], p)}

    def save(self, project, rel, content, hash_read, working=()):
        p, err = self._resolve(project, rel)
        if err:
            return {"ok": False, "message": err}
        if not os.path.isfile(p):
            return {"ok": False, "message": "does not exist: project-os edits documents, it never creates them"}
        if project in working:
            return {"ok": False, "message": f"an agent is working in {project} right now; editing could overwrite its work. Wait until it finishes."}
        try:
            current = open(p, encoding="utf-8", errors="replace").read()
            mode = stat.S_IMODE(os.stat(p).st_mode)
        except Exception as e:
            return {"ok": False, "message": str(e)}
        if _h(current) != hash_read:
            return {"ok": False, "conflict": True, "hash_current": _h(current),
                    "message": "the file changed on disk since you opened it. Reload and re-apply your change."}
        try:
            bd, base, berr = self._backup_loc(project, rel)
            if berr:
                return {"ok": False, "message": f"backup failed, not saving: {berr}"}
            os.makedirs(bd, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            with open(os.path.join(bd, f"{base}.{stamp}.md"), "w", encoding="utf-8") as f:
                f.write(current)
            self._prune(self._bp(project))
        except Exception as e:
            return {"ok": False, "message": f"backup failed, not saving: {e}"}
        tmp = None
        fd = None
        try:
            fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(p)}.", suffix=".tmp",
                                       dir=os.path.dirname(p))
            if hasattr(os, "fchmod"):
                os.fchmod(fd, mode)
            else:
                os.chmod(tmp, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fd = None
                f.write(content)
            os.replace(tmp, p)
            tmp = None
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp and os.path.lexists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return {"ok": True, "hash": _h(content), "message": f"saved · previous version kept in {bd}"}

    def _bp(self, project):
        return os.path.realpath(os.path.join(self.backups, project))

    def _backup_loc(self, project, rel):
        """Mirrored backup dir + basename for project's rel doc: <backups>/<project>/<dirname of
        rel>. Confines the result inside <backups>/<project>/ independently of _resolve's own
        confinement to the project root. Returns (bd, base, None) or (None, None, error)."""
        p, err = self._resolve(project, rel)
        if err:
            return None, None, err
        bp = self._bp(project)
        dname = os.path.dirname(rel)
        bd = os.path.realpath(os.path.join(bp, dname)) if dname else bp
        if not _confined(bd, bp):
            return None, None, "backup path outside project backups"
        return bd, os.path.basename(p)[:-3], None

    def versions(self, project, rel):
        """Read-only: newest-first backup history for project's rel doc. Never raises on a
        missing directory. `ambiguous` warns, not dates: before the mirrored layout, every
        same-basename document in a project shared one flat backup directory, so a root-level
        document's flat dir may hold versions that actually belonged to some subdirectory
        document of the same basename, and there is no way to tell which is which on disk. For a
        root-level document that flat directory IS its real backup directory forever (mirroring
        an empty dirname is a no-op), so `ambiguous` stays true even for versions saved after this
        fix, not just old ones -- flagging the whole list is the conservative choice, since
        silently presenting a possibly-contaminated history as clean would be exactly the kind of
        lie this project refuses to tell. A document in a subdirectory never reads the flat dir at
        all, so its list is never ambiguous."""
        bd, base, err = self._backup_loc(project, rel)
        if err or not bd or not os.path.isdir(bd):
            return []
        ambiguous = (bd == self._bp(project))
        out = []
        for f in os.listdir(bd):
            fp = os.path.join(bd, f)
            if not os.path.isfile(fp):
                continue
            m = _BACKUP_RE.match(f)
            if not m or m.group("base") != base:
                continue
            stamp = m.group("stamp")
            iso = datetime.strptime(stamp, "%Y%m%d-%H%M%S").astimezone().isoformat(timespec="seconds")
            out.append({"stamp": stamp, "iso": iso, "size": os.stat(fp).st_size, "ambiguous": ambiguous})
        out.sort(key=lambda x: x["stamp"], reverse=True)
        return out

    def version_text(self, project, rel, stamp):
        """Read-only: the stored text of one backed-up version. Re-validates the stamp (the only
        user-controlled part of the path) and re-confines rel + the resolved file, independently
        of versions()'s own listing. The stamp is what keeps the resolved file a direct child of
        bd (`^\\d{8}-\\d{6}$` allows no path separators at all); the final containment check is
        against the project's whole backups dir, not just bd, so it stays a genuinely separate
        layer from the stamp regex rather than a restatement of it."""
        if not _STAMP_RE.match(stamp):
            return {"ok": False, "message": "invalid version stamp"}
        bd, base, err = self._backup_loc(project, rel)
        if err:
            return {"ok": False, "message": err}
        bp = self._bp(project)
        fp = os.path.realpath(os.path.join(bd, f"{base}.{stamp}.md"))
        if not _confined(fp, bp) or not os.path.isfile(fp):
            return {"ok": False, "message": "version not found"}
        try:
            txt = open(fp, encoding="utf-8", errors="replace").read()
        except Exception as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "content": txt, "stamp": stamp}

    def _prune(self, bp):
        cutoff = time.time() - self.retention * 86400
        for dp, dn, fn in os.walk(bp):
            for f in fn:
                if not _is_backup_file(f):
                    continue
                fp = os.path.join(dp, f)
                try:
                    if os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                except Exception:
                    pass
