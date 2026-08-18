import json, os, threading, unittest, urllib.request
import _helpers  # noqa
from _env import Env
from cabina import server, scan
from http.server import ThreadingHTTPServer

class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env(); scan.save(cls.env.cfg, scan.run(cls.env.cfg))
        cls.app = server.App(cls.env.cfg)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cls.app))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.env.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r: return json.loads(r.read())
    def post(self, path, body, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Cabina-Token": token if token is not None else self.app.token})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read())

    def test_index_has_token_and_lang(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn(self.app.token, html); self.assertIn('lang="en"', html)
    def test_agents_with_attribution(self):
        d = self.get("/api/agents"); by = {(a["project"], a["name"]): a for a in d["agents"]}
        self.assertEqual(by[("alpha", "reviewer")]["uses_here"], 2)      # cwd attribution
        self.assertEqual(by[("alpha", "reviewer")]["uses"], 3)           # total by name
        self.assertTrue(by[("alpha", "reviewer")]["attributed"])
        self.assertEqual(by[("alpha", "guide")]["category"], "document")
        self.assertTrue(any("overrides" in w for w in by[("alpha", "reviewer")]["warnings"]))  # shadows global undeclared
    def test_skills_projects_harness_docs_live(self):
        s = self.get("/api/skills"); self.assertEqual({x["name"] for x in s["skills"]}, {"gsk", "deploy"})
        self.assertEqual(next(x for x in s["skills"] if x["name"] == "deploy")["uses"], 1)
        p = self.get("/api/projects"); self.assertEqual(p["projects"][0]["name"], "alpha")
        h = self.get("/api/harness"); self.assertEqual(h["states"][0]["hooks_dead"], ["dead.sh"])
        d = self.get("/api/docs"); self.assertTrue(any(x["rel"] == ".claude/MEMORY.md" for x in d["docs"]))
        l = self.get("/api/live"); self.assertFalse(l["ok"]); self.assertEqual(l["provider"], "none")
    def test_post_requires_token(self):
        code, _ = self.post("/api/open", {"path": "/tmp"}, token="wrong"); self.assertEqual(code, 403)
        code, _ = self.post("/api/open", {"path": "/tmp"}, token=""); self.assertEqual(code, 403)
    def test_create_then_archive_agent(self):
        code, r = self.post("/api/create", {"project": "alpha", "name": "new-one", "description": "Does new things well", "model": "sonnet", "tools": "Read", "body": "You are new."})
        self.assertTrue(r["ok"], r); self.assertTrue(os.path.isfile(os.path.join(self.env.alpha, ".claude", "agents", "new-one.md")))
        code, r = self.post("/api/create", {"project": "alpha", "name": "Bad Name", "description": "x", "model": "sonnet", "tools": "Read", "body": "y"})
        self.assertFalse(r["ok"])                                        # contract blocks creation
        code, r = self.post("/api/archive", {"name": "new-one", "project": "alpha"})
        self.assertTrue(r["ok"], r); self.assertFalse(os.path.exists(os.path.join(self.env.alpha, ".claude", "agents", "new-one.md")))
    def test_doc_read_save_conflict(self):
        d = self.get("/api/doc?project=alpha&rel=CLAUDE.md"); self.assertTrue(d["ok"])
        code, r = self.post("/api/save-doc", {"project": "alpha", "rel": "CLAUDE.md", "content": "# alpha 2\n", "hash": d["hash"]}); self.assertTrue(r["ok"], r)
        code, r = self.post("/api/save-doc", {"project": "alpha", "rel": "CLAUDE.md", "content": "# stale\n", "hash": d["hash"]}); self.assertFalse(r["ok"]); self.assertTrue(r["conflict"])
        code, r = self.post("/api/save-doc", {"project": "alpha", "rel": "../../x.md", "content": "x", "hash": "0" * 16}); self.assertFalse(r["ok"])
    def test_unknown_routes(self):
        with self.assertRaises(urllib.error.HTTPError): self.get("/api/nope")
        code, _ = self.post("/api/nope", {}); self.assertEqual(code, 404)
if __name__ == "__main__": unittest.main()
