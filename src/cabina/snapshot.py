"""`cabina export` / `cabina compare` — one environment as a portable JSON, and the diff between two
(two machines, or the same machine over time). Read-only."""
import json, os, platform, socket
from datetime import datetime
from . import scan, skills as SK, harness as HAR
from .roster import Roster

_LOCAL_ONLY_FIELDS = ("cwd", "source_path", "mtime", "size", "offset")


def _strip_local_only(row):
    """R9 (cwd/source_path) + P1 (también mtime/size/offset): campos que nunca deben salir de
    esta máquina, sin importar cómo se haya construido la fila. Se aplica en el límite mismo de
    la exportación — no confía en que quien construye la fila nunca los vuelva a agregar."""
    return {k: v for k, v in row.items() if k not in _LOCAL_ONLY_FIELDS}


def _detail_row(s, titles):
    """Una fila de `export --activity --detail`, como lista blanca explícita a partir de un
    resumen de sesión completo `s` (que SÍ trae cwd/source_path/mtime/size/offset — sessions.py
    los guarda solo localmente, no para exportar). titles=True agrega el título."""
    row = {"project": s.get("project"), "started": s.get("started"), "ended": s.get("ended"),
           "duration_s": s.get("duration_s"), "turns": s.get("turns"), "commits": s.get("commits"),
           "branch": s.get("branch"), "files_touched": s.get("files_touched") or [],
           "agents": s.get("agents") or {}, "skills": s.get("skills") or {},
           "tokens": s.get("tokens") or {"in": 0, "out": 0}, "subagents": s.get("subagents", 0)}
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


def export(cfg):
    data = scan.ensure(cfg)
    R = Roster(cfg, data); rows, items = R.load(refresh_usage=False)
    agents = [{"name": r.name, "project": p, "tool": t, "category": r.category, "model": r.fields.get("model", ""),
               "uses": items.get(r.name, {}).get("n_total", 0)} for p, r, path, t in rows if r.is_agent]
    sk = [{"name": s["name"], "project": s["project"], "state": s["state"], "symlink": s["symlink"]} for s in SK.load(cfg, data)]
    hs = [{"project": e["name"], "level": e["level"], "hooks_dead": e["hooks_dead"], "hooks_broken": e["hooks_broken"]} for e in HAR.states(data)]
    return {"cabina": 1, "machine": socket.gethostname(), "os": platform.system(), "when": datetime.now().isoformat(timespec="minutes"),
            "agents": agents, "skills": sk, "harness": hs, "projects": sorted(p["name"] for p in data.get("projects", []))}


def _key(x): return f'{x.get("tool", "claude")}:{x["project"]}/{x["name"]}'


def compare(a, b):
    ka = {_key(x): x for x in a.get("agents", [])}; kb = {_key(x): x for x in b.get("agents", [])}
    sa = {_key(x) for x in a.get("skills", [])}; sb = {_key(x) for x in b.get("skills", [])}
    pa, pb = set(a.get("projects", [])), set(b.get("projects", []))
    return {
        "a": a.get("machine"), "b": b.get("machine"),
        "agents": {"only_a": sorted(set(ka) - set(kb)), "only_b": sorted(set(kb) - set(ka)),
                   "state_differs": [{"agent": k, "a": ka[k]["category"], "b": kb[k]["category"]} for k in sorted(set(ka) & set(kb)) if ka[k]["category"] != kb[k]["category"]]},
        "skills": {"only_a": sorted(sa - sb), "only_b": sorted(sb - sa)},
        "projects": {"only_a": sorted(pa - pb), "only_b": sorted(pb - pa)},
    }


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
    return "\n".join(out)
