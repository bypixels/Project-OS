"""`cabina check` — health of the environment. Read-only. Exit 1 if anything critical.
Every detector encodes a failure that once went unnoticed for weeks."""
import os, re, json, sys, time
from datetime import datetime
from . import scan, harness as HAR, usage, drift as DR
from .contract import Contract
from .i18n import t
from . import host

SEV_ORDER = {"crit": 0, "warn": 1, "info": 2}


def run(cfg, quick=False):
    """Returns list of findings: {sev, title, detail, fix}."""
    L = cfg["language"]; ch = cfg["claude_home"]
    F = []
    add = lambda sev, title, detail="", fix="": F.append({"sev": sev, "title": title, "detail": detail, "fix": fix})
    data = scan.load(cfg)
    skills_dir = os.path.join(ch, "skills"); agents_dir = os.path.join(ch, "agents")

    # 1. broken symlinks in skills/agents/_archive
    broken = []
    for base in (skills_dir, agents_dir, os.path.join(ch, "_archive")):
        for dp, dn, fn in os.walk(base):
            for e in list(dn) + fn:
                p = os.path.join(dp, e)
                if os.path.islink(p) and not os.path.exists(p):
                    broken.append(p)
    if broken:
        add("crit", t(L, "check.broken_links", n=len(broken)), t(L, "check.broken_links.d") + "\n    " + "\n    ".join(broken[:8]))

    # 2. skill dirs without SKILL.md
    shells = [e for e in os.listdir(skills_dir) if not e.startswith(".") and os.path.isdir(os.path.join(skills_dir, e))
              and not os.path.isfile(os.path.join(skills_dir, e, "SKILL.md"))] if os.path.isdir(skills_dir) else []
    if shells:
        add("crit", t(L, "check.shell_skills", n=len(shells)), t(L, "check.shell_skills.d", names=", ".join(shells)))

    # 3. agents referencing missing skills  (rubric delegation: "skill `x`")
    present = set(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else set()
    orphans = {}
    dirs = [agents_dir] + [os.path.join(p["path"], ".claude", "agents") for p in (data or {}).get("projects", [])]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if not f.endswith(".md"):
                continue
            try:
                txt = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            for m in re.finditer(r"skill `([a-z0-9-]+)`", txt):
                if m.group(1) not in present:
                    orphans.setdefault(m.group(1), []).append(os.path.join(d, f))
    if orphans:
        det = "\n    ".join(f"{k} <- {', '.join(v)}" for k, v in orphans.items())
        add("crit", t(L, "check.orphan_skill_refs", n=len(orphans)), t(L, "check.orphan_skill_refs.d") + "\n    " + det, t(L, "fix.archive_or_restore"))

    # 4. agent contract (severity from config)
    C = Contract(cfg)
    glob = C.validate_dir(agents_dir); gnames = frozenset(r.name for r in glob if r.is_agent)
    rows = [("global", r) for r in glob]
    for p in (data or {}).get("projects", []):
        for r in C.validate_dir(os.path.join(p["path"], ".claude", "agents"), gnames):
            rows.append((p["name"], r))
    inv = [(p, r) for p, r in rows if r.category == "invalid"]
    wrn = [(p, r) for p, r in rows if r.category == "warnings"]
    docs = [(p, r) for p, r in rows if r.category == "document"]
    if inv:
        det = "\n    ".join(f"{p}/{r.name}: {r.critical[0]}" for p, r in inv[:8]) + (f"\n    … +{len(inv)-8}" if len(inv) > 8 else "")
        add("crit", t(L, "check.invalid_agents", n=len(inv)), t(L, "check.invalid_agents.d") + "\n    " + det, t(L, "fix.agents_invalid"))
    if wrn:
        kinds = {}
        for _, r in wrn:
            for w in r.warnings:
                k = w.split("(")[0].split(":")[0].strip(); kinds[k] = kinds.get(k, 0) + 1
        add("warn", t(L, "check.warn_agents", n=len(wrn)), t(L, "check.warn_agents.d", kinds=", ".join(f"{v} {k}" for k, v in sorted(kinds.items(), key=lambda x: -x[1]))), t(L, "fix.agents_invalid"))
    if docs:
        add("info", t(L, "check.docs_in_agents", n=len(docs)), t(L, "check.docs_in_agents.d") + "\n    " + ", ".join(f"{p}/{r.name}" for p, r in docs[:6]) + (" …" if len(docs) > 6 else ""))

    # 4b. Codex agents (TOML) against the codex contract
    cx = cfg.get("codex_home") or ""
    if os.path.isdir(os.path.join(cx, "agents")):
        cres = Contract(cfg, tool="codex").validate_dir(os.path.join(cx, "agents"))
        cinv = [r for r in cres if r.category in ("invalid", "error")]
        if cinv:
            add("crit", t(L, "check.codex_invalid", n=len(cinv)), "\n    ".join(f"{r.name}: {(r.critical or ['?'])[0]}" for r in cinv[:8]))

    # 4c. drift between Claude Code and Codex
    if data and os.path.isdir(cx):
        dr = DR.report(cfg, data)
        tw = [x for x in dr["twins"] if x["status"] == "diverged"]
        if tw:
            add("warn", t(L, "check.twins", n=len(tw)), "\n    ".join(f"{x['name']}  similarity {x['similarity']}" for x in tw), t(L, "fix.twins"))
        dv = [x for x in dr["rules"] if x["status"] == "diverged"]
        cp = [x for x in dr["rules"] if x["status"] == "copy"]
        if dv:
            add("warn", t(L, "check.rules_diverged", n=len(dv)), "\n    ".join(f"{x['project']}: {x.get('diff_lines', '?')} lines differ" for x in dv), t(L, "fix.rules"))
        if cp:
            add("info", t(L, "check.rules_copy", n=len(cp)), ", ".join(x["project"] for x in cp), t(L, "fix.rules"))
        sk = [x for x in dr["skills"] if x["status"] == "diverged"]
        if sk:
            add("warn", t(L, "check.skill_copies", n=len(sk)), ", ".join(x["name"] for x in sk))

    # 5. harness hooks
    if data:
        dead, brk = [], []
        for e in HAR.states(data):
            dead += [f"{e['name']}/{h}" for h in e["hooks_dead"]]; brk += [f"{e['name']}/{h}" for h in e["hooks_broken"]]
        if brk:
            add("crit", t(L, "check.broken_hooks", n=len(brk)), t(L, "check.broken_hooks.d") + "\n    " + "\n    ".join(brk), t(L, "fix.remove_wire"))
        if dead:
            add("warn", t(L, "check.dead_hooks", n=len(dead)), t(L, "check.dead_hooks.d") + "\n    " + "\n    ".join(dead), t(L, "fix.wire_or_archive"))

    # 6. stale clean worktrees
    days = cfg["check"]["worktree_stale_days"]
    stale, mb = [], 0
    for p in (data or {}).get("projects", []):
        for w in (p.get("git") or {}).get("worktrees", []):
            try:
                age = (time.time() - time.mktime(time.strptime(w["mtime"], "%Y-%m-%d"))) / 86400
            except Exception:
                continue
            if w["dirty"] == 0 and age > days:
                stale.append((p["name"], w["name"], w["mb"], int(age))); mb += w["mb"]
    if stale:
        top = "\n    ".join(f"{a}/{b}  {c} MB  {d} d" for a, b, c, d in sorted(stale, key=lambda x: -x[2])[:6])
        add("warn", t(L, "check.stale_worktrees", n=len(stale), days=days, gb=f"{mb/1024:.1f}"), t(L, "check.stale_worktrees.d") + "\n    " + top, t(L, "fix.worktree"))

    # 7. MCP (only if the scan checked it)
    if data and data.get("mcp", {}).get("checked"):
        srv = data["mcp"]["servers"]
        auth = [s["name"] for s in srv if s["status"] == "auth"]; failed = [f"{s['name']} ({s['detail'][:40]})" for s in srv if s["status"] == "failed"]
        unv = [s["name"] for s in srv if s["status"] == "unverified"]
        if auth: add("warn", t(L, "check.mcp_auth", n=len(auth)), ", ".join(auth))
        if failed: add("crit", t(L, "check.mcp_failed", n=len(failed)), "\n    ".join(failed))
        if unv: add("info", t(L, "check.mcp_unverified", n=len(unv)), t(L, "check.mcp_unverified.d") + "\n    " + ", ".join(unv))

    # 8. never-invoked agents (slow-ish: reads history)
    if not quick and data:
        items = usage.load(os.path.join(cfg["state_dir"], "usage-agents.json"))
        defined = {r.name for _, r in rows if r.is_agent}
        never = sorted(defined - {k for k, v in items.items() if v.get("n_total", 0) > 0})
        if never and items:
            add("info", t(L, "check.unused_agents", n=len(never)), ", ".join(never[:14]) + (" …" if len(never) > 14 else ""))

    # 9. scan freshness
    cp = scan.cache_path(cfg)
    if os.path.exists(cp):
        age = (time.time() - os.path.getmtime(cp)) / 86400
        if age > 7:
            add("info", t(L, "check.stale_scan", days=int(age)), "", t(L, "fix.rescan"))
    else:
        add("warn", t(L, "check.no_scan"), "", t(L, "fix.rescan"))

    F.sort(key=lambda h: SEV_ORDER.get(h["sev"], 9))
    return F


def render(cfg, findings, color=True):
    L = cfg["language"]
    C = {"crit": "\033[31m", "warn": "\033[33m", "ok": "\033[32m", "dim": "\033[90m", "b": "\033[1m", "r": "\033[0m"} if color else {k: "" for k in "crit warn ok dim b r".split()}
    n = {s: sum(1 for f in findings if f["sev"] == s) for s in ("crit", "warn", "info")}
    out = [f"\n{C['b']}{t(L, 'health.title')}{C['r']}  {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    if not findings:
        out.append(f"  {C['ok']}{t(L, 'health.ok')}{C['r']}\n"); return "\n".join(out)
    out.append("  " + t(L, "health.summary", **n) + "\n")
    for f in findings:
        col = C.get(f["sev"], "")
        out.append(f"  {col}[{t(L, 'sev.' + f['sev'])}]{C['r']} {C['b']}{f['title']}{C['r']}")
        for line in (f["detail"] or "").split("\n"):
            if line.strip():
                out.append(f"    {C['dim']}{line if line.startswith('    ') else line.strip()}{C['r']}")
        if f["fix"]:
            out.append(f"    {C['dim']}-> {f['fix']}{C['r']}")
        out.append("")
    return "\n".join(out)


def notify(cfg, findings):
    n_c = sum(1 for f in findings if f["sev"] == "crit"); n_w = sum(1 for f in findings if f["sev"] == "warn")
    if n_c:
        host.notify("cabina: attention", f"{n_c} critical, {n_w} warnings. Run: cabina check", urgent=True)
    elif n_w:
        host.notify("cabina", f"{n_w} warnings. Run: cabina check")
