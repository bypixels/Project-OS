"""Live view of running agents. Pluggable providers; degrades to 'none' gracefully.
A provider returns {"ok": bool, "agents": [...], "workspaces": [...]} with each agent as
{"agent","status","workspace","cwd","task","pane","focused"} and status in working|done|idle|unknown."""
import json, os, re, shutil, time
from . import host, usage


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


class TranscriptProvider:
    """Reads Claude Code's own transcripts to find projects with very recent activity.
    ADDITIVE only (R1): used to extend the 'working' set that blocks doc saves — never
    replaces herdr, never downgrades a herdr 'working' status to idle, and is NOT part of the
    live.get() provider chain (the Live tab's provider selection is unchanged). Looks at BOTH
    the session file and any file under its sibling <sid>/subagents/ dir, so a busy subagent
    alone still counts as 'active'."""
    name = "transcript"

    def __init__(self, cfg):
        self.cfg = cfg

    @staticmethod
    def _peek_cwd(path, limit=40, tail_bytes=65536):
        """The LAST cwd the transcript mentions, not the first: a session can change project
        mid-way (cd into a different repo), and 'active now' must reflect where the user is
        working THIS moment, not where the session started. Reads only the tail of the file
        (bounded, so this stays cheap even for a multi-MB transcript) and returns the last
        match in it. Falls back to scanning the first `limit` lines only if the tail itself
        has no cwd at all (e.g. a transcript smaller than one buffer with a header-only start)."""
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as fh:
                fh.seek(max(0, size - tail_bytes))
                data = fh.read()
            matches = re.findall(r'"cwd":"([^"]+)"', data.decode("utf-8", "replace"))
            if matches:
                return matches[-1]
        except Exception:
            pass
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for _ in range(limit):
                    line = fh.readline()
                    if not line:
                        break
                    m = re.search(r'"cwd":"([^"]+)"', line)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        return None

    def active_projects(self, roots):
        """{project names} with a session or subagent file whose mtime is under
        cfg.live.active_seconds (default 600)."""
        pdir = os.path.join(self.cfg["claude_home"], "projects")
        if not os.path.isdir(pdir):
            return set()
        active = (self.cfg.get("live") or {}).get("active_seconds", 600)
        now = time.time()
        out = set()
        for e in os.listdir(pdir):
            edir = os.path.join(pdir, e)
            if not os.path.isdir(edir):
                continue
            top = [f for f in os.listdir(edir) if f.endswith(".jsonl")]
            if not top:
                continue
            fresh = any(now - os.path.getmtime(os.path.join(edir, f)) < active for f in top)
            if not fresh:
                for name in os.listdir(edir):
                    sub = os.path.join(edir, name, "subagents")
                    if os.path.isdir(sub) and any(
                        f.endswith(".jsonl") and now - os.path.getmtime(os.path.join(sub, f)) < active
                        for f in os.listdir(sub)
                    ):
                        fresh = True
                        break
            if not fresh:
                continue
            newest = max((os.path.join(edir, f) for f in top), key=os.path.getmtime)
            cwd = self._peek_cwd(newest)
            proj = usage._project_of(cwd, roots) if cwd else None
            if proj:
                out.add(proj)
        return out


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
