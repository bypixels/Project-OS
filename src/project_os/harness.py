"""Harness state per project (HARNESS.md, MEMORY.md, hooks wired vs on disk, rules, workflows)
and the run log (harness-runs.md). Read-only."""
import os, re, json, time

PIECES = ("HARNESS.md", "MEMORY.md", "hooks", "rules")


def _wired_hooks(cdir):
    out = set()
    for f in ("settings.json", "settings.local.json"):
        fp = os.path.join(cdir, f)
        if not os.path.isfile(fp):
            continue
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        for _, lst in (d.get("hooks") or {}).items():
            for h in lst or []:
                for hh in h.get("hooks", []) or []:
                    for m in re.finditer(r"hooks/([\w.-]+)", hh.get("command", "") or ""):
                        out.add(m.group(1))
    return out


def _is_helper(h):
    return h.startswith(("test-", "test_", "_", "lib-", "lib_", "common")) or h.endswith((".test.sh", "_test.sh"))


def project_state(root):
    c = os.path.join(root, ".claude")
    has = {"CLAUDE.md": os.path.isfile(os.path.join(root, "CLAUDE.md")),
           "HARNESS.md": os.path.isfile(os.path.join(c, "HARNESS.md")),
           "MEMORY.md": os.path.isfile(os.path.join(c, "MEMORY.md"))}
    hd = os.path.join(c, "hooks")
    on_disk = sorted(f for f in os.listdir(hd) if not f.startswith(".") and os.path.isfile(os.path.join(hd, f))) if os.path.isdir(hd) else []
    wired = _wired_hooks(c)
    helpers = sorted(h for h in on_disk if _is_helper(h))
    dead = sorted(h for h in on_disk if h not in wired and not _is_helper(h))
    broken = sorted(h for h in wired if h not in on_disk)
    rd = os.path.join(c, "rules"); wd = os.path.join(c, "workflows")
    n_rules = len([f for f in os.listdir(rd) if f.endswith(".md")]) if os.path.isdir(rd) else 0
    n_wf = len([f for f in os.listdir(wd) if f.endswith(".js")]) if os.path.isdir(wd) else 0
    has["hooks"] = bool(on_disk); has["rules"] = n_rules > 0; has["workflows"] = n_wf > 0
    missing = [p for p in PIECES if not has[p]]
    mem = os.path.join(c, "MEMORY.md")
    if not has["HARNESS.md"] and not has["MEMORY.md"] and not on_disk:
        level = "none"
    elif missing or dead or broken:
        level = "partial"
    else:
        level = "complete"
    return {"level": level, "has": has, "missing": missing, "hooks": on_disk,
            "hooks_active": sorted(h for h in on_disk if h in wired), "hooks_dead": dead,
            "hooks_broken": broken, "hooks_helpers": helpers, "rules": n_rules, "workflows": n_wf,
            "memory_days": int((time.time() - os.path.getmtime(mem)) / 86400) if os.path.isfile(mem) else None,
            "runlog": os.path.isfile(os.path.join(c, "harness-runs.md"))}


def states(data):
    out = []
    for p in data.get("projects", []):
        if os.path.isdir(p["path"]):
            e = project_state(p["path"]); e["name"] = p["name"]; e["path"] = p["path"]; out.append(e)
    order = {"complete": 0, "partial": 1, "none": 2}
    out.sort(key=lambda x: (order[x["level"]], x["name"]))
    return out


# ---- run log ----
_NUM = re.compile(r"(\d+(?:[.,]\d+)?)\s*k", re.I)
_FUN = re.compile(r"(\d+)[^→\d]*→[^\d]*(\d+)[^→\d]*→[^\d]*(\d+)")


def _tokens_k(txt):
    m = _NUM.search(txt or "")
    try:
        return int(float(m.group(1).replace(",", "."))) if m else None
    except ValueError:
        return None


def read_runlog(path):
    if not os.path.isfile(path):
        return []
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        if not re.match(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        date_, task, vehicle, agents, tokens, funnel, consq = cells[:7]
        m = _FUN.search(funnel); c = re.match(r"\s*(\d+)", consq)
        rows.append({"date": date_, "task": task, "vehicle": vehicle, "agents": agents, "tokens": tokens,
                     "tokens_k": _tokens_k(tokens), "funnel_txt": funnel,
                     "funnel": [int(m.group(1)), int(m.group(2)), int(m.group(3))] if m else None,
                     "consequential": int(c.group(1)) if c else 0, "notes": cells[7] if len(cells) > 7 else ""})
    rows.sort(key=lambda x: x["date"], reverse=True)
    return rows


def summarize(rows):
    with_tok = [r for r in rows if r.get("tokens_k") is not None]
    tok = sum(r["tokens_k"] for r in with_tok)
    cm = sum(r.get("consequential", 0) for r in with_tok)
    return {"runs": len(rows), "consequential": sum(r.get("consequential", 0) for r in rows),
            "tokens_k_measured": tok, "runs_with_tokens": len(with_tok),
            "k_per_consequential": (tok // cm) if cm else None}


def runlogs(data):
    out = []
    for p in data.get("projects", []):
        b = os.path.join(p["path"], ".claude", "harness-runs.md")
        if os.path.isfile(b):
            rows = read_runlog(b)
            out.append({"project": p["name"], "path": b, "rows": rows, "summary": summarize(rows)})
    return out
