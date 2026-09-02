"""`project-os check` — health of the environment. Read-only. Exit 1 if anything critical.
Every detector encodes a failure that once went unnoticed for weeks."""
import os, re, json, sys, time
from datetime import datetime
from . import scan, harness as HAR, usage, drift as DR, skills as SK, desired as DS
from .contract import Contract
from .i18n import t
from . import host

SEV_ORDER = {"crit": 0, "warn": 1, "info": 2}


def _warn_kind(w):
    """The short 'kind' shown in the grouped `check.warn_agents.d` summary: the text of a
    warning up to its first `(` or top-level `:` — but a `:` INSIDE a backtick-quoted span
    (e.g. "declaring `overrides: global`") must not count as the cut point, or the kind
    comes out with a dangling, unbalanced backtick."""
    masked = re.sub(r"`[^`]*`", lambda m: "`" * len(m.group(0)), w)
    stops = [i for i in (masked.find("("), masked.find(":")) if i != -1]
    return w[:min(stops)].strip() if stops else w.strip()


def run(cfg, quick=False, upstream=False):
    """Returns list of findings: {sev, title, detail, fix}, plus a `projects` list (names as in
    scan.project_roots, "global" for the global home) ONLY when the finding is genuinely about
    one or more specific projects — never guessed from free text. Findings about the environment
    as a whole (broken symlinks in ~/.claude, mcp, stale scan cache…) carry no `projects` key.
    `upstream=True` is the ONLY thing in this module that touches the network (opt-in, never on
    a plain `project-os check`) — see upstream.py; its findings are never `crit`, so `--upstream`
    can never change check's exit code. Those findings also carry `upstream: True` (added ONLY
    when true, same convention as `projects` below) -- they are about whether project-os itself
    is up to date, not about the environment's health, so a caller writing to the 30-day health
    trend (cli.py's `check` branch) must filter them out before appending, or `extra` (which
    ALWAYS includes project-os's own `overrides`/`version` conventions by design) would add a
    finding to every networked run and the trend would measure the flag, not the environment."""
    L = cfg["language"]; ch = cfg["claude_home"]
    F = []
    def add(sev, title, detail="", fix="", projects=None, upstream=False, *, id):
        """`id` is the i18n KEY of the finding (e.g. "check.dead_hooks"), stored as a stable
        identity used by healthlog to diff runs -- keyword-only and required so no call site can
        silently omit it. Two variants of the same detector (e.g. stale-worktrees with/without a
        measured size) MUST pass the same id: identity, not title text, is what healthlog compares."""
        d = {"sev": sev, "title": title, "detail": detail, "fix": fix, "id": id}
        if projects:
            d["projects"] = sorted(set(projects))
        if upstream:
            d["upstream"] = True
        F.append(d)
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
        add("crit", t(L, "check.broken_links", n=len(broken)), t(L, "check.broken_links.d") + "\n    " + "\n    ".join(broken[:8]), id="check.broken_links")

    # 2. skill dirs without SKILL.md
    shells = [e for e in os.listdir(skills_dir) if not e.startswith(".") and os.path.isdir(os.path.join(skills_dir, e))
              and not os.path.isfile(os.path.join(skills_dir, e, "SKILL.md"))] if os.path.isdir(skills_dir) else []
    if shells:
        add("crit", t(L, "check.shell_skills", n=len(shells)), t(L, "check.shell_skills.d", names=", ".join(shells)), id="check.shell_skills")

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
        add("crit", t(L, "check.orphan_skill_refs", n=len(orphans)), t(L, "check.orphan_skill_refs.d") + "\n    " + det, t(L, "fix.archive_or_restore"), id="check.orphan_skill_refs")

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
        add("crit", t(L, "check.invalid_agents", n=len(inv)), t(L, "check.invalid_agents.d") + "\n    " + det, t(L, "fix.agents_invalid"), projects=[p for p, _ in inv], id="check.invalid_agents")
    if wrn:
        kinds = {}
        for _, r in wrn:
            for w in r.warnings:
                k = _warn_kind(w); kinds[k] = kinds.get(k, 0) + 1
        add("warn", t(L, "check.warn_agents", n=len(wrn)), t(L, "check.warn_agents.d", kinds=", ".join(f"{v} {k}" for k, v in sorted(kinds.items(), key=lambda x: -x[1]))), t(L, "fix.agents_invalid"), projects=[p for p, _ in wrn], id="check.warn_agents")
    if docs:
        add("info", t(L, "check.docs_in_agents", n=len(docs)), t(L, "check.docs_in_agents.d") + "\n    " + ", ".join(f"{p}/{r.name}" for p, r in docs[:6]) + (" …" if len(docs) > 6 else ""), projects=[p for p, _ in docs], id="check.docs_in_agents")

    # 4b. Codex agents (TOML) against the codex contract
    cx = cfg.get("codex_home") or ""
    if os.path.isdir(os.path.join(cx, "agents")):
        cres = Contract(cfg, tool="codex").validate_dir(os.path.join(cx, "agents"))
        cinv = [r for r in cres if r.category in ("invalid", "error")]
        if cinv:
            add("crit", t(L, "check.codex_invalid", n=len(cinv)), "\n    ".join(f"{r.name}: {(r.critical or ['?'])[0]}" for r in cinv[:8]), id="check.codex_invalid")

    # 4c. drift between Claude Code and Codex
    if data and os.path.isdir(cx):
        dr = DR.report(cfg, data)
        tw = [x for x in dr["twins"] if x["status"] == "diverged"]
        if tw:
            add("warn", t(L, "check.twins", n=len(tw)), "\n    ".join(f"{x['name']}  similarity {x['similarity']}" for x in tw), t(L, "fix.twins"), id="check.twins")
        dv = [x for x in dr["rules"] if x["status"] == "diverged"]
        cp = [x for x in dr["rules"] if x["status"] == "copy"]
        if dv:
            add("warn", t(L, "check.rules_diverged", n=len(dv)), "\n    ".join(f"{x['project']}: {x.get('diff_lines', '?')} lines differ" for x in dv), t(L, "fix.rules"), projects=[x["project"] for x in dv], id="check.rules_diverged")
        if cp:
            add("info", t(L, "check.rules_copy", n=len(cp)), ", ".join(x["project"] for x in cp), t(L, "fix.rules"), projects=[x["project"] for x in cp], id="check.rules_copy")
        sk = [x for x in dr["skills"] if x["status"] == "diverged"]
        if sk:
            add("warn", t(L, "check.skill_copies", n=len(sk)), ", ".join(x["name"] for x in sk), id="check.skill_copies")

    # 5. harness hooks
    if data:
        dead, brk = [], []
        dead_projects, broken_projects = [], []
        for e in HAR.states(data):
            if e["hooks_dead"]:
                dead += [f"{e['name']}/{h}" for h in e["hooks_dead"]]; dead_projects.append(e["name"])
            if e["hooks_broken"]:
                brk += [f"{e['name']}/{h}" for h in e["hooks_broken"]]; broken_projects.append(e["name"])
        if brk:
            add("crit", t(L, "check.broken_hooks", n=len(brk)), t(L, "check.broken_hooks.d") + "\n    " + "\n    ".join(brk), t(L, "fix.remove_wire"), projects=broken_projects, id="check.broken_hooks")
        if dead:
            add("warn", t(L, "check.dead_hooks", n=len(dead)), t(L, "check.dead_hooks.d") + "\n    " + "\n    ".join(dead), t(L, "fix.wire_or_archive"), projects=dead_projects, id="check.dead_hooks")

    # 6. stale clean worktrees (prunable rows have no directory: they belong to
    # `git worktree prune`, not to this warning; unmeasured sizes must not render as "0.0 GB")
    days = cfg["check"]["worktree_stale_days"]
    stale, mb, all_measured = [], 0, True
    for p in (data or {}).get("projects", []):
        for w in (p.get("git") or {}).get("worktrees", []):
            if w.get("prunable"):
                continue
            try:
                age = (time.time() - time.mktime(time.strptime(w["mtime"], "%Y-%m-%d"))) / 86400
            except Exception:
                continue
            if w["dirty"] == 0 and age > days:
                stale.append((p["name"], w["name"], w["mb"], int(age)))
                if w["mb"] is None:
                    all_measured = False
                else:
                    mb += w["mb"]
    if stale:
        top = "\n    ".join(f"{a}/{b}  {c if c is not None else '?'} MB  {d} d" for a, b, c, d in sorted(stale, key=lambda x: -(x[2] or 0))[:6])
        if all_measured:
            title = t(L, "check.stale_worktrees", n=len(stale), days=days, gb=f"{mb/1024:.1f}")
        else:
            title = t(L, "check.stale_worktrees.nogb", n=len(stale), days=days)
        add("warn", title, t(L, "check.stale_worktrees.d") + "\n    " + top, t(L, "fix.worktree"), projects=[a for a, b, c, d in stale], id="check.stale_worktrees")

    # 7. MCP (only if the scan checked it)
    if data and data.get("mcp", {}).get("checked"):
        srv = data["mcp"]["servers"]
        auth = [s["name"] for s in srv if s["status"] == "auth"]; failed = [f"{s['name']} ({s['detail'][:40]})" for s in srv if s["status"] == "failed"]
        unv = [s["name"] for s in srv if s["status"] == "unverified"]
        if auth: add("warn", t(L, "check.mcp_auth", n=len(auth)), ", ".join(auth), id="check.mcp_auth")
        if failed: add("crit", t(L, "check.mcp_failed", n=len(failed)), "\n    ".join(failed), id="check.mcp_failed")
        if unv: add("info", t(L, "check.mcp_unverified", n=len(unv)), t(L, "check.mcp_unverified.d") + "\n    " + ", ".join(unv), id="check.mcp_unverified")

    # 8. never-invoked agents (slow-ish: reads history). A by-NAME comparison mixes homonyms:
    # if global `deploy` was used, a project's own never-used `deploy` was never reported. Usage
    # items carry by_project -- check per INSTANCE with shadowing semantics: a project's own
    # instance is unused unless by_project credits THAT project; the global instance is unused
    # only when n_total==0, or every recorded use is attributed to a project that defines its
    # own homonym (so it could never have been the global one). Ambiguous cases (unattributed
    # uses, or uses from a project with no homonym of its own) are left alone -- this detector
    # is info, and a false accusation is worse than staying silent.
    if not quick and data:
        items = usage.load(os.path.join(cfg["state_dir"], "usage-agents.json"))
        defined_rows = [(p, r) for p, r in rows if r.is_agent]
        homonym_projects = {}
        for p, r in defined_rows:
            if p != "global":
                homonym_projects.setdefault(r.name, set()).add(p)
        never = []
        for p, r in defined_rows:
            e = items.get(r.name) or {}
            n_total = e.get("n_total", 0)
            bp = e.get("by_project") or {}
            if p == "global":
                hp = homonym_projects.get(r.name, set())
                # NOT just "the homonym-defining subset sums to n_total" -- that can match by
                # coincidence on desynced data (e.g. after transcript rotation) where by_project
                # also carries a key OUTSIDE hp that isn't reflected in n_total at all. Require
                # every by_project key to be homonym-defining AND the full sum to equal n_total,
                # so any unattributed or non-homonym use keeps this silent (ambiguous -> global).
                unused = n_total == 0 or (set(bp) <= hp and sum(bp.values()) == n_total)
            else:
                # symmetric guard: bp.get(p, 0)==0 alone doesn't mean "0 uses here" -- it can
                # also mean "n_total uses that never resolved to ANY project root" (unattributed,
                # by_project={}). Require the full total to be accounted for in by_project, or a
                # genuinely-unattributed use would read as a false "never invoked".
                unused = bp.get(p, 0) == 0 and sum(bp.values()) == n_total
            if unused:
                never.append((p, r))
        if never and items:
            names = sorted({r.name for _, r in never})
            add("info", t(L, "check.unused_agents", n=len(never)), ", ".join(names[:14]) + (" …" if len(names) > 14 else ""),
                projects=[p for p, _ in never], id="check.unused_agents")

    # 8b. never-invoked skills (Claude only: skills.load() reads only claude_home + project
    # .claude dirs, so Codex skills never reach `valid_skills` -- Codex transcripts carry no
    # skill invocations at all (see usage.codex_sessions docstring), so "never used" for one
    # would be a measurement lie, not a finding)
    if not quick and data:
        valid_skills = [r for r in SK.load(cfg, data) if r["state"] == "ok"]
        sitems = usage.load(os.path.join(cfg["state_dir"], "usage-skills.json"))
        # same by-INSTANCE / shadowing fix as #8 above, for skills.
        homonym_projects = {}
        for r in valid_skills:
            if r["project"] != "global":
                homonym_projects.setdefault(r["name"], set()).add(r["project"])
        never_sk = []
        for r in valid_skills:
            e = sitems.get(r["name"]) or {}
            n_total = e.get("n_total", 0)
            bp = e.get("by_project") or {}
            if r["project"] == "global":
                hp = homonym_projects.get(r["name"], set())
                # same desync fix as #8 above: full-set-subset + full-sum-match, not a partial
                # sum over hp alone (which can coincidentally match n_total on desynced data).
                unused = n_total == 0 or (set(bp) <= hp and sum(bp.values()) == n_total)
            else:
                # same symmetric guard as #8 above.
                unused = bp.get(r["project"], 0) == 0 and sum(bp.values()) == n_total
            if unused:
                never_sk.append(r)
        if never_sk and sitems:
            names = sorted({r["name"] for r in never_sk})
            add("info", t(L, "check.unused_skills", n=len(never_sk)), ", ".join(names[:14]) + (" …" if len(names) > 14 else ""),
                t(L, "fix.archive_skill"), projects=[r["project"] for r in never_sk], id="check.unused_skills")

    # 9. scan freshness
    cp = scan.cache_path(cfg)
    if os.path.exists(cp):
        age = (time.time() - os.path.getmtime(cp)) / 86400
        if age > 7:
            add("info", t(L, "check.stale_scan", days=int(age)), "", t(L, "fix.rescan"), id="check.stale_scan")
    else:
        add("warn", t(L, "check.no_scan"), "", t(L, "fix.rescan"), id="check.no_scan")

    # 9b. desired state: a project's own .project-os.toml can declare what its agent
    # environment SHOULD have ([desired].agents/skills/mcp/memory/docs) -- compare against what
    # the scan observed. No [desired] table -> silent (most projects never opt in).
    if data:
        for p in (data.get("projects") or []):
            gp = DS.gaps(cfg, p, data)
            if gp:
                det = "\n    ".join(t(L, f"desired.gap.{g['kind']}", **{k: (", ".join(v) if k == "keys" else v) for k, v in g.items() if k != "kind"}) for g in gp)
                add("warn", t(L, "check.desired_gaps", n=len(gp), project=p["name"]),
                    t(L, "check.desired_gaps.d") + "\n    " + det, t(L, "fix.desired"), projects=[p["name"]], id="check.desired_gaps")

    # 10. upstream drift (opt-in only -- see upstream.py; never emits "crit", so this can never
    # change check's exit code, and never runs unless the caller explicitly asked for it)
    if upstream:
        from . import upstream as UP
        cmp = UP.compare(cfg)
        if cmp["unavailable"]:
            if cmp.get("reason") == "ssl":
                add("info", t(L, "check.upstream_unavailable_ssl"), "", t(L, "fix.upstream_ssl"), upstream=True, id="check.upstream_unavailable_ssl")
            else:
                add("info", t(L, "check.upstream_unavailable"), upstream=True, id="check.upstream_unavailable")
        else:
            if cmp["missing"]:
                add("warn", t(L, "check.upstream_missing", n=len(cmp["missing"])),
                    t(L, "check.upstream_missing.d") + "\n    " + ", ".join(cmp["missing"]), t(L, "fix.upstream_missing"), upstream=True, id="check.upstream_missing")
            if cmp["extra"]:
                add("info", t(L, "check.upstream_extra", n=len(cmp["extra"])),
                    t(L, "check.upstream_extra.d") + "\n    " + ", ".join(cmp["extra"]), upstream=True, id="check.upstream_extra")

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
        host.notify("project-os: attention", f"{n_c} critical, {n_w} warnings. Run: project-os check", urgent=True)
    elif n_w:
        host.notify("project-os", f"{n_w} warnings. Run: project-os check")
