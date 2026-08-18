import json, os, subprocess, sys, unittest, tempfile
import _helpers  # noqa
from _env import Env
from cabina import scan, mcp as MCP, config as CFG

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
        self.assertEqual(r["result"]["serverInfo"]["name"], "cabina"); self.assertIn("READ-ONLY", r["result"]["instructions"])
        self.assertIsNone(self.srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = {t["name"] for t in self.srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertEqual(names, {"cabina_health", "cabina_working", "cabina_agent", "cabina_agents", "cabina_references", "cabina_project", "cabina_drift"})
    def test_health_and_working(self):
        h = self.call("cabina_health"); self.assertIn("critical", h); self.assertIsInstance(h["findings"], list)
        w = self.call("cabina_working"); self.assertEqual(w["provider"], "none"); self.assertEqual(w["working"], [])
    def test_agent_and_agents(self):
        a = self.call("cabina_agent", name="reviewer"); self.assertTrue(a["found"]); self.assertEqual({i["tool"] for i in a["instances"]}, {"claude", "codex"})
        self.assertFalse(self.call("cabina_agent", name="nope")["found"])
        l = self.call("cabina_agents", project="alpha", category="document"); self.assertEqual([x["name"] for x in l["agents"]], ["guide"])
    def test_references_project_drift(self):
        self.assertIn("count", self.call("cabina_references", name="reviewer"))
        p = self.call("cabina_project", name="alpha"); self.assertTrue(p["found"]); self.assertEqual(p["harness"]["hooks_dead"], ["dead.sh"])
        d = self.call("cabina_drift"); self.assertEqual(d["twins"][0]["status"], "same")
    def test_unknown_tool_and_method(self):
        r = self.srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "cabina_delete_everything", "arguments": {}}})
        self.assertTrue(r["result"]["isError"])
        r = self.srv.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"}); self.assertEqual(r["error"]["code"], -32601)
    def test_no_write_tools_exposed(self):
        for t in MCP.tools_spec():
            self.assertNotRegex(t["name"], r"(archive|delete|write|create|save|commit|edit|remove)")
        # and the server has no handler that could write: every t_* method name is a read
        self.assertFalse([m for m in dir(MCP.Server) if m.startswith("t_") and any(k in m for k in ("archive", "delete", "write", "create", "save", "commit"))])

class TestMcpSubprocess(unittest.TestCase):
    def test_stdio_roundtrip(self):
        env = Env(); scan.save(env.cfg, scan.run(env.cfg))
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(f'claude_home = "{env.claude}"\ncodex_home = "{env.codex}"\nroots = ["{env.projects}"]\nstate_dir = "{env.state}"\n[live]\nprovider = "none"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n')
            cfgp = f.name
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        p = subprocess.Popen([sys.executable, "-m", "cabina", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             env={**os.environ, "PYTHONPATH": src, "CABINA_CONFIG": cfgp})
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "cabina_working", "arguments": {}}}]
        out, _ = p.communicate("\n".join(json.dumps(m) for m in msgs) + "\n", timeout=60)
        lines = [json.loads(l) for l in out.strip().splitlines()]
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "cabina")
        self.assertIn("working", json.loads(lines[1]["result"]["content"][0]["text"]))
        os.unlink(cfgp); env.cleanup()
if __name__ == "__main__": unittest.main()
