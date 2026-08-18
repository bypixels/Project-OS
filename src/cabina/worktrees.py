"""Worktree cleanup helper. Writes NOTHING: `script()` only returns text for the user to review
and run themselves — cabina never shells out to `git worktree remove`/`prune` on its own. Reads
the cached scan data (via `scan.ensure`), same as every other consumer; it never re-walks disk."""
from . import scan


def _rows_from_data(data, project=None):
    out = []
    for p in data.get("projects", []):
        if project and p.get("name") != project:
            continue
        git = p.get("git") or {}
        for w in git.get("worktrees", []):
            dirty = w.get("dirty")
            if dirty is None or dirty < 0:
                dirty = -1     # unknown status: never treated as clean
            out.append({
                "project": p.get("name"),
                "repo": p.get("path"),
                "path": w.get("path"),
                "name": w.get("name"),
                "mb": w.get("mb"),
                "mtime": w.get("mtime"),
                "dirty": dirty,
                "branch": w.get("branch"),
                "prunable": bool(w.get("prunable")),
            })
    out.sort(key=lambda r: (r["repo"] or "", r["path"] or ""))
    return out


def rows(cfg, data=None, project=None):
    """Flat list of `{project, repo, path, name, mb, mtime, dirty, branch, prunable}`,
    one per worktree, across all projects (or just `project` when given)."""
    data = data if data is not None else scan.ensure(cfg)
    return _rows_from_data(data, project)


def script(cfg, data=None, project=None):
    """A flat, loop-free, if-free plain-text script: one `git worktree prune` per repo that has
    a prunable worktree, then one `git worktree remove` per worktree that is both not prunable
    and clean (dirty == 0). Never `--force`; branches are never touched. Everything else is
    listed as a `#` comment explaining why it was skipped. Pastes identically into zsh, bash,
    PowerShell and cmd."""
    rs = rows(cfg, data, project)
    if not rs:
        return "# cabina worktrees: nothing to clean up.\n"
    lines = [
        "# cabina worktree cleanup — review before running; cabina never executes these itself.",
        "# Branches are kept; only worktree directories are affected.",
        "",
    ]
    prunable_repos = sorted({r["repo"] for r in rs if r["prunable"]})
    for repo in prunable_repos:
        lines.append(f'git -C "{repo}" worktree prune')
    if prunable_repos:
        lines.append("")

    removable = [r for r in rs if not r["prunable"] and r["dirty"] == 0]
    for r in removable:
        lines.append(f'git -C "{r["repo"]}" worktree remove "{r["path"]}"')

    skipped_dirty = [r for r in rs if not r["prunable"] and r["dirty"] > 0]
    skipped_unknown = [r for r in rs if not r["prunable"] and r["dirty"] < 0]
    if removable and (skipped_dirty or skipped_unknown):
        lines.append("")
    for r in skipped_dirty:
        lines.append(f'# skipped (uncommitted changes): {r["path"]}')
    for r in skipped_unknown:
        lines.append(f'# skipped (status unknown — run: cabina scan): {r["path"]}')

    return "\n".join(lines) + "\n"


def summary(cfg, data=None, project=None):
    """Counts for the UI/CLI: `{total, clean, dirty, unknown, prunable, mb, mb_measured}`.
    `mb` sums only the known sizes; `mb_measured` is False when any row's size is unknown."""
    rs = rows(cfg, data, project)
    prunable = sum(1 for r in rs if r["prunable"])
    dirty = sum(1 for r in rs if not r["prunable"] and r["dirty"] > 0)
    unknown = sum(1 for r in rs if not r["prunable"] and r["dirty"] < 0)
    clean = sum(1 for r in rs if not r["prunable"] and r["dirty"] == 0)
    known_mb = [r["mb"] for r in rs if r["mb"] is not None]
    return {
        "total": len(rs), "clean": clean, "dirty": dirty, "unknown": unknown,
        "prunable": prunable, "mb": sum(known_mb), "mb_measured": len(known_mb) == len(rs),
    }
