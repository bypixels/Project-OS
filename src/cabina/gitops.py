"""Opt-in commit of ONE path that cabina just changed on the user's request.
Never `git add -A`; never automatic; refuses if the repo is mid-merge/rebase; commits only
that pathspec even if other files are staged."""
import os, subprocess


def _git(root, *a, env=None):
    r = subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, timeout=30, env=env)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def repo_root(path):
    path = os.path.realpath(path)          # symlinked parents (macOS /var -> /private/var) must match git's toplevel
    d = path if os.path.isdir(path) else os.path.dirname(path)
    code, out, _ = _git(d, "rev-parse", "--show-toplevel") if os.path.isdir(d) else (1, "", "")
    return out if code == 0 else None


def commit_path(path, message, author=None):
    """Stage and commit exactly `path` (file or dir; a deleted path records the deletion)."""
    root = repo_root(path)
    if not root:
        return False, "not in a git repository"
    gd = _git(root, "rev-parse", "--git-dir")[1]
    gd = gd if os.path.isabs(gd) else os.path.join(root, gd)
    for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"):
        if os.path.exists(os.path.join(gd, marker)):
            return False, f"repository is mid-{marker.split('_')[0].split('-')[0].lower()}: not committing"
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    if rel.startswith(".."):
        return False, "path is outside the repository"
    code, _, err = _git(root, "add", "-A", "--", rel)          # -A scoped to THIS pathspec only: adds, modifies, deletes
    if code != 0:
        return False, f"git add failed: {err}"
    code, out, _ = _git(root, "diff", "--cached", "--name-only", "--", rel)
    if not out.strip():
        return False, "nothing to commit for that path"
    args = ["commit", "-q", "-m", message, "--", rel]
    if author:
        args = ["-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}"] + args
    code, _, err = _git(root, *args)
    if code != 0:
        return False, f"git commit failed: {err}"
    sha = _git(root, "rev-parse", "--short", "HEAD")[1]
    return True, f"committed {rel} as {sha}"
