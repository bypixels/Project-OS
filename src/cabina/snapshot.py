"""`cabina export` / `cabina compare` — one environment as a portable JSON, and the diff between two
(two machines, or the same machine over time). Read-only."""
import json, os, platform, socket
from datetime import datetime
from . import scan, skills as SK, harness as HAR, projects as PROJ
from .roster import Roster

_PROJECT_DETAIL_FIELDS = ("name", "branch", "dirty", "worktrees", "docs", "memory_days", "last_commit", "agents", "skills")

_LOCAL_ONLY_FIELDS = ("cwd", "source_path", "mtime", "size", "offset")
_DETAIL_TOKEN_FIELDS = ("in", "out", "cache_read", "cache_write")


def _strip_local_only(row):
    """R9 (cwd/source_path) + P1 (también mtime/size/offset): campos que nunca deben salir de
    esta máquina, sin importar cómo se haya construido la fila. Se aplica en el límite mismo de
    la exportación — no confía en que quien construye la fila nunca los vuelva a agregar.
    Defensa adicional (privacy fix): cualquier entrada de files_touched que sea absoluta se
    descarta aquí también, aunque _detail_row ya la haya filtrado — es la última puerta antes
    de serializar."""
    out = {k: v for k, v in row.items() if k not in _LOCAL_ONLY_FIELDS}
    ft = out.get("files_touched")
    if isinstance(ft, list):
        out["files_touched"] = [f for f in ft if isinstance(f, str) and not os.path.isabs(f) and not f.startswith("~")]
    return out


def _detail_row(s, titles):
    """Una fila de `export --activity --detail`, como lista blanca explícita a partir de un
    resumen de sesión completo `s` (que SÍ trae cwd/source_path/mtime/size/offset — sessions.py
    los guarda solo localmente, no para exportar). titles=True agrega el título.

    Privacy fix: files_touched puede traer rutas absolutas para archivos fuera del proyecto (p.
    ej. un scratch file bajo el home del usuario) — eso filtra el username. Solo las entradas
    relativas salen; las descartadas se cuentan en files_outside."""
    all_files = s.get("files_touched") or []
    kept = [f for f in all_files if isinstance(f, str) and not os.path.isabs(f) and not f.startswith("~")]
    source_tokens = s.get("tokens") if isinstance(s.get("tokens"), dict) else {}
    tokens = {k: source_tokens.get(k, 0) for k in _DETAIL_TOKEN_FIELDS}
    row = {"project": s.get("project"), "started": s.get("started"), "ended": s.get("ended"),
           "duration_s": s.get("duration_s"), "turns": s.get("turns"), "commits": s.get("commits"),
           "branch": s.get("branch"), "files_touched": kept, "files_outside": len(all_files) - len(kept),
           "agents": s.get("agents") or {}, "skills": s.get("skills") or {},
           "tokens": tokens, "subagents": s.get("subagents", 0)}
    if titles:
        row["title"] = s.get("title")
    return row


def export_activity(cfg, projects=None, detail=False, titles=False):
    """R9/P1: agregado por proyecto por default; detail=True agrega filas por sesión; titles=True
    requiere detail=True (error de uso si no, nunca un flag ignorado en silencio). cwd y
    source_path (más mtime/size/offset) nunca salen de acá — _strip_local_only corre sobre CADA
    fila, agregada o por sesión, justo antes de devolverla."""
    if titles and not detail:
        raise ValueError("--titles requires --detail")
    from . import sessions
    sessions.refresh(cfg)   # this is a CLI call, not a request thread: refresh the registry
    items = sessions.load(cfg)
    if projects:
        want = {p.lower() for p in projects}
        items = [s for s in items if (s.get("project") or "").lower() in want]
    agg = {}
    for s in items:
        p = s.get("project") or "unknown"
        a = agg.setdefault(p, {"project": p, "sessions": 0, "hours": 0.0, "tokens": {"in": 0, "out": 0},
                               "commits": 0, "files_touched": 0, "tool_calls": {}, "agents": {}, "skills": {}})
        a["sessions"] += 1
        a["hours"] += (s.get("duration_s") or 0) / 3600.0
        a["tokens"]["in"] += (s.get("tokens") or {}).get("in", 0)
        a["tokens"]["out"] += (s.get("tokens") or {}).get("out", 0)
        a["commits"] += s.get("commits", 0)
        a["files_touched"] += len(s.get("files_touched") or [])
        for k, v in (s.get("tool_calls") or {}).items(): a["tool_calls"][k] = a["tool_calls"].get(k, 0) + v
        for k, v in (s.get("agents") or {}).items(): a["agents"][k] = a["agents"].get(k, 0) + v
        for k, v in (s.get("skills") or {}).items(): a["skills"][k] = a["skills"].get(k, 0) + v
    aggregated = []
    for p in sorted(agg):
        a = agg[p]; a["hours"] = round(a["hours"], 2)
        aggregated.append(_strip_local_only(a))
    out = {"aggregated": aggregated}
    if detail:
        out["sessions"] = [_strip_local_only(_detail_row(s, titles)) for s in items]
    return out


def export(cfg, activity=None):
    data = scan.ensure(cfg)
    R = Roster(cfg, data); rows, items = R.load(refresh_usage=False)
    # critical/warnings (why the contract flags it) and desc (frontmatter description, truncated
    # to 300 chars — never the prompt body) travel to other machines via hub so a teammate can
    # see WHY an agent is invalid without a filesystem path, which stays local-only (like cwd).
    agents = [{"name": r.name, "project": p, "tool": t, "category": r.category, "model": r.fields.get("model", ""),
               "uses": items.get(r.name, {}).get("n_total", 0), "critical": r.critical, "warnings": r.warnings,
               "desc": r.fields.get("description", "")[:300]} for p, r, path, t in rows if r.is_agent]
    sk = [{"name": s["name"], "project": s["project"], "state": s["state"], "symlink": s["symlink"]} for s in SK.load(cfg, data)]
    hs = [{"project": e["name"], "level": e["level"], "hooks_dead": e["hooks_dead"], "hooks_broken": e["hooks_broken"]} for e in HAR.states(data)]
    # projects_detail: per-project fields from projects.load(), whitelisted to _PROJECT_DETAIL_FIELDS —
    # "path" (local-only, like cwd/source_path above) never leaves this machine.
    pd = [{k: p[k] for k in _PROJECT_DETAIL_FIELDS} for p in PROJ.load(data)]
    out = {"cabina": 1, "machine": socket.gethostname(), "os": platform.system(), "when": datetime.now().isoformat(timespec="minutes"),
           "agents": agents, "skills": sk, "harness": hs, "projects": sorted(p["name"] for p in data.get("projects", [])),
           "projects_detail": pd}
    if activity is not None:
        out["activity"] = activity
    return out


def _key(x): return f'{x.get("tool", "claude")}:{x["project"]}/{x["name"]}'


def compare(a, b):
    ka = {_key(x): x for x in a.get("agents", [])}; kb = {_key(x): x for x in b.get("agents", [])}
    sa = {_key(x) for x in a.get("skills", [])}; sb = {_key(x) for x in b.get("skills", [])}
    pa, pb = set(a.get("projects", [])), set(b.get("projects", []))
    out = {
        "a": a.get("machine"), "b": b.get("machine"),
        "agents": {"only_a": sorted(set(ka) - set(kb)), "only_b": sorted(set(kb) - set(ka)),
                   "state_differs": [{"agent": k, "a": ka[k]["category"], "b": kb[k]["category"]} for k in sorted(set(ka) & set(kb)) if ka[k]["category"] != kb[k]["category"]]},
        "skills": {"only_a": sorted(sa - sb), "only_b": sorted(sb - sa)},
        "projects": {"only_a": sorted(pa - pb), "only_b": sorted(pb - pa)},
    }
    # P4: activity deltas only when BOTH exports carry aggregated activity — a missing side
    # (a machine that ran `cabina export` without --activity) means "say nothing", never a
    # false delta from assumed zeros.
    aa, ab = (a.get("activity") or {}).get("aggregated"), (b.get("activity") or {}).get("aggregated")
    if aa and ab:
        pa2 = {x["project"]: x for x in aa}; pb2 = {x["project"]: x for x in ab}
        out["activity"] = [{"project": p,
                            "sessions": {"a": pa2.get(p, {}).get("sessions", 0), "b": pb2.get(p, {}).get("sessions", 0)},
                            "hours": {"a": pa2.get(p, {}).get("hours", 0), "b": pb2.get(p, {}).get("hours", 0)},
                            "commits": {"a": pa2.get(p, {}).get("commits", 0), "b": pb2.get(p, {}).get("commits", 0)}}
                           for p in sorted(set(pa2) | set(pb2))]
    return out


def render_compare(r, la=None, lb=None):
    la = la or r.get("a") or "A"; lb = lb or r.get("b") or "B"
    out = [f"cabina compare  {la}  vs  {lb}"]
    def sec(title, only_a, only_b):
        out.append(f"  {title}: {len(only_a)} only in {la} · {len(only_b)} only in {lb}")
        for x in only_a[:15]: out.append(f"     {la:<12} {x}")
        for x in only_b[:15]: out.append(f"     {lb:<12} {x}")
    sec("agents", r["agents"]["only_a"], r["agents"]["only_b"])
    for x in r["agents"]["state_differs"]: out.append(f"     state differs  {x['agent']}: {la}={x['a']}  {lb}={x['b']}")
    sec("skills", r["skills"]["only_a"], r["skills"]["only_b"])
    sec("projects", r["projects"]["only_a"], r["projects"]["only_b"])
    if r.get("activity"):
        out.append(f"  activity: sessions/hours/commits, {la} → {lb}")
        for x in r["activity"]:
            out.append(f"     {x['project']:<20} sessions {x['sessions']['a']:>3}→{x['sessions']['b']:<3}  "
                       f"hours {x['hours']['a']:.1f}→{x['hours']['b']:.1f}  commits {x['commits']['a']}→{x['commits']['b']}")
    return "\n".join(out)
