import json, os, subprocess, sys, unittest, tempfile
import _helpers  # noqa
from _env import Env
from project_os import scan, mcp as MCP, config as CFG

class TestMcpInProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env(); scan.save(cls.env.cfg, scan.run(cls.env.cfg)); cls.srv = MCP.Server(cls.env.cfg)
    @classmethod
    def tearDownClass(cls): cls.env.cleanup()
    def call(self, _tool, **args):
        r = self.srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": _tool, "arguments": args}})
        self.assertFalse(r["result"].get("isError"), r); return json.loads(r["result"]["content"][0]["text"])
    def test_initialize_and_list(self):
        r = self.srv.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "project-os"); self.assertIn("READ-ONLY", r["result"]["instructions"])
        self.assertIsNone(self.srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = {t["name"] for t in self.srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertEqual(names, {"project_os_health", "project_os_working", "project_os_agent", "project_os_agents", "project_os_references", "project_os_project", "project_os_drift", "project_os_activity"})
    def test_health_and_working(self):
        h = self.call("project_os_health"); self.assertIn("critical", h); self.assertIsInstance(h["findings"], list)
        w = self.call("project_os_working"); self.assertEqual(w["provider"], "none"); self.assertEqual(w["working"], [])
    def test_agent_and_agents(self):
        a = self.call("project_os_agent", name="reviewer"); self.assertTrue(a["found"]); self.assertEqual({i["tool"] for i in a["instances"]}, {"claude", "codex"})
        self.assertFalse(self.call("project_os_agent", name="nope")["found"])
        l = self.call("project_os_agents", project="alpha", category="document"); self.assertEqual([x["name"] for x in l["agents"]], ["guide"])
    def test_references_project_drift(self):
        self.assertIn("count", self.call("project_os_references", name="reviewer"))
        p = self.call("project_os_project", name="alpha"); self.assertTrue(p["found"]); self.assertEqual(p["harness"]["hooks_dead"], ["dead.sh"])
        d = self.call("project_os_drift"); self.assertEqual(d["twins"][0]["status"], "same")
    def test_activity_tool_requires_project_and_hides_titles_paths(self):
        from project_os import sessions as SESS
        SESS.refresh(self.env.cfg)
        r = self.call("project_os_activity", project="alpha")
        self.assertEqual(r["project"], "alpha")
        self.assertGreaterEqual(r["aggregate"]["sessions"], 1)
        dumped = json.dumps(r)
        self.assertNotIn("title", dumped); self.assertNotIn("source_path", dumped); self.assertNotIn('"cwd"', dumped)
        resp = self.srv.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "project_os_activity", "arguments": {}}})
        self.assertTrue(resp["result"]["isError"])                # project omitted -> bad arguments

    def test_unknown_tool_and_method(self):
        r = self.srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "project_os_delete_everything", "arguments": {}}})
        self.assertTrue(r["result"]["isError"])
        r = self.srv.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"}); self.assertEqual(r["error"]["code"], -32601)
    def test_no_write_tools_exposed(self):
        for t in MCP.tools_spec():
            self.assertNotRegex(t["name"], r"(archive|delete|write|create|save|commit|edit|remove)")
        # and the server has no handler that could write: every t_* method name is a read
        self.assertFalse([m for m in dir(MCP.Server) if m.startswith("t_") and any(k in m for k in ("archive", "delete", "write", "create", "save", "commit"))])

class TestMcpRosterFreshness(unittest.TestCase):
    """The stdio MCP server lives for a whole Claude Code session (unlike server.py's
    per-request HTTP handler), so a Roster snapshot cached forever in __init__ would answer
    project_os_agent/project_os_agents/etc with stale data for the entire session. Mirrors server.py's
    App.roster() 30s TTL."""
    def setUp(self):
        self.env = Env(); scan.save(self.env.cfg, scan.run(self.env.cfg)); self.srv = MCP.Server(self.env.cfg)
    def tearDown(self):
        self.env.cleanup()

    def call(self, _tool, **args):
        r = self.srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": _tool, "arguments": args}})
        self.assertFalse(r["result"].get("isError"), r); return json.loads(r["result"]["content"][0]["text"])

    def test_agents_tool_picks_up_new_agent_after_rescan(self):
        from _env import AGENT
        names1 = {a["name"] for a in self.call("project_os_agents", project="alpha")["agents"]}
        self.assertNotIn("newagent", names1)
        agents_dir = os.path.join(self.env.alpha, ".claude", "agents")
        open(os.path.join(agents_dir, "newagent.md"), "w").write(AGENT.format(n="newagent"))
        scan.save(self.env.cfg, scan.run(self.env.cfg))   # cache now reflects the new agent
        self.srv._t = 0                                    # force the TTL to be expired
        names2 = {a["name"] for a in self.call("project_os_agents", project="alpha")["agents"]}
        self.assertIn("newagent", names2)


class TestMcpSubprocess(unittest.TestCase):
    def test_stdio_roundtrip(self):
        env = Env(); scan.save(env.cfg, scan.run(env.cfg))
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
            cfgp = f.name
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        p = subprocess.Popen([sys.executable, "-m", "project_os", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             env={**os.environ, "PYTHONPATH": src, "PROJECT_OS_CONFIG": cfgp})
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "project_os_working", "arguments": {}}}]
        out, _ = p.communicate("\n".join(json.dumps(m) for m in msgs) + "\n", timeout=60)
        lines = [json.loads(l) for l in out.strip().splitlines()]
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "project-os")
        self.assertIn("working", json.loads(lines[1]["result"]["content"][0]["text"]))
        os.unlink(cfgp); env.cleanup()
if __name__ == "__main__": unittest.main()
