"""project-os — one entrypoint, subcommands.

  project-os                  open the UI (default; same as `project-os ui`)
  project-os ui               open the web UI                              [--port] [--no-open]
  project-os check            health check; exit 1 on critical findings     [--quick] [--json] [--notify] [--repo PATH]
  project-os agents           agent roster / archive / references           [list|archive|refs] [--invalid] [--unused] [--project P] [--tool claude|codex] [--json] [--force]
  project-os scan             rebuild the environment cache                 [--mcp] [--worktrees]
  project-os fleet            terminal TUI (live provider + roster)
  project-os export           export this environment as JSON               [-o PATH] [--activity] [--detail] [--titles] [--project P]
  project-os compare A B      compare two exports (two machines, or then vs now)
  project-os init             print an example .project-os.toml (or the CI workflow)   [--ci]
  project-os mcp              run the read-only MCP server over stdio       [--install]
  project-os guard            hook: PreToolUse on Edit|Write — validate agent files (reads stdin JSON)
  project-os brief            hook: SessionStart — print a short health/context brief   [--cwd PATH]
  project-os hooks            print (or write) the settings.json entries for guard+brief   [--write] [--settings PATH] [--cmd NAME]
  project-os config           print the effective config / write an example   [--example]
  project-os activity         session activity read from Claude Code transcripts   [--project P] [--days N] [--json]
  project-os hub DIR          serve the UI, read-only, over N `project-os export --activity` files   [--port] [--no-open]
  project-os worktrees        worktree cleanup report: a script to review and run yourself [--project P] [--json]
"""
import argparse, json, os, sys, textwrap
from . import __version__, config as CFG
from .i18n import t


def main(argv=None):
    ap = argparse.ArgumentParser(prog="project-os", description="Control plane for a Claude Code environment. Measures, warns, blocks — never acts on its own.")
    ap.add_argument("--version", action="version", version=f"project-os {__version__}")
    ap.add_argument("--config", help="path to config.toml (default: ~/.config/project-os/config.toml or $PROJECT_OS_CONFIG)")
    sub = ap.add_subparsers(dest="cmd")

    ui = sub.add_parser("ui", help="open the web UI (default)")
    ui.add_argument("--port", type=int); ui.add_argument("--no-open", action="store_true")

    ck = sub.add_parser("check", help="health check (exit 1 on critical)")
    ck.add_argument("--quick", action="store_true", help="skip slow detectors (usage history)")
    ck.add_argument("--json", action="store_true"); ck.add_argument("--notify", action="store_true", help="desktop notification if anything to see")
    ck.add_argument("--repo", metavar="PATH", help="check ONE repository on its own (CI mode): .claude/agents against .project-os.toml; no home, no cache")

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
    ex.add_argument("--activity", action="store_true", help="also export session activity (aggregated per project by default)")
    ex.add_argument("--detail", action="store_true", help="with --activity: add per-session rows")
    ex.add_argument("--titles", action="store_true", help="with --activity --detail: add session titles")
    ex.add_argument("--project", action="append", help="with --activity: restrict to this project (repeatable)")
    cp = sub.add_parser("compare", help="compare two exports (two machines, or then vs now)"); cp.add_argument("a"); cp.add_argument("b")
    ini = sub.add_parser("init", help="print an example .project-os.toml (--ci: the GitHub Actions workflow)"); ini.add_argument("--ci", action="store_true")
    mc = sub.add_parser("mcp", help="run the read-only MCP server over stdio (register with --install)"); mc.add_argument("--install", action="store_true", help="print how to register it in Claude Code and Codex")
    sub.add_parser("guard", help="hook: PreToolUse on Edit|Write — validate agent files (reads stdin JSON)")
    br = sub.add_parser("brief", help="hook: SessionStart — print a short health/context brief"); br.add_argument("--cwd")
    hk = sub.add_parser("hooks", help="print the settings.json entries for guard+brief; --write merges them")
    hk.add_argument("--write", action="store_true"); hk.add_argument("--settings", help="path to settings.json (default: ~/.claude/settings.json)")
    hk.add_argument("--cmd", dest="hook_cmd", default="project-os", help="command name to wire (default: project-os)")
    cf = sub.add_parser("config", help="show effective config"); cf.add_argument("--example", action="store_true", help="print an example config.toml")

    ac = sub.add_parser("activity", help="session activity read from Claude Code transcripts")
    ac.add_argument("--project"); ac.add_argument("--days", type=int, default=30); ac.add_argument("--json", action="store_true")

    hb = sub.add_parser("hub", help="serve the UI, read-only, over N `project-os export --activity` files in DIR")
    hb.add_argument("dir"); hb.add_argument("--port", type=int); hb.add_argument("--no-open", action="store_true")

    wt = sub.add_parser("worktrees", help="worktree cleanup report: prints a script to review and run yourself (project-os never runs it)")
    wt.add_argument("--project", help="restrict to this project"); wt.add_argument("--json", action="store_true")

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
        from . import check, healthlog
        F = check.run(cfg, quick=a.quick)
        if not a.quick: healthlog.append(cfg, F)   # a quick run skips slow detectors: never record a false sawtooth
        if a.json: print(json.dumps(F, ensure_ascii=False, indent=1))
        else: print(check.render(cfg, F, color=sys.stdout.isatty()))
        if a.notify: check.notify(cfg, F)
        return 1 if any(f["sev"] == "crit" for f in F) else 0
    if a.cmd == "agents":
        return _agents(cfg, a)
    if a.cmd == "export":
        from . import snapshot
        activity = None
        if a.activity:
            try:
                activity = snapshot.export_activity(cfg, projects=a.project, detail=a.detail, titles=a.titles)
            except ValueError as e:
                print(f"usage: {e}", file=sys.stderr); return 2
        d = snapshot.export(cfg, activity=activity); txt = json.dumps(d, indent=1, ensure_ascii=False)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(txt)
            print(f"exported {len(d['agents'])} agents, {len(d['skills'])} skills, {len(d['projects'])} projects"
                  + (" + activity" if activity else "") + f" -> {a.out}")
        else:
            print(txt)
        return 0
    if a.cmd == "compare":
        from . import snapshot
        def _load(path):
            try:
                return json.load(open(path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"error: cannot read {path}: {e}", file=sys.stderr); return None
        A = _load(a.a); B = _load(a.b) if A is not None else None
        if A is None or B is None:
            return 2
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
            ok, msg = guard.hooks_write(sp, a.hook_cmd); print(msg); return 0 if ok else 1
        print(json.dumps(guard.hooks_snippet(a.hook_cmd), indent=2)); print(f"\n# to apply:  project-os hooks --write   (merges into {sp}, keeps a backup)"); return 0
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
    if a.cmd == "hub":
        from . import hub
        hub.serve_hub(a.dir, cfg, port=a.port, open_browser=not a.no_open); return 0
    if a.cmd == "worktrees":
        return _worktrees(cfg, a)
    from . import server
    port = getattr(a, "port", None); no_open = getattr(a, "no_open", False)
    server.serve(cfg, port=port, open_browser=not no_open); return 0


def _agents(cfg, a):
    from .roster import Roster
    from . import usage
    R = Roster(cfg)
    if a.action == "refs":
        if not a.name: print("usage: project-os agents refs NAME"); return 2
        for r in R.references(a.name): print(r)
        return 0
    if a.action == "archive":
        if not a.name or not a.project: print("usage: project-os agents archive NAME --project P [--force]"); return 2
        ok, msg, refs = R.archive(a.name, a.project, a.force, tool=a.tool or "claude")
        print(msg)
        for r in refs[:12]: print("   ", r)
        return 0 if ok else 1
    if sys.stderr.isatty():
        # R.load() below refreshes usage by grepping every transcript, which can take ~10s.
        print(t(cfg["language"], "agents.scanning_usage"), file=sys.stderr)
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
        det = textwrap.shorten((r.critical or r.warnings or [""])[0], width=38, placeholder="…")
        print(f"{r.name:<28} {proj[:20]:<20} {tool:<7} {(r.fields.get('model') or '—')[:6]:<7} {(u['last'] or '—'):<11} {n:>4}{mark:1} {r.category:<9} {det}")
    ag = [r for _, r, _, _, _ in out if r.is_agent]
    nc = sum(1 for _, _, _, _, t in out if t == "codex")
    print("─" * 100)
    print(f"  {len(ag)} agents ({nc} codex) · {sum(1 for r in ag if r.category=='invalid')} invalid · {sum(1 for r in ag if r.category=='warnings')} warnings · "
          f"{sum(1 for _, r, u, _, t in out if r.is_agent and t=='claude' and u['total']==0)} unused · {sum(1 for _, r, _, _, _ in out if r.category=='document')} documents\n")
    return 0


def _worktrees(cfg, a):
    from . import scan, worktrees
    data = scan.ensure(cfg)
    s = worktrees.summary(cfg, data, a.project)
    text = worktrees.script(cfg, data, a.project)
    if a.json:
        rs = worktrees.rows(cfg, data, a.project)
        print(json.dumps({"summary": s, "script": text, "rows": rs}, ensure_ascii=False, indent=1))
        return 0
    # The summary line prints right before the pasteable script, so it must be just as safe to
    # paste into an interactive zsh: no backticks (command substitution there) and routed
    # through the same _comment() no-op wrapper as script()'s own lines -- a bare `#` line is
    # not a comment in an interactive zsh without `setopt interactive_comments` either.
    mb = f"{s['mb']} MB" + ("" if s["mb_measured"] else "+ (some sizes unmeasured — run project-os scan --worktrees)")
    print(worktrees._comment(f"{s['total']} worktrees · {s['clean']} clean · {s['dirty']} dirty · {s['unknown']} unknown status · {s['prunable']} prunable · {mb}") + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
