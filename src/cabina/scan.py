"""Environment scan: every .claude/ under the configured roots, plus the global one.
Writes ONE file: <state_dir>/scan.json. Everything else is read-only."""
import json, os, re, subprocess, hashlib, shutil
from datetime import datetime, timezone
from . import host
from .contract import parse_frontmatter

HOME = os.path.expanduser("~")


def _read(p, limit=200_000):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except Exception:
        return ""


def find_claude_dirs(roots, skip):
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in skip]
            if os.path.basename(dp) == ".claude":
                found.append(dp)
                dn[:] = []
    return found


def _assets(cdir, kind):
    if kind == "agents_toml":                        # Codex: <home>/agents/*.toml
        d = cdir; out = []
        if not os.path.isdir(d):
            return out
        for e in sorted(os.listdir(d)):
            if e.endswith(".toml"):
                try:
                    import tomllib
                    t = tomllib.loads(_read(os.path.join(d, e)))
                except Exception:
                    t = {}
                out.append({"name": t.get("name", e[:-5]), "file": e, "desc": str(t.get("description", ""))[:300],
                            "model": str(t.get("model", "")), "lines": _read(os.path.join(d, e)).count("\n"), "frontmatter": bool(t)})
        return out
    d = os.path.join(cdir, kind)
    out = []
    if not os.path.isdir(d):
        return out
    for e in sorted(os.listdir(d)):
        p = os.path.join(d, e)
        if kind == "skills":
            sk = os.path.join(p, "SKILL.md")
            if os.path.isdir(p) and os.path.isfile(sk):
                fm, _ = parse_frontmatter(_read(sk))
                out.append({"name": fm.get("name", e), "file": e, "desc": fm.get("description", "")[:300],
                            "lines": _read(sk).count("\n"), "symlink": os.path.islink(p)})
            elif os.path.isdir(p):
                out.append({"name": e, "file": e, "desc": "", "lines": 0, "symlink": os.path.islink(p), "invalid": True})
        elif e.endswith(".md") and os.path.isfile(p):
            txt = _read(p)
            fm, has_fm = parse_frontmatter(txt)
            out.append({"name": fm.get("name", e[:-3]), "file": e, "desc": fm.get("description", "")[:300],
                        "model": fm.get("model", ""), "tools": fm.get("tools", ""), "lines": txt.count("\n"),
                        "frontmatter": has_fm})
    return out


def _dir_mb(path):
    """Directory size in MB: `du` where available, os.walk elsewhere (Windows)."""
    if shutil.which("du"):
        try:
            r = subprocess.run(["du", "-sk", path], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                return round(int(r.stdout.split()[0]) / 1024)
        except Exception:
            pass
    total = 0
    for dp, dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return round(total / (1024 * 1024))


def _git(path, *a):
    try:
        r = subprocess.run(["git", "-C", path, *a], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _git_info(path, measure_worktrees):
    if not _git(path, "rev-parse", "--git-dir"):
        return None
    wt = []
    for line in _git(path, "worktree", "list").splitlines()[1:]:
        wp = line.split()[0]
        mb = _dir_mb(wp) if measure_worktrees else 0
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(wp)).strftime("%Y-%m-%d")
        except Exception:
            mtime = "?"
        wt.append({"path": wp, "name": os.path.basename(wp), "mb": mb, "mtime": mtime,
                   "dirty": len(_git(wp, "status", "--porcelain").splitlines()) if measure_worktrees else -1,
                   "branch": _git(wp, "branch", "--show-current") if measure_worktrees else ""})
    return {"branch": _git(path, "branch", "--show-current"), "commit": _git(path, "rev-parse", "--short", "HEAD"),
            "dirty": len(_git(path, "status", "--porcelain").splitlines()), "worktrees": wt,
            "worktree_mb": sum(w["mb"] for w in wt), "last": _git(path, "log", "-1", "--format=%cs")}


def mcp_servers(claude_home):
    cb = host.claude_bin(claude_home)
    if not cb:
        return {"checked": False, "servers": []}
    out = []
    for line in host.run([cb, "mcp", "list"], timeout=90).splitlines():
        m = re.match(r"^(.+?):\s+(.+?)\s+-\s+(.+)$", line.strip())
        if not m:
            continue
        st = m.group(3)
        status = "ok" if "Connected" in st else "auth" if "authentication" in st else \
                 "unverified" if ("Executable not found" in st or "ENOENT" in st) else "failed"
        out.append({"name": m.group(1), "target": m.group(2)[:90], "status": status, "detail": st[:80]})
    return {"checked": True, "servers": out}


def sessions(claude_home):
    d = os.path.join(claude_home, "projects")
    out = []
    if not os.path.isdir(d):
        return out
    for e in sorted(os.listdir(d)):
        p = os.path.join(d, e)
        if not os.path.isdir(p):
            continue
        files = [os.path.join(p, f) for f in os.listdir(p) if f.endswith(".jsonl")]
        if not files:
            continue
        newest = max(files, key=os.path.getmtime)
        cwd = None
        try:
            with open(newest, encoding="utf-8", errors="replace") as fh:
                for _ in range(40):
                    line = fh.readline()
                    if not line:
                        break
                    m = re.search(r'"cwd":"([^"]+)"', line)
                    if m:
                        cwd = m.group(1); break
        except Exception:
            pass
        out.append({"key": e, "cwd": cwd, "count": len(files),
                    "mb": round(sum(os.path.getsize(f) for f in files) / 1e6, 1),
                    "last": datetime.fromtimestamp(os.path.getmtime(newest)).strftime("%Y-%m-%d")})
    return sorted(out, key=lambda x: x["last"], reverse=True)


def _unique_name(root, roots, seen):
    """Project name = basename; if taken, use the path relative to its scan root (e.g. 'actanova/apps/api')."""
    name = os.path.basename(root)
    if name in seen:
        for r in roots:
            if root.startswith(r.rstrip("/") + "/"):
                name = os.path.relpath(root, r); break
    seen.add(name)
    return name


def run(cfg):
    ch = cfg["claude_home"]; sc = cfg["scan"]
    data = {"generated": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"),
            "claude_home": ch, "global": {}, "projects": [], "sessions": sessions(ch)}
    data["global"] = {k: _assets(ch, k) for k in ("agents", "skills", "commands", "rules")}
    cx = cfg.get("codex_home") or ""
    data["codex"] = {"present": os.path.isdir(cx), "home": cx,
                     "agents": _assets(os.path.join(cx, "agents"), "agents_toml") if os.path.isdir(cx) else [],
                     "skills": _assets(cx, "skills") if os.path.isdir(cx) else []}
    data["mcp"] = mcp_servers(ch) if sc.get("check_mcp") else {"checked": False, "servers": []}
    seen_names = set()
    for cdir in sorted(find_claude_dirs(cfg["roots"], set(sc["skip_dirs"]))):
        root = os.path.dirname(cdir)
        if os.path.realpath(root) == os.path.realpath(HOME):     # ~/.claude is the global one
            continue
        entry = {"path": root, "name": _unique_name(root, cfg["roots"], seen_names),
                 "agents": _assets(cdir, "agents"), "skills": _assets(cdir, "skills"),
                 "commands": _assets(cdir, "commands"), "rules": _assets(cdir, "rules"),
                 "git": _git_info(root, sc.get("measure_worktrees", True)),
                 "claude_md": os.path.isfile(os.path.join(root, "CLAUDE.md")),
                 "agents_md": os.path.lexists(os.path.join(root, "AGENTS.md")),
                 "agents_md_link": os.path.islink(os.path.join(root, "AGENTS.md"))}
        has_assets = any(entry[k] for k in ("agents", "skills", "commands", "rules"))
        has_harness = any(os.path.exists(os.path.join(cdir, x)) for x in ("MEMORY.md", "HARNESS.md", "hooks", "settings.json"))
        if has_assets or has_harness or entry["claude_md"] or entry["agents_md"]:
            data["projects"].append(entry)
    return data


def cache_path(cfg):
    return os.path.join(cfg["state_dir"], "scan.json")


def save(cfg, data):
    p = cache_path(cfg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def load(cfg):
    try:
        with open(cache_path(cfg), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def ensure(cfg):
    """Return cached scan; run one if there is none yet (first launch)."""
    d = load(cfg)
    if d is None:
        d = run(cfg); save(cfg, d)
    return d


def project_roots(cfg, data=None):
    """{name: abs_root} incl. 'global' -> claude_home."""
    data = data or ensure(cfg)
    out = {"global": cfg["claude_home"]}
    for p in data.get("projects", []):
        out[p["name"]] = p["path"]
    return out
