"""`cabina export` / `cabina compare` — one environment as a portable JSON, and the diff between two
(two machines, or the same machine over time). Read-only."""
import json, os, platform, socket
from datetime import datetime
from . import scan, skills as SK, harness as HAR
from .roster import Roster


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
