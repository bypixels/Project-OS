"""`cabina mcp` — a READ-ONLY MCP server over stdio, so Claude Code and Codex can ask the
control plane before acting: is anyone working in project X? does this agent meet the contract?
who references Y? Nothing here writes. Newline-delimited JSON-RPC 2.0, stdlib only.
"""
import os, sys, json
from . import scan, check as CHECK, live as LIVE, drift as DR, projects as PROJ, harness as HAR, usage
from .roster import Roster

PROTOCOL = "2024-11-05"


def tools_spec():
    S = lambda **p: {"type": "object", "properties": p, "additionalProperties": False}
    return [
        {"name": "cabina_health", "description": "Health of the Claude Code / Codex environment: findings by severity (critical/warning/info) with titles and fixes. Read-only.",
         "inputSchema": S(quick={"type": "boolean", "description": "skip slow detectors (default true)"})},
        {"name": "cabina_working", "description": "Projects that have an AI agent WORKING RIGHT NOW (from the live provider). Ask before editing shared files (MEMORY.md, CLAUDE.md) in a project.",
         "inputSchema": S()},
        {"name": "cabina_agent", "description": "Contract state and real usage of one agent by name (all projects/tools where it exists).",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}},
        {"name": "cabina_agents", "description": "List agents. Optional filters: project, tool (claude|codex), category (valid|warnings|invalid|document).",
         "inputSchema": S(project={"type": "string"}, tool={"type": "string"}, category={"type": "string"})},
        {"name": "cabina_references", "description": "Files that reference an agent or skill by name (before archiving or renaming it).",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}},
        {"name": "cabina_project", "description": "Status of one project: branch, uncommitted changes, assets, harness level, dead hooks, MEMORY.md age, worktrees.",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}},
        {"name": "cabina_drift", "description": "Drift between Claude Code and Codex: twin agents that diverged, CLAUDE.md vs AGENTS.md per project, copied skills.",
         "inputSchema": S()},
    ]


class Server:
    def __init__(self, cfg):
        self.cfg = cfg
        self.data = scan.ensure(cfg)
        self.live = LIVE.get(cfg)
        self._roster = None

    def roster(self):
        if self._roster is None:
            self._roster = Roster(self.cfg, self.data)
            self._rows, self._items = self._roster.load(refresh_usage=False)
        return self._roster, self._rows, self._items

    # ---- tools ----
    def t_health(self, quick=True, **_):
        F = CHECK.run(self.cfg, quick=quick)
        return {"critical": sum(1 for f in F if f["sev"] == "crit"), "warnings": sum(1 for f in F if f["sev"] == "warn"),
                "info": sum(1 for f in F if f["sev"] == "info"), "findings": [{"severity": f["sev"], "title": f["title"], "fix": f["fix"]} for f in F]}

    def t_working(self, **_):
        roots = scan.project_roots(self.cfg, self.data)
        w = LIVE.working_projects(self.live, roots)
        return {"provider": self.live.name, "working": w,
                "advice": "coordinate before editing shared files in these projects" if w else "no agent is working right now"}

    def t_agent(self, name, **_):
        R, rows, items = self.roster()
        hits = [(p, r, path, t) for p, r, path, t in rows if r.name == name]
        if not hits:
            return {"found": False, "name": name}
        return {"found": True, "name": name, "instances": [
            {"project": p, "tool": t, "category": r.category, "path": path, "model": r.fields.get("model", ""),
             "critical": r.critical, "warnings": r.warnings, "usage": usage.for_agent(items, r.name, p) if t == "claude" else "not measurable for codex"} for p, r, path, t in hits]}

    def t_agents(self, project=None, tool=None, category=None, **_):
        R, rows, items = self.roster()
        out = []
        for p, r, path, t in rows:
            if project and p.lower() != project.lower(): continue
            if tool and t != tool: continue
            if category and r.category != category: continue
            out.append({"name": r.name, "project": p, "tool": t, "category": r.category, "uses": items.get(r.name, {}).get("n_total", 0) if t == "claude" else None})
        return {"count": len(out), "agents": out}

    def t_references(self, name, **_):
        R, _, _ = self.roster()
        refs = R.references(name)
        return {"name": name, "count": len(refs), "files": refs, "note": "matches are by name; a homonym in another project also matches"}

    def t_project(self, name, **_):
        ps = [p for p in PROJ.load(self.data) if p["name"].lower() == name.lower()]
        if not ps:
            return {"found": False, "name": name}
        p = ps[0]; h = next((e for e in HAR.states(self.data) if e["name"] == p["name"]), None)
        return {"found": True, **p, "harness": {"level": h["level"], "hooks_dead": h["hooks_dead"], "hooks_broken": h["hooks_broken"], "missing": h["missing"]} if h else None}

    def t_drift(self, **_):
        return DR.report(self.cfg, self.data)

    # ---- JSON-RPC ----
    def handle(self, msg):
        m, i, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if m == "initialize":
            return self._ok(i, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                                "serverInfo": {"name": "cabina", "version": __import__("cabina").__version__},
                                "instructions": "cabina is READ-ONLY. Ask cabina_working before editing MEMORY.md/CLAUDE.md in a project; ask cabina_agent before creating an agent with an existing name; ask cabina_references before archiving anything."})
        if m == "notifications/initialized" or m is None and i is None:
            return None
        if m == "ping":
            return self._ok(i, {})
        if m == "tools/list":
            return self._ok(i, {"tools": tools_spec()})
        if m == "tools/call":
            name = params.get("name", ""); args = params.get("arguments") or {}
            fn = {"cabina_health": self.t_health, "cabina_working": self.t_working, "cabina_agent": self.t_agent,
                  "cabina_agents": self.t_agents, "cabina_references": self.t_references, "cabina_project": self.t_project,
                  "cabina_drift": self.t_drift}.get(name)
            if not fn:
                return self._ok(i, {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True})
            try:
                res = fn(**args)
                return self._ok(i, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}]})
            except TypeError as e:
                return self._ok(i, {"content": [{"type": "text", "text": f"bad arguments: {e}"}], "isError": True})
            except Exception as e:
                return self._ok(i, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
        if i is not None:
            return {"jsonrpc": "2.0", "id": i, "error": {"code": -32601, "message": f"method not found: {m}"}}
        return None

    @staticmethod
    def _ok(i, result):
        return {"jsonrpc": "2.0", "id": i, "result": result}


def serve(cfg, inp=None, out=None):
    inp = inp or sys.stdin; out = out or sys.stdout
    srv = Server(cfg)
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n"); out.flush(); continue
        resp = srv.handle(msg)
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n"); out.flush()


def install_snippets(cmd="cabina"):
    return {
        "claude_code": f"claude mcp add cabina -s user -- {cmd} mcp",
        "codex_toml": f'[mcp_servers.cabina]\ncommand = "{cmd}"\nargs = ["mcp"]\n',
        "generic_json": {"mcpServers": {"cabina": {"command": cmd, "args": ["mcp"]}}},
    }
