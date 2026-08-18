"""Worktree cleanup helper. Writes NOTHING: `script()` only returns text for the user to review
and run themselves — cabina never shells out to `git worktree remove`/`prune` on its own. Reads
the cached scan data (via `scan.ensure`), same as every other consumer; it never re-walks disk."""
from . import scan

# Characters that cannot be quoted safely in a SINGLE line meant to paste unchanged into zsh,
# bash, PowerShell and cmd: "$" and "`" still expand inside POSIX double quotes (command
# substitution would RUN when the user pastes the line), "`" is also PowerShell's escape
# character, "%" and "!" are cmd's variable / delayed-expansion markers, and a literal `"` or
# `'` breaks the quoting itself. "&", "(", ")" and "^" are all legal characters in a Windows
# directory name but are cmd.exe metacharacters NOT reliably neutralized by double quotes there:
# "&" chains a second command, "(" / ")" group commands, and "^" is cmd's own escape character.
# Control characters (incl. newlines) are never safe either. A plain space is fine — it stays
# inside the double quotes on every one of these shells.
_UNSAFE_CHARS = frozenset('"\'$`%!&()^')


def _is_unsafe(path):
    """True when `path` cannot be embedded in a double-quoted shell argument that is safe
    across zsh/bash/PowerShell/cmd at once (see _UNSAFE_CHARS above)."""
    if not path:
        return True
    return any(ch in _UNSAFE_CHARS or ord(ch) < 32 for ch in path)


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

    # Bucket every row into exactly one group. Unsafe paths come first: an unsafe REPO path
    # takes down every one of its worktrees (no prune line either, per the invariant that
    # cabina never hands the user a command it did not fully intend), and an unsafe worktree
    # path is skipped regardless of its dirty/prunable state — we cannot safely reference it in
    # any command, so there is nothing else to check about it.
    unsafe, prunable_repos, removable, skipped_dirty, skipped_unknown = [], set(), [], [], []
    for r in rs:
        if _is_unsafe(r["repo"]) or _is_unsafe(r["path"]):
            unsafe.append(r)
        elif r["prunable"]:
            prunable_repos.add(r["repo"])
        elif r["dirty"] > 0:
            skipped_dirty.append(r)
        elif r["dirty"] < 0:
            skipped_unknown.append(r)
        else:
            removable.append(r)

    for repo in sorted(prunable_repos):
        lines.append(f'git -C "{repo}" worktree prune')
    if prunable_repos:
        lines.append("")

    for r in removable:
        lines.append(f'git -C "{r["repo"]}" worktree remove "{r["path"]}"')

    if removable and (skipped_dirty or skipped_unknown or unsafe):
        lines.append("")
    for r in skipped_dirty:
        lines.append(f'# skipped (uncommitted changes): {r["path"]}')
    for r in skipped_unknown:
        lines.append(f'# skipped (status unknown — run: cabina scan): {r["path"]}')
    for r in unsafe:
        lines.append(f'# skipped (path needs manual handling — unusual characters): {r["path"]}')

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
