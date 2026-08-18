"""Operational documents per project: list, read, save.
The ONLY piece of cabina that edits project files. Guards:
  1. allowlist: .md inside a known root only; never creates files.
  2. optimistic concurrency: save requires the hash you read; changed on disk => refused.
  3. blocked while an agent is working in that project (caller passes the list, from the live provider).
  4. backup of the previous content, atomic write (tmp + replace), retention pruning.
"""
import os, time, hashlib

MAX_PER_DIR = 60


def _h(txt):
    return hashlib.sha256(txt.encode("utf-8", "replace")).hexdigest()[:16]


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
            return {"ok": False, "message": "does not exist: cabina edits documents, it never creates them"}
        if project in working:
            return {"ok": False, "message": f"an agent is working in {project} right now; editing could overwrite its work. Wait until it finishes."}
        try:
            current = open(p, encoding="utf-8", errors="replace").read()
        except Exception as e:
            return {"ok": False, "message": str(e)}
        if _h(current) != hash_read:
            return {"ok": False, "conflict": True, "hash_current": _h(current),
                    "message": "the file changed on disk since you opened it. Reload and re-apply your change."}
        try:
            bd = os.path.join(self.backups, project)
            os.makedirs(bd, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            with open(os.path.join(bd, f"{os.path.basename(p)[:-3]}.{stamp}.md"), "w", encoding="utf-8") as f:
                f.write(current)
            self._prune(bd)
        except Exception as e:
            return {"ok": False, "message": f"backup failed, not saving: {e}"}
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, p)
        return {"ok": True, "hash": _h(content), "message": f"saved · previous version kept in {bd}"}

    def _prune(self, bd):
        cutoff = time.time() - self.retention * 86400
        for f in os.listdir(bd):
            fp = os.path.join(bd, f)
            try:
                if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
            except Exception:
                pass
