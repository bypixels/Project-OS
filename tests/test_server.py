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
    def test_index_marks_hub_false(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertNotIn("__HUB__", html)
        self.assertIn('HUB="0"==="1"', html)
    def test_index_has_activity_tab(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn('"activity"', html); self.assertIn("/api/activity", html)
    def test_agents_with_attribution(self):
        d = self.get("/api/agents"); by = {(a["project"], a["name"]): a for a in d["agents"]}
        self.assertEqual(by[("alpha", "reviewer")]["uses_here"], 2)      # cwd attribution
        self.assertEqual(by[("alpha", "reviewer")]["uses"], 3)           # total by name
        self.assertTrue(by[("alpha", "reviewer")]["attributed"])
        self.assertEqual(by[("alpha", "guide")]["category"], "document")
        self.assertTrue(any("overrides" in w for w in by[("alpha", "reviewer")]["warnings"]))  # shadows global undeclared
        self.assertEqual({a["tool"] for a in d["agents"]}, {"claude", "codex"})
        self.assertTrue(d["codex_present"])
    def test_skills_projects_harness_docs_live(self):
        s = self.get("/api/skills"); self.assertEqual({(x["name"], x["tool"]) for x in s["skills"]}, {("gsk", "claude"), ("deploy", "claude"), ("gsk", "codex")})
        self.assertEqual(next(x for x in s["skills"] if x["name"] == "deploy")["uses"], 1)
        p = self.get("/api/projects"); self.assertEqual(p["projects"][0]["name"], "alpha")
        h = self.get("/api/harness"); self.assertEqual(h["states"][0]["hooks_dead"], ["dead.sh"])
        self.assertEqual(h["drift"]["twins"][0]["status"], "same")                       # reviewer.md ≡ reviewer.toml
        self.assertEqual({x["project"]: x["status"] for x in h["drift"]["rules"]}, {"alpha": "diverged"})
        d = self.get("/api/docs"); self.assertTrue(any(x["rel"] == ".claude/MEMORY.md" for x in d["docs"]))
        l = self.get("/api/live"); self.assertFalse(l["ok"]); self.assertEqual(l["provider"], "none")
    def test_activity_endpoint_serves_cache(self):
        from cabina import sessions as SESS
        SESS.refresh(self.env.cfg)                      # populate the cache once, synchronously, for the test
        d = self.get("/api/activity?days=30")
        self.assertTrue(any(s["project"] == "alpha" for s in d["sessions"]))
        self.assertIn("active_seconds", d)
        d2 = self.get("/api/activity?project=alpha&days=30")
        self.assertTrue(d2["sessions"]); self.assertTrue(all(s["project"] == "alpha" for s in d2["sessions"]))
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
    def test_commit_endpoint_requires_repo_and_only_that_path(self):
        import subprocess
        a = self.env.alpha
        subprocess.run(["git", "init", "-q", a], check=True)
        subprocess.run(["git", "-C", a, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        r = self.get("/api/in-repo?path=" + os.path.join(a, "CLAUDE.md")); self.assertTrue(r["in_repo"])
        d = self.get("/api/doc?project=alpha&rel=CLAUDE.md")
        self.post("/api/save-doc", {"project": "alpha", "rel": "CLAUDE.md", "content": "# alpha 3\n", "hash": d["hash"]})
        code, r = self.post("/api/commit", {"path": os.path.join(a, "CLAUDE.md"), "message": "cabina: edit CLAUDE.md"})
        self.assertTrue(r["ok"], r)
        files = subprocess.run(["git", "-C", a, "show", "--name-only", "--format=", "HEAD"], capture_output=True, text=True).stdout.split()
        self.assertEqual(files, ["CLAUDE.md"])          # AGENTS.md, .claude/... untouched by the commit
        code, r = self.post("/api/commit", {"path": "/tmp/nowhere.md", "message": "x"}); self.assertFalse(r["ok"])
    def test_hub_mode_hides_live_docs_and_write_buttons(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn('["agents","skills","projects","harness","activity"]', html)   # hub-mode VIEWS, sin live/docs
        self.assertIn('HUB?"":', html)                                               # al menos un control de escritura condicionado
    def test_hub_mode_hides_remaining_write_buttons_and_has_machine_chip(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function mchip", html)
        self.assertIn("function renderHubBanner", html)
    def test_activity_supports_aggregated_shape(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function renderActivityAggregated", html)
    def test_activity_and_hub_fields_always_escaped(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        import re
        start = html.index("// ---------- ACTIVITY ----------")
        end = html.index("// ---------- PROJECTS ----------")
        body = html[start:end]
        pattern = re.compile(r"\$\{([^{}]*\bx\.(?:title|project|machine|branch)\b[^{}]*)\}")
        hits = list(pattern.finditer(body))
        self.assertGreater(len(hits), 0)                    # sanity: the section actually interpolates these fields
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
    def test_hub_banner_and_projects_fields_always_escaped(self):
        # Orchestrator amendment to Tarea 38: the ACTIVITY-only scan above misses renderHubBanner
        # and mchip() (both defined before the ACTIVITY marker) and renderProjects (defined after
        # the PROJECTS marker) — scan those three spots too so every export-sourced field they
        # interpolate (machine chip, hub banner file name/machine/status, project branch) is
        # checked. Scoped tightly to just those three (not the whole file): other functions in
        # between (e.g. renderArchive) interpolate x.project into a git commit MESSAGE string,
        # never into innerHTML, so they are not an escaping concern and would be a false positive.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        import re
        hub_banner = html[html.index("async function loadHub"):html.index("async function loadLive")]
        mchip = html[html.index("function mchip"):html.index("// ---------- AGENTS ----------")]
        projects = html[html.index("// ---------- PROJECTS ----------"):html.index("// ---------- HARNESS ----------")]
        body = hub_banner + mchip + projects
        pattern = re.compile(r"\$\{([^{}]*\b(?:x\.(?:title|project|machine|branch)|f\.(?:name|machine|status))\b[^{}]*)\}")
        hits = list(pattern.finditer(body))
        self.assertGreater(len(hits), 0)
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
    def test_agent_detail_tolerates_missing_critical_and_warnings(self):
        # E1: hub export rows carry no critical/warnings key the way a live scan's rows do (they
        # do now, but renderAgentDetail must never assume it) — a bare x.critical.length threw
        # TypeError in hub mode. Guard both reads.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("(x.critical||[])", html)
        self.assertIn("(x.warnings||[])", html)
    def test_project_detail_keyed_by_name_and_machine(self):
        # E2: renderProjDetail found a row with `find(y=>y.name===S.sel)` — in hub mode two
        # machines can both have a project called "alpha", so the detail always showed the
        # first one, no matter which row was clicked.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function projKey", html)
        self.assertIn("projKey(y)===S.sel", html)
    def test_unknown_routes(self):
        with self.assertRaises(urllib.error.HTTPError): self.get("/api/nope")
        code, _ = self.post("/api/nope", {}); self.assertEqual(code, 404)
if __name__ == "__main__": unittest.main()
