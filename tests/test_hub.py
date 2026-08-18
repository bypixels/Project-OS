import json, os, tempfile, unittest
import _helpers  # noqa
from _env import Env, sample_export

class TestHubFixtures(unittest.TestCase):
    def test_refresh_sessions_and_sample_export_shape(self):
        env = Env()
        try:
            items = env.refresh_sessions()
            self.assertTrue(any(s["session_id"] == "sess-1" for s in items))
        finally:
            env.cleanup()
        ex = sample_export("mac-mini")
        self.assertEqual(ex["machine"], "mac-mini")
        self.assertEqual(ex["activity"]["aggregated"][0]["project"], "alpha")


class TestHubLoadDir(unittest.TestCase):
    def test_hub_lists_sessions_from_multiple_exports(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "m1.json"), "w").write(json.dumps({"cabina": 1, "machine": "m1", "os": "macOS", "when": "x",
                "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                "activity": {"aggregated": [{"project": "alpha", "sessions": 2, "hours": 1.0}]}}))
            open(os.path.join(d, "m2.json"), "w").write(json.dumps({"cabina": 1, "machine": "m2", "os": "Linux", "when": "y",
                "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                "activity": {"aggregated": [{"project": "alpha", "sessions": 3, "hours": 2.0}]}}))
            out = HUB.load_dir(d, 5)
            self.assertEqual(len(out["files"]), 2)
            self.assertTrue(all(f["status"] == "ok" for f in out["files"]))
            machines = {row["machine"] for row in out["merged"]["activity"]["aggregated"]}
            self.assertEqual(machines, {"m1", "m2"})

    def test_hub_rejects_symlink_escaping_dir(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            secret = os.path.join(outside, "secret.json")
            open(secret, "w").write(json.dumps({"machine": "evil", "agents": [{"name": "leaked"}], "skills": [], "harness": [], "projects": []}))
            os.symlink(secret, os.path.join(d, "escape.json"))
            out = HUB.load_dir(d, 5)
            self.assertEqual(out["files"][0]["status"], "outside")
            self.assertEqual(out["merged"]["agents"], [])

    def test_hub_keeps_aggregated_and_session_detail_from_all_machines(self):
        # Orchestrator amendment: a file with only `aggregated` and a file with `sessions`
        # detail must BOTH survive the merge — detail from one machine must never push the
        # aggregated-only rows of another machine out of the response.
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "m1.json"), "w").write(json.dumps({"cabina": 1, "machine": "m1", "os": "macOS", "when": "x",
                "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                "activity": {"aggregated": [{"project": "alpha", "sessions": 2, "hours": 1.0}]}}))
            open(os.path.join(d, "m2.json"), "w").write(json.dumps({"cabina": 1, "machine": "m2", "os": "Linux", "when": "y",
                "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                "activity": {"aggregated": [{"project": "alpha", "sessions": 3, "hours": 2.0}],
                             "sessions": [{"project": "alpha", "started": "s", "title": "t"}]}}))
            out = HUB.load_dir(d, 5)
            agg_machines = {row["machine"] for row in out["merged"]["activity"]["aggregated"]}
            sess_machines = {row["machine"] for row in out["merged"]["activity"]["sessions"]}
            self.assertEqual(agg_machines, {"m1", "m2"})
            self.assertEqual(sess_machines, {"m2"})

    def test_hub_merges_projects_detail_with_machine(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "m1.json"), "w").write(json.dumps({"cabina": 1, "machine": "m1", "os": "macOS", "when": "x",
                "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                "projects_detail": [{"name": "alpha", "branch": "main", "dirty": 0, "worktrees": 0, "docs": {},
                                      "memory_days": None, "last_commit": "", "agents": 1, "skills": 1}]}))
            open(os.path.join(d, "m2.json"), "w").write(json.dumps({"cabina": 1, "machine": "m2", "os": "Linux", "when": "y",
                "agents": [], "skills": [], "harness": [], "projects": ["alpha"]}))   # no projects_detail key
            out = HUB.load_dir(d, 5)
            rows = out["merged"]["projects_detail"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["machine"], "m1")
            self.assertEqual(rows[0]["name"], "alpha")

    def test_hub_skips_oversized_file(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "big.json"), "w").write(json.dumps({"machine": "m1", "agents": [], "skills": [], "harness": [], "projects": [], "pad": "x" * 2000}))
            out = HUB.load_dir(d, max_mb=0.001)          # ~1 KB cap, file is bigger
            self.assertEqual(out["files"][0]["status"], "too-large")

    @unittest.skipIf(os.name == "nt", "os.mkfifo is POSIX-only")
    def test_hub_skips_fifo_without_hanging(self):
        # D1: a FIFO named *.json under DIR would block forever inside open() (_read_export) —
        # and since every hub endpoint calls load_dir, that hang would take down the whole hub.
        from cabina import hub as HUB
        import threading
        with tempfile.TemporaryDirectory() as d:
            os.mkfifo(os.path.join(d, "pipe.json"))
            result = {}
            def run():
                result["out"] = HUB.load_dir(d, 5)
            t = threading.Thread(target=run, daemon=True)
            t.start()
            t.join(timeout=5)
            self.assertFalse(t.is_alive(), "load_dir hung reading a FIFO")
            self.assertEqual(result["out"]["files"][0]["status"], "not-a-file")

    def test_hub_marks_corrupt_json_as_unreadable_without_crashing(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "bad.json"), "w").write("{not valid json")
            open(os.path.join(d, "good.json"), "w").write(json.dumps({"machine": "m1",
                "agents": [{"name": "x", "project": "p", "tool": "claude", "category": "valid", "model": "sonnet", "uses": 1}],
                "skills": [], "harness": [], "projects": ["p"]}))
            out = HUB.load_dir(d, 5)
            statuses = {f["name"]: f["status"] for f in out["files"]}
            self.assertEqual(statuses["bad.json"], "unreadable")
            self.assertEqual(statuses["good.json"], "ok")
            self.assertEqual(out["merged"]["agents"][0]["machine"], "m1")


class TestHubMergedCache(unittest.TestCase):
    def test_merged_cache_survives_until_a_file_in_dir_changes(self):
        # D3: HubApp._merged() re-read every export on every request. Cache it keyed by the
        # (name, mtime, size) fingerprint of DIR's *.json entries; only re-read when that
        # fingerprint changes.
        from unittest import mock
        from cabina import hub as HUB, config as CFG
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m1.json")
            open(p, "w").write(json.dumps({"machine": "m1", "agents": [{"name": "x"}], "skills": [], "harness": [], "projects": []}))
            app = HUB.HubApp(d, CFG.load(None))
            first = app.api_agents()
            self.assertEqual(first["agents"][0]["name"], "x")
            with mock.patch.object(HUB, "load_dir", side_effect=AssertionError("should be served from cache")):
                second = app.api_agents()                                        # must NOT raise: served from cache
            self.assertEqual(second["agents"][0]["name"], "x")
            future = os.stat(p).st_mtime + 5                                     # force a change coarse mtimes can't hide
            os.utime(p, (future, future))
            with mock.patch.object(HUB, "load_dir", wraps=HUB.load_dir) as spy:
                app.api_agents()
            spy.assert_called_once()                                             # a changed file busts the cache


class TestHubServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from cabina import hub as HUB, config as CFG
        cls.dir = tempfile.mkdtemp()
        open(os.path.join(cls.dir, "m1.json"), "w").write(json.dumps({
            "cabina": 1, "machine": "m1", "os": "macOS", "when": "x",
            "agents": [{"name": "rev", "project": "alpha", "tool": "claude", "category": "valid", "model": "sonnet", "uses": 1}],
            "skills": [], "harness": [{"project": "alpha", "level": "partial", "hooks_dead": [], "hooks_broken": []}],
            "projects": ["alpha"],
            "projects_detail": [{"name": "alpha", "branch": "main", "dirty": 0, "worktrees": 0, "docs": {},
                                  "memory_days": None, "last_commit": "", "agents": 1, "skills": 0}],
            "activity": {"aggregated": [{"project": "alpha", "sessions": 1, "hours": 0.5, "tokens": {"in": 1, "out": 1},
                                          "commits": 0, "files_touched": 0, "tool_calls": {}, "agents": {}, "skills": {}}]}}))
        cls.HUB = HUB
        cls.cfg = CFG.load(None)
        cls.app = HUB.HubApp(cls.dir, cls.cfg)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), HUB.make_hub_handler(cls.app))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path):
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r: return json.loads(r.read())

    def test_index_marks_hub_true(self):
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn('HUB="1"==="1"', html)

    def test_endpoints_and_404s(self):
        import urllib.request, urllib.error
        self.assertEqual(len(self.get("/api/hub")["files"]), 1)
        self.assertEqual(self.get("/api/agents")["agents"][0]["machine"], "m1")
        self.assertTrue(self.get("/api/activity")["aggregated"])
        for p in ("/api/live", "/api/docs", "/api/doc", "/api/references", "/api/in-repo"):
            with self.assertRaises(urllib.error.HTTPError):
                self.get(p)

    def test_api_projects_returns_projects_detail_rows_with_machine_and_safe_defaults(self):
        d = self.get("/api/projects")
        row = d["projects"][0]
        self.assertEqual(row["name"], "alpha")
        self.assertEqual(row["machine"], "m1")
        # fields never exported (local-only or too expensive to recompute) must default so the
        # UI's renderProjects/renderProjDetail never throw on a hub row.
        for k, v in {"exists": True, "git": True, "path": "", "commands": 0, "rules": 0, "hooks": 0,
                     "workflows": 0, "worktrees_mb": 0, "worktrees_detail": []}.items():
            self.assertEqual(row[k], v, k)

    def test_api_harness_returns_states_with_name_machine_and_safe_defaults(self):
        # G1: snapshot.export()'s harness rows carry `project` (not `name`) and only
        # {level, hooks_dead, hooks_broken} — the UI's renderHarness/renderHarDetail read
        # e.name plus several other keys a hub row never exports. Without a `name`, clicking
        # a harness row in hub mode could never resolve its detail (silent no-op).
        d = self.get("/api/harness")
        row = d["states"][0]
        self.assertEqual(row["name"], "alpha")
        self.assertEqual(row["machine"], "m1")
        self.assertEqual(row["level"], "partial")
        for k, v in {"hooks_active": [], "hooks": [], "missing": [], "hooks_helpers": [],
                     "memory_days": None, "runlog": False, "has": {}, "path": "", "rules": 0,
                     "workflows": 0}.items():
            self.assertEqual(row[k], v, k)

    def test_post_is_always_405(self):
        import urllib.request, urllib.error
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/rescan", data=b"{}", method="POST")
        try:
            urllib.request.urlopen(req); self.fail("expected 405")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 405)


if __name__ == "__main__":
    unittest.main()
