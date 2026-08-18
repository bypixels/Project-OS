"""Live view of running agents. Pluggable providers; degrades to 'none' gracefully.
A provider returns {"ok": bool, "agents": [...], "workspaces": [...]} with each agent as
{"agent","status","workspace","cwd","task","pane","focused"} and status in working|done|idle|unknown."""
import json, os, shutil
from . import host


class NoneProvider:
    name = "none"
    def available(self): return True
    def list(self): return {"ok": False, "reason": "no live provider configured", "agents": [], "workspaces": []}
    def focus(self, pane): return False, "no live provider"


class HerdrProvider:
    """herdr — terminal workspace manager for AI coding agents (https://herdr.dev)."""
    name = "herdr"

    def available(self):
        return shutil.which("herdr") is not None

    def _call(self, *a):
        try:
            return json.loads(host.run(["herdr", *a], timeout=10)).get("result", {})
        except Exception:
            return None

    def list(self):
        ag = self._call("agent", "list"); ws = self._call("workspace", "list")
        if ag is None or ws is None:
            return {"ok": False, "reason": "herdr not responding", "agents": [], "workspaces": []}
        spaces = {w["workspace_id"]: w for w in ws.get("workspaces", [])}
        out = []
        for a in ag.get("agents", []):
            w = spaces.get(a["workspace_id"], {})
            t = (a.get("terminal_title_stripped") or "").strip()
            lbl = w.get("label", "?")
            if t.lower() in ("claude code", lbl.lower()):
                t = ""
            out.append({"agent": a["agent"], "status": a.get("agent_status", "unknown"), "workspace": lbl,
                        "cwd": a.get("foreground_cwd") or a.get("cwd") or "", "task": t,
                        "pane": a["pane_id"], "focused": a.get("focused", False)})
        order = {"working": 0, "done": 1, "idle": 2}
        out.sort(key=lambda x: (order.get(x["status"], 9), x["workspace"]))
        return {"ok": True, "agents": out,
                "workspaces": [{"id": k, "label": v["label"], "tabs": v.get("tab_count", 0)} for k, v in spaces.items()]}

    def focus(self, pane):
        ok = bool(host.run(["herdr", "agent", "focus", pane]))
        return ok, "focused" if ok else "herdr did not respond"


def get(cfg):
    want = (cfg.get("live") or {}).get("provider", "auto")
    if want in ("auto", "herdr"):
        p = HerdrProvider()
        if p.available() or want == "herdr":
            return p
    return NoneProvider()


def working_projects(provider, roots):
    """Project names (from roots {name: abs_root}, excluding 'global') with a 'working' agent."""
    data = provider.list()
    rr = {k: os.path.realpath(v) for k, v in roots.items() if k != "global"}
    out = set()
    for a in data.get("agents", []):
        if a.get("status") != "working":
            continue
        cwd = os.path.realpath(a.get("cwd") or "")
        for name, r in rr.items():
            if cwd == r or cwd.startswith(r + os.sep):
                out.add(name)
    # collapse nested projects into their parent (Webs/actanova/apps/api -> actanova)
    return sorted({next((o for o, orr in rr.items() if o != n and rr[n].startswith(orr + os.sep)), n) for n in out})
