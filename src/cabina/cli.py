"""cabina — one entrypoint, subcommands.

  cabina                 open the UI (local server + browser)
  cabina check           health check; exit 1 on critical findings   [--quick] [--json] [--notify]
  cabina agents          agent roster                                 [--invalid] [--unused] [--project P]
  cabina agents archive NAME --project P [--force]
  cabina scan            rebuild the cache                            [--mcp]
  cabina fleet           terminal TUI (live provider + roster)
  cabina config          print the effective config / write an example
"""
import argparse, json, os, sys
from . import __version__, config as CFG


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cabina", description="Control plane for a Claude Code environment. Measures, warns, blocks — never acts on its own.")
    ap.add_argument("--version", action="version", version=f"cabina {__version__}")
    ap.add_argument("--config", help="path to config.toml (default: ~/.config/cabina/config.toml or $CABINA_CONFIG)")
    sub = ap.add_subparsers(dest="cmd")

    ui = sub.add_parser("ui", help="open the web UI (default)")
    ui.add_argument("--port", type=int); ui.add_argument("--no-open", action="store_true")

    ck = sub.add_parser("check", help="health check (exit 1 on critical)")
    ck.add_argument("--quick", action="store_true", help="skip slow detectors (usage history)")
    ck.add_argument("--json", action="store_true"); ck.add_argument("--notify", action="store_true", help="desktop notification if anything to see")
    ck.add_argument("--repo", metavar="PATH", help="check ONE repository on its own (CI mode): .claude/agents against .cabina.toml; no home, no cache")

    ag = sub.add_parser("agents", help="agent roster")
    ag.add_argument("action", nargs="?", choices=["list", "archive", "refs"], default="list")
    ag.add_argument("name", nargs="?"); ag.add_argument("--project"); ag.add_argument("--force", action="store_true")
    ag.add_argument("--invalid", action="store_true"); ag.add_argument("--unused", action="store_true"); ag.add_argument("--json", action="store_true")
    ag.add_argument("--tool", choices=["claude", "codex"], help="only agents of one tool")

    sc = sub.add_parser("scan", help="rebuild the environment cache")
    sc.add_argument("--mcp", action="store_true", help="also check MCP servers (needs the claude CLI; slow)")
    sc.add_argument("--worktrees", action="store_true", help="also measure worktree sizes with du (~2 s each)")

    sub.add_parser("fleet", help="terminal TUI")
    ex = sub.add_parser("export", help="export this environment as JSON (agents, skills, harness, projects)"); ex.add_argument("-o", "--out")
    cp = sub.add_parser("compare", help="compare two exports (two machines, or then vs now)"); cp.add_argument("a"); cp.add_argument("b")
    ini = sub.add_parser("init", help="print an example .cabina.toml (--ci: the GitHub Actions workflow)"); ini.add_argument("--ci", action="store_true")
    mc = sub.add_parser("mcp", help="run the read-only MCP server over stdio (register with --install)"); mc.add_argument("--install", action="store_true", help="print how to register it in Claude Code and Codex")
    sub.add_parser("guard", help="hook: PreToolUse on Edit|Write — validate agent files (reads stdin JSON)")
    br = sub.add_parser("brief", help="hook: SessionStart — print a short health/context brief"); br.add_argument("--cwd")
    hk = sub.add_parser("hooks", help="print the settings.json entries for guard+brief; --write merges them")
    hk.add_argument("--write", action="store_true"); hk.add_argument("--settings", help="path to settings.json (default: ~/.claude/settings.json)")
    hk.add_argument("--cmd", default="cabina", help="command name to wire (default: cabina)")
    cf = sub.add_parser("config", help="show effective config"); cf.add_argument("--example", action="store_true", help="print an example config.toml")

    ac = sub.add_parser("activity", help="session activity read from Claude Code transcripts")
    ac.add_argument("--project"); ac.add_argument("--days", type=int, default=30); ac.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    cfg = CFG.load(a.config)

    if a.cmd == "config":
        print(CFG.example_toml() if a.example else json.dumps(cfg, indent=1, ensure_ascii=False)); return 0
    if a.cmd == "scan":
        from . import scan
        cfg["scan"]["check_mcp"] = cfg["scan"]["check_mcp"] or a.mcp
        cfg["scan"]["measure_worktrees"] = cfg["scan"]["measure_worktrees"] or a.worktrees
        d = scan.run(cfg); p = scan.save(cfg, d)
        print(f"scanned {len(d['projects'])} projects · {len(d['global']['agents'])} global agents · {len(d['global']['skills'])} global skills -> {p}"); return 0
    if a.cmd == "check" and a.repo:
        from . import repo
        r = repo.check_repo(a.repo)
        print(json.dumps(r, indent=1) if a.json else repo.render(r)); return r["exit"]
    if a.cmd == "check":
        from . import check
        F = check.run(cfg, quick=a.quick)
        if a.json: print(json.dumps(F, ensure_ascii=False, indent=1))
        else: print(check.render(cfg, F, color=sys.stdout.isatty()))
        if a.notify: check.notify(cfg, F)
        return 1 if any(f["sev"] == "crit" for f in F) else 0
    if a.cmd == "agents":
        return _agents(cfg, a)
    if a.cmd == "export":
        from . import snapshot
        d = snapshot.export(cfg); txt = json.dumps(d, indent=1, ensure_ascii=False)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(txt); print(f"exported {len(d['agents'])} agents, {len(d['skills'])} skills, {len(d['projects'])} projects -> {a.out}")
        else:
            print(txt)
        return 0
    if a.cmd == "compare":
        from . import snapshot
        A = json.load(open(a.a, encoding="utf-8")); B = json.load(open(a.b, encoding="utf-8"))
        print(snapshot.render_compare(snapshot.compare(A, B), A.get("machine") or a.a, B.get("machine") or a.b)); return 0
    if a.cmd == "init":
        from . import repo
        print(repo.CI_YAML if a.ci else repo.EXAMPLE_TOML); return 0
    if a.cmd == "fleet":
        from . import fleet; return fleet.run(cfg) or 0
    if a.cmd == "mcp":
        from . import mcp
        if a.install:
            sn = mcp.install_snippets()
            print("# Claude Code:\n" + sn["claude_code"] + "\n\n# Codex (~/.codex/config.toml):\n" + sn["codex_toml"]); return 0
        mcp.serve(cfg); return 0
    if a.cmd == "guard":
        from . import guard; return guard.run(cfg, guard.read_stdin_briefly(timeout=5.0))
    if a.cmd == "brief":
        from . import guard
        d = {}
        if not a.cwd:
            try:
                d = json.loads(guard.read_stdin_briefly() or "{}")
            except Exception:
                d = {}
        sys.stdout.write(guard.brief(cfg, cwd=a.cwd or d.get("cwd"))); return 0
    if a.cmd == "hooks":
        from . import guard
        sp = a.settings or os.path.join(cfg["claude_home"], "settings.json")
        if a.write:
            ok, msg = guard.hooks_write(sp, a.cmd); print(msg); return 0 if ok else 1
        print(json.dumps(guard.hooks_snippet(a.cmd), indent=2)); print(f"\n# to apply:  cabina hooks --write   (merges into {sp}, keeps a backup)"); return 0
    if a.cmd == "activity":
        from . import sessions
        items = sessions.refresh(cfg, days=a.days)
        if a.project:
            items = [s for s in items if (s.get("project") or "").lower() == a.project.lower()]
        if a.json:
            print(json.dumps(items, ensure_ascii=False, indent=1)); return 0
        print(f"\n{'project':<20} {'started':<25} {'dur':>6} {'turns':>5} {'files':>5}  title")
        print("─" * 100)
        for s in items[:60]:
            dur = f"{(s['duration_s'] or 0) // 60}m"
            print(f"{(s['project'] or '—')[:20]:<20} {(s['started'] or '—')[:24]:<25} {dur:>6} {s['turns']:>5} {len(s['files_touched']):>5}  {(s['title'] or '—')[:50]}")
        print("─" * 100)
        print(f"  {len(items)} sessions\n")
        return 0
    from . import server
    port = getattr(a, "port", None); no_open = getattr(a, "no_open", False)
    server.serve(cfg, port=port, open_browser=not no_open); return 0


def _agents(cfg, a):
    from .roster import Roster
    from . import usage
    R = Roster(cfg)
    if a.action == "refs":
        if not a.name: print("usage: cabina agents refs NAME"); return 2
        for r in R.references(a.name): print(r)
        return 0
    if a.action == "archive":
        if not a.name or not a.project: print("usage: cabina agents archive NAME --project P [--force]"); return 2
        ok, msg, refs = R.archive(a.name, a.project, a.force, tool=a.tool or "claude")
        print(msg)
        for r in refs[:12]: print("   ", r)
        return 0 if ok else 1
    rows, items = R.load()
    hom = Roster.homonyms(rows)
    out = []
    for proj, r, path, tool in rows:
        u = usage.for_agent(items, r.name, proj) if tool == "claude" else {"total": 0, "here": None, "last": None, "attributed": True}
        if a.tool and tool != a.tool: continue
        if a.project and proj.lower() != a.project.lower(): continue
        if a.invalid and r.category not in ("invalid", "warnings"): continue
        if a.unused and (u["total"] > 0 or not r.is_agent): continue
        out.append((proj, r, u, path, tool))
    if a.json:
        print(json.dumps([{"name": r.name, "project": p, "tool": t, "category": r.category, "model": r.fields.get("model", ""),
                           "uses": u["total"], "uses_here": u["here"], "last": u["last"], "critical": r.critical, "warnings": r.warnings, "path": path} for p, r, u, path, t in out], ensure_ascii=False, indent=1)); return 0
    order = {"invalid": 0, "warnings": 1, "valid": 2, "document": 3, "error": 4}
    out.sort(key=lambda x: (order[x[1].category], x[4], -(x[2]["total"]), x[0], x[1].name))
    print(f"\n{'agent':<28} {'where':<20} {'tool':<7} {'model':<7} {'last':<11} {'uses':>5}  state")
    print("─" * 100)
    for proj, r, u, path, tool in out:
        n = u["here"] if u["attributed"] and u["here"] is not None else u["total"]
        mark = "" if u["attributed"] or hom.get(r.name, 0) < 2 else "≈"
        det = (r.critical or r.warnings or [""])[0][:38]
        print(f"{r.name:<28} {proj[:20]:<20} {tool:<7} {(r.fields.get('model') or '—')[:6]:<7} {(u['last'] or '—'):<11} {n:>4}{mark:1} {r.category:<9} {det}")
    ag = [r for _, r, _, _, _ in out if r.is_agent]
    nc = sum(1 for _, _, _, _, t in out if t == "codex")
    print("─" * 100)
    print(f"  {len(ag)} agents ({nc} codex) · {sum(1 for r in ag if r.category=='invalid')} invalid · {sum(1 for r in ag if r.category=='warnings')} warnings · "
          f"{sum(1 for _, r, u, _, t in out if r.is_agent and t=='claude' and u['total']==0)} unused · {sum(1 for _, r, _, _, _ in out if r.category=='document')} documents\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
