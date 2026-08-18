import copy, json, os, threading, time, unittest, urllib.request
import _helpers  # noqa
from _env import Env
from cabina import server, scan
from http.server import ThreadingHTTPServer

class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        # S1-a: guarantee at least one "crit" finding for /api/health (the shared fixture's
        # warn_agents/dead_hooks/rules_diverged only produce warn+info) — an agent missing the
        # critical `description` field, local to THIS test module only.
        open(os.path.join(cls.env.alpha, ".claude", "agents", "broken.md"), "w").write(
            "---\nname: broken\nmodel: sonnet\n---\nBody without a description.\n")
        scan.save(cls.env.cfg, scan.run(cls.env.cfg))
        cls.app = server.App(cls.env.cfg)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cls.app))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close(); cls.env.cleanup()

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
    def test_skills_endpoint_caches_usage_refresh_and_invalidates_on_archive(self):
        # H2: api_skills used to call usage.refresh() (a grep over ~/.claude/projects) on
        # every request, unlike api_agents' cached, TTL'd roster(). Mirror that pattern for
        # skills: two consecutive GETs must refresh usage only once; archiving a skill must
        # invalidate the cache so the next GET refreshes again.
        from cabina import usage
        from unittest import mock
        tdir = os.path.join(self.env.alpha, ".claude", "skills", "throwaway")
        os.makedirs(tdir, exist_ok=True)
        open(os.path.join(tdir, "SKILL.md"), "w").write("---\nname: throwaway\ndescription: t\n---\n")
        self.app._skills = None                      # force a real recompute inside the patched block below
        with mock.patch("cabina.server.usage.refresh", wraps=usage.refresh) as m:
            s1 = self.get("/api/skills")
            self.assertTrue(any(x["name"] == "throwaway" for x in s1["skills"]))
            self.get("/api/skills")
            self.assertEqual(m.call_count, 1)                 # second GET served from cache: no re-refresh
            code, r = self.post("/api/archive-skill", {"name": "throwaway", "path": tdir, "project": "alpha"})
            self.assertTrue(r["ok"], r)
            s2 = self.get("/api/skills")
            self.assertEqual(m.call_count, 2)                 # archive invalidated the cache: refreshes again
            self.assertFalse(any(x["name"] == "throwaway" for x in s2["skills"]))
    def test_rescan_invalidates_skills_cache(self):
        # Reviewer-verified regression: api_rescan's background go() clears self._roster but
        # not self._skills, so Skills could show up to 30s of stale data after a rescan even
        # though Agents (via roster()) refreshes instantly.
        self.app.skills()                                   # warm the cache with the pre-existing skill set
        tdir = os.path.join(self.env.alpha, ".claude", "skills", "rescan-new")
        os.makedirs(tdir, exist_ok=True)
        open(os.path.join(tdir, "SKILL.md"), "w").write("---\nname: rescan-new\ndescription: r\n---\n")
        self.app.api_rescan({})
        for _ in range(150):
            if not self.app._scanning:      # S3-a: the authoritative "this rescan finished" signal —
                break                        # _roster alone can already be None from a PRIOR rescan
            time.sleep(0.02)
        else:
            self.fail("rescan did not complete in time")
        rows, _ = self.app.skills()                          # still within the 30s TTL: must reflect the rescan
        self.assertTrue(any(x["name"] == "rescan-new" for x in rows))
        # cleanup: this fixture is shared across the whole TestServer class (setUpClass), so
        # remove the added skill and re-sync data/caches before the next test reads them.
        import shutil
        shutil.rmtree(tdir)
        self.app.api_rescan({})
        for _ in range(150):
            if not self.app._scanning:
                break
            time.sleep(0.02)
    # ---------- S3-a: /api/rescan (mcp/worktrees options) + /api/scan-status ----------
    def test_rescan_gates_check_mcp_and_measure_worktrees_via_copied_cfg(self):
        from unittest import mock
        orig_mcp = self.app.cfg["scan"]["check_mcp"]; orig_wt = self.app.cfg["scan"]["measure_worktrees"]
        captured = {}
        def fake_run(cfg):
            captured["cfg"] = cfg
            return {"projects": [], "global": {"agents": [], "skills": [], "commands": [], "rules": []},
                    "sessions": [], "codex": {"present": False, "home": "", "agents": [], "skills": []},
                    "mcp": {"checked": False, "servers": []}, "generated": "x", "claude_home": self.env.cfg["claude_home"]}
        with mock.patch("cabina.server.scan.run", side_effect=fake_run), mock.patch("cabina.server.scan.save"):
            r = self.app.api_rescan({"mcp": True, "worktrees": True})
            self.assertTrue(r["ok"], r)
            for _ in range(150):
                if not self.app._scanning: break
                time.sleep(0.02)
            else: self.fail("rescan did not finish")
        try:
            self.assertTrue(captured["cfg"]["scan"]["check_mcp"])
            self.assertTrue(captured["cfg"]["scan"]["measure_worktrees"])
            self.assertEqual(self.app.cfg["scan"]["check_mcp"], orig_mcp)          # self.cfg never mutated
            self.assertEqual(self.app.cfg["scan"]["measure_worktrees"], orig_wt)
        finally:
            # restore the real cache the go() thread overwrote with the fake minimal scan, and
            # re-warm roster/skills — go()'s own success path already reset both to None, and
            # leaving them None would make test_rescan_invalidates_skills_cache (which treats
            # "_roster is None" as "my OWN rescan just completed") pass vacuously.
            self.app.data = scan.load(self.env.cfg); self.app._roster = None; self.app._skills = None
            self.app.roster(); self.app.skills()
    def test_second_rescan_while_running_is_refused(self):
        from unittest import mock
        ev = threading.Event()
        def slow_run(cfg):
            ev.wait(2); return scan.load(self.env.cfg)
        with mock.patch("cabina.server.scan.run", side_effect=slow_run), mock.patch("cabina.server.scan.save"):
            r1 = self.app.api_rescan({})
            self.assertTrue(r1["ok"], r1)
            r2 = self.app.api_rescan({})
            self.assertFalse(r2["ok"]); self.assertIn("already running", r2["message"])
            ev.set()
            for _ in range(150):
                if not self.app._scanning: break
                time.sleep(0.02)
        self.app.data = scan.load(self.env.cfg); self.app._roster = None; self.app._skills = None
        self.app.roster(); self.app.skills()   # re-warm: see comment in the "gates" test above
    def test_rescan_publishes_data_before_flipping_scanning_and_releasing_lock(self):
        # S3 fix-up: the go() thread must publish self.data (and clear _roster/_skills) BEFORE
        # flipping _scanning False and releasing _scan_lock. Otherwise a poller that sees
        # scanning=False and immediately reloads /api/agents can still get the OLD self.data,
        # and a second POST /api/rescan landing in the gap between release() and _scanning=False
        # would be accepted, starting an overlapping scan.
        from unittest import mock
        marker = copy.deepcopy(self.app.data)
        marker["projects"] = list(marker["projects"]) + [{
            "path": "/tmp/after-rescan", "name": "after-rescan", "agents": [], "skills": [],
            "commands": [], "rules": [], "git": None, "claude_md": None, "agents_md": None,
            "agents_md_link": None,
        }]
        with mock.patch("cabina.server.scan.run", return_value=marker), mock.patch("cabina.server.scan.save"):
            r = self.app.api_rescan({})
            self.assertTrue(r["ok"], r)
            for _ in range(150):
                if not self.app._scanning:
                    # The instant _scanning flips False, self.data must ALREADY be the new
                    # marker and the lock must ALREADY be released — never observe the old
                    # order where scanning=False (or lock released) precedes the data swap.
                    self.assertTrue(
                        any(p["name"] == "after-rescan" for p in self.app.data["projects"]),
                        "scanning flipped False (or lock released) before self.data was published")
                    self.assertFalse(self.app._scan_lock.locked())
                    break
                time.sleep(0.001)
            else:
                self.fail("rescan did not finish")
        # restore the real cache/state before other tests in this shared fixture run
        self.app.data = scan.load(self.env.cfg); self.app._roster = None; self.app._skills = None
        self.app.roster(); self.app.skills()
    def test_scan_status_reflects_error_when_scan_run_raises(self):
        from unittest import mock
        d0 = self.get("/api/scan-status")
        for k in ("scanning", "started", "finished", "error", "scanned_at"): self.assertIn(k, d0)
        def boom(cfg): raise RuntimeError("kaboom")
        with mock.patch("cabina.server.scan.run", side_effect=boom):
            r = self.app.api_rescan({})
            self.assertTrue(r["ok"], r)
            for _ in range(150):
                if not self.app._scanning: break
                time.sleep(0.02)
            else: self.fail("did not finish")
        try:
            d = self.get("/api/scan-status")
            self.assertFalse(d["scanning"]); self.assertIn("kaboom", d["error"])
        finally:
            self.app._scan_error = None
    def test_scan_status_scanned_at_is_cache_mtime(self):
        p = scan.cache_path(self.env.cfg)
        self.assertTrue(os.path.isfile(p))
        d = self.get("/api/scan-status")
        self.assertIsNotNone(d["scanned_at"])
    def test_rescan_ui_polls_scan_status_no_fixed_timeout(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertNotIn("45000", html)
        self.assertIn("/api/scan-status", html)
    # ---------- S3-b: /api/export ----------
    def test_export_endpoint_returns_snapshot_shape_and_download_headers(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/export")
        with urllib.request.urlopen(req) as r:
            headers = dict(r.getheaders()); body = json.loads(r.read())
        self.assertIn("Content-Disposition", headers)
        self.assertIn("attachment", headers["Content-Disposition"])
        for k in ("cabina", "machine", "agents", "skills", "projects"): self.assertIn(k, body)
        self.assertNotIn("activity", body)
    def test_export_endpoint_with_activity(self):
        # snapshot.export_activity() refreshes the sessions registry itself — no need to call
        # sessions.refresh() here too (and doing so redundantly only widens a pre-existing race
        # window against other tests' background /api/activity refreshes).
        d = self.get("/api/export?activity=1")
        self.assertIn("activity", d); self.assertIn("aggregated", d["activity"])
    # ---------- S3-c: /api/compare ----------
    def test_compare_self_export_has_no_diffs(self):
        a = self.get("/api/export")
        code, r = self.post("/api/compare", {"other": a})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["delta"]["agents"]["only_a"], []); self.assertEqual(r["delta"]["agents"]["only_b"], [])
        self.assertIn("text", r)
    def test_compare_rejects_non_export(self):
        code, r = self.post("/api/compare", {"other": {}}); self.assertFalse(r["ok"])
        code, r = self.post("/api/compare", {"other": "not a dict"}); self.assertFalse(r["ok"])
    def test_compare_rejects_oversized_body(self):
        big = {"other": {"agents": [{"pad": "x" * 1000} for _ in range(6000)]}}
        code, r = self.post("/api/compare", big)
        self.assertFalse(r["ok"])
    def test_scan_export_compare_block_fields_always_escaped(self):
        import re
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("// ---------- SCAN / EXPORT / COMPARE ----------")
        end = html.index("// ---------- HARNESS ----------")
        body = html[start:end]
        pattern = re.compile(r"\$\{([^{}]*\btext\b[^{}]*)\}")
        hits = list(pattern.finditer(body))
        self.assertGreater(len(hits), 0)
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
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
    def test_activity_endpoint_filters_by_days(self):
        # H3(i): api_activity received `days` but returned EVERY cached session regardless
        # (measured: identical payload size for days=7 and days=365). Filter by `started`.
        from cabina import sessions as SESS
        from datetime import datetime, timedelta, timezone
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        sdir = os.path.join(self.env.claude, "projects", "-work-alpha")
        old_id = "sess-old-b3"
        with open(os.path.join(sdir, old_id + ".jsonl"), "w") as f:
            f.write(json.dumps({"type": "user", "timestamp": old_ts, "cwd": self.env.alpha, "gitBranch": "main",
                                 "sessionId": old_id, "version": "1.0.0",
                                 "message": {"role": "user", "content": [{"type": "text", "text": "old session"}]}}) + "\n")
        SESS.refresh(self.env.cfg, days=3650)
        d_wide = self.get("/api/activity?project=alpha&days=3650")
        self.assertTrue(any(s["session_id"] == old_id for s in d_wide["sessions"]))
        d_narrow = self.get("/api/activity?project=alpha&days=1")
        self.assertFalse(any(s["session_id"] == old_id for s in d_narrow["sessions"]))
        self.assertLessEqual(len(d_narrow["sessions"]), len(d_wide["sessions"]))
    def test_post_requires_token(self):
        code, _ = self.post("/api/open", {"path": "/tmp"}, token="wrong"); self.assertEqual(code, 403)
        code, _ = self.post("/api/open", {"path": "/tmp"}, token=""); self.assertEqual(code, 403)
    # ---------- Host/Origin guard (anti DNS-rebinding) ----------
    def _raw(self, method, path, headers=None, body=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            r = conn.getresponse()
            data = r.read()
            return r.status, data
        finally:
            conn.close()
    def test_get_with_bad_host_header_rejected(self):
        code, body = self._raw("GET", "/", headers={"Host": "evil.example"})
        self.assertEqual(code, 421)
        self.assertFalse(json.loads(body)["ok"])
    def test_get_with_normal_host_header_ok(self):
        code, body = self._raw("GET", "/", headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(code, 200)
    def test_post_with_bad_host_header_rejected(self):
        headers = {"Host": "evil.example", "Content-Type": "application/json", "X-Cabina-Token": self.app.token}
        code, body = self._raw("POST", "/api/open", headers=headers, body=json.dumps({"path": "/tmp"}).encode())
        self.assertEqual(code, 421)
        self.assertFalse(json.loads(body)["ok"])
    def test_post_with_bad_origin_rejected_even_with_valid_token(self):
        headers = {"Host": f"127.0.0.1:{self.port}", "Origin": "http://evil.example",
                   "Content-Type": "application/json", "X-Cabina-Token": self.app.token}
        code, body = self._raw("POST", "/api/open", headers=headers, body=json.dumps({"path": "/tmp"}).encode())
        self.assertEqual(code, 403)
        self.assertFalse(json.loads(body)["ok"])
    def test_post_with_loopback_origin_allowed(self):
        from unittest import mock
        with mock.patch("cabina.server.host.open_path", return_value=(True, "opened")):
            headers = {"Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}",
                       "Content-Type": "application/json", "X-Cabina-Token": self.app.token}
            code, body = self._raw("POST", "/api/open", headers=headers,
                                    body=json.dumps({"path": self.env.alpha}).encode())
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])
    def test_post_origin_matching_configured_bind_host_allowed(self):
        # server.host is user-configurable (config.py DEFAULTS / example config): a user may
        # bind to a LAN IP, not just loopback. The Origin check must accept loopback OR the
        # exact configured bind host -- otherwise the UI's own POSTs from a non-loopback bind
        # would be refused as "bad origin", a functional regression. The TEST server still
        # binds 127.0.0.1 (so this suite can talk to it); only cfg["server"]["host"] differs.
        import copy, http.client, threading
        from http.server import ThreadingHTTPServer
        from unittest import mock
        from cabina import server as SRV
        cfg2 = copy.deepcopy(self.env.cfg)
        cfg2["server"]["host"] = "10.0.0.5"
        app2 = SRV.App(cfg2)
        srv2 = ThreadingHTTPServer(("127.0.0.1", 0), SRV.make_handler(app2))
        port2 = srv2.server_address[1]
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        try:
            with mock.patch("cabina.server.host.open_path", return_value=(True, "opened")):
                conn = http.client.HTTPConnection("127.0.0.1", port2)
                headers = {"Host": f"127.0.0.1:{port2}", "Origin": "http://10.0.0.5:1234",
                           "Content-Type": "application/json", "X-Cabina-Token": app2.token}
                conn.request("POST", "/api/open", body=json.dumps({"path": app2.cfg["claude_home"]}).encode(), headers=headers)
                r = conn.getresponse(); code = r.status; body = json.loads(r.read()); conn.close()
            self.assertEqual(code, 200, body)          # bind host as Origin: allowed
            self.assertTrue(body["ok"], body)
            conn = http.client.HTTPConnection("127.0.0.1", port2)
            headers2 = {"Host": f"127.0.0.1:{port2}", "Origin": "http://evil.example",
                        "Content-Type": "application/json", "X-Cabina-Token": app2.token}
            conn.request("POST", "/api/open", body=json.dumps({"path": "/tmp"}).encode(), headers=headers2)
            r2 = conn.getresponse(); code2 = r2.status; r2.read(); conn.close()
            self.assertEqual(code2, 403)               # still refuses a genuinely foreign origin
        finally:
            srv2.shutdown(); srv2.server_close()
    # ---------- /api/open path confinement ----------
    def test_open_outside_roots_refused_and_never_calls_host_open_path(self):
        from unittest import mock
        with mock.patch("cabina.server.host.open_path") as m:
            code, r = self.post("/api/open", {"path": "/tmp"})
        self.assertFalse(r["ok"], r)
        self.assertIn("outside", r["message"])
        m.assert_not_called()
    def test_open_inside_project_root_allowed(self):
        from unittest import mock
        with mock.patch("cabina.server.host.open_path", return_value=(True, "opened")) as m:
            code, r = self.post("/api/open", {"path": os.path.join(self.env.alpha, "CLAUDE.md")})
        self.assertTrue(r["ok"], r)
        m.assert_called_once()
    # ---------- W3: /api/worktrees ----------
    def test_worktrees_endpoint_shape_and_project_filter(self):
        orig_data = self.app.data
        try:
            self.app.data = copy.deepcopy(orig_data)
            self.app.data["projects"] = list(self.app.data["projects"]) + [{
                "name": "wt-proj", "path": "/tmp/wt-proj",
                "git": {"worktrees": [
                    {"path": "/tmp/wt-proj-wt/a", "name": "a", "mb": 10, "mtime": "2026-08-01", "dirty": 0, "branch": "b", "prunable": False},
                    {"path": "/tmp/wt-proj-wt/b", "name": "b", "mb": None, "mtime": "2026-08-02", "dirty": 2, "branch": "c", "prunable": False},
                ]},
                "agents": [], "skills": [], "commands": [], "rules": [],
                "claude_md": None, "agents_md": None, "agents_md_link": None,
            }]
            d = self.get("/api/worktrees?project=wt-proj")
            self.assertEqual(d["summary"]["total"], 2)
            self.assertEqual(d["summary"]["clean"], 1)
            self.assertEqual(d["summary"]["dirty"], 1)
            self.assertFalse(d["summary"]["mb_measured"])
            self.assertEqual({r["name"] for r in d["rows"]}, {"a", "b"})
            self.assertIn("git -C", d["script"])
            d_all = self.get("/api/worktrees")
            self.assertGreaterEqual(len(d_all["rows"]), 2)
        finally:
            self.app.data = orig_data
    # ---------- W3: /api/open-terminal ----------
    def test_open_terminal_outside_roots_refused_and_never_calls_host(self):
        from unittest import mock
        with mock.patch("cabina.server.host.open_terminal") as m:
            code, r = self.post("/api/open-terminal", {"path": "/tmp"})
        self.assertFalse(r["ok"], r)
        m.assert_not_called()
    def test_open_terminal_refuses_a_file(self):
        from unittest import mock
        with mock.patch("cabina.server.host.open_terminal") as m:
            code, r = self.post("/api/open-terminal", {"path": os.path.join(self.env.alpha, "CLAUDE.md")})
        self.assertFalse(r["ok"], r)
        m.assert_not_called()
    def test_open_terminal_inside_project_root_allowed(self):
        from unittest import mock
        with mock.patch("cabina.server.host.open_terminal", return_value=(True, "opened")) as m:
            code, r = self.post("/api/open-terminal", {"path": self.env.alpha})
        self.assertTrue(r["ok"], r)
        m.assert_called_once()
    def test_open_terminal_requires_token(self):
        code, _ = self.post("/api/open-terminal", {"path": self.env.alpha}, token="wrong")
        self.assertEqual(code, 403)
    # ---------- W3: Projects tab worktree panel (UI) ----------
    def test_worktree_panel_hub_gated_source_guards(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function loadWorktreePanel", html)
        self.assertIn('!HUB&&x.worktrees?', html)
        self.assertIn("if(!HUB&&x.worktrees)loadWorktreePanel(x)", html)
        # internal guard too (double-gate), in case the function is ever called from elsewhere
        start = html.index("async function loadWorktreePanel")
        self.assertIn("if(HUB)return;", html[start:start + 200])
    def test_worktree_panel_script_output_escaped(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("esc(r.script)", html)
    def test_server_module_never_shells_out_directly(self):
        # W3: cabina never runs `git worktree remove`/prune itself -- the script is only ever
        # text for the user to review and paste. Guard the ENTIRE server.py module, not just the
        # new endpoint, so a future change here regresses loudly.
        server_path = os.path.join(os.path.dirname(server.__file__), "server.py")
        src = open(server_path, encoding="utf-8").read()
        self.assertNotIn("subprocess", src)
        self.assertNotIn("worktree remove", src)
        self.assertNotIn("worktree prune", src)
    def test_worktree_i18n_keys_present_in_both_languages(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("const I18N={")
        end = html.index("const T=(k,v)=>")
        block = html[start:end]
        split = block.index("\nes:{")
        en_block, es_block = block[:split], block[split:]
        for key in ("wtStats", "wtSizeGb", "wtSizeUnmeasured", "wtRescanSizes", "wtCopyScript", "wtOpenTerminal", "wtLoadError"):
            self.assertIn(key + ":", en_block, key)
            self.assertIn(key + ":", es_block, key)
    def test_worktree_panel_fetch_failure_shows_error_instead_of_hanging_on_loading(self):
        # Follow-up: GET() has no error handling of its own, so a rejected /api/worktrees
        # fetch (network failure, bad JSON, ...) used to leave the panel stuck on "loading…"
        # forever plus an unhandled promise rejection. loadWorktreePanel must catch just that
        # fetch and render a short error line instead -- the shared GET() helper itself must
        # stay untouched (out of scope for this fix).
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("async function loadWorktreePanel")
        end = html.index("// ---------- SCAN / EXPORT / COMPARE ----------")
        body = html[start:end]
        self.assertIn("catch", body)
        self.assertIn('T("wtLoadError")', body)
        self.assertIn('async function GET(u){return (await fetch(u)).json();}', html)   # GET() itself unchanged
    def test_project_row_and_footer_never_show_a_fake_zero_gb_for_unmeasured_worktrees(self):
        # Follow-up to the worktree panel: the ORIGINAL project row and the tab footer still
        # computed (x.worktrees_mb/1024).toFixed(1) unconditionally, so an unmeasured project
        # (worktrees_mb defaults to 0) rendered a lying "0.0G"/"(0.0 GB)". Both the row text and
        # the footer aggregate must key off worktrees_mb_measured, and the size-based warn dot
        # heuristic must never fire on an unmeasured (i.e. zero) size either.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("function renderProjects(){if(!S.projs)")
        end = html.index("function renderProjDetail(){")
        body = html[start:end]
        # row text: GB only when measured, "?G" otherwise -- never a raw toFixed(1) on an
        # unmeasured size
        self.assertIn('x.worktrees_mb_measured?(x.worktrees_mb/1024).toFixed(1)+"G":"?G"', body)
        # footer: GB total only when every project with worktrees was measured, "? GB" otherwise,
        # and omitted entirely when nothing has worktrees at all (no more unconditional "(0.0 GB)")
        self.assertIn("wtMeasured?wtG.toFixed(1)", body)
        self.assertIn('"? GB"', body)
        self.assertIn("wtProjects.length?", body)
        # the red/amber dot must never trigger the size condition on an unmeasured project
        self.assertIn("x.worktrees_mb_measured&&x.worktrees_mb>5000", body)
        self.assertNotIn('x.worktrees_mb>5000?"invalid"', body)   # the old, ungated heuristic
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
    def test_boot_lazy_loads_non_default_tabs(self):
        # H3(ii): the boot fetched agents, skills, projects, harness, activity, docs and hub in
        # one burst regardless of which tab was visible. Only what the header needs (agents,
        # live, hub banner) should load eagerly; the rest loads on first visit via ensureLoaded.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertNotIn("loadSkills();loadProjs();loadHar();loadActivity();", html)
        self.assertIn("function ensureLoaded", html)
    def test_activity_supports_aggregated_shape(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function renderActivityAggregated", html)
    def test_live_polling_pauses_when_hidden_and_resumes_on_visible(self):
        # H4: setInterval(loadLive,1000) ran forever regardless of tab visibility, each tick
        # launching 2 herdr subprocesses. Guard on document.hidden and refresh immediately on
        # visibilitychange, instead of two separate timers.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("visibilitychange", html)
        self.assertIn("document.hidden", html)
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
    def test_agents_skills_block_fields_always_escaped(self):
        # F1: the ACTIVITY-only scan above never reaches renderAgents / renderAgentDetail /
        # renderSkillDetail (all defined before the ACTIVITY marker), and its field list omits
        # desc. Scan the AGENTS->ACTIVITY block (also covers renderArchive/renderCreate/
        # renderSkills in between) and add desc/description/name to the fields checked.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        import re
        start = html.index("// ---------- AGENTS ----------")
        end = html.index("// ---------- ACTIVITY ----------")
        body = html[start:end]
        # renderArchive interpolates x.name/x.project into a git commit MESSAGE string
        # (`cabina: archive ${x.name} (${x.project})`), never into innerHTML — not an escaping
        # concern. Whitelisted by exact substring so any other change to this block is still caught.
        git_message = "`cabina: archive ${x.name} (${x.project})`"
        self.assertIn(git_message, body, "git message literal moved; update whitelist")
        body = body.replace(git_message, "")
        pattern = re.compile(r"\$\{([^{}]*\bx\.(?:title|project|machine|branch|desc|description|name)\b[^{}]*)\}")
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
    def test_agent_detail_hides_file_row_in_hub(self):
        # F2: hub export rows carry no path, so renderAgentDetail's unconditional "File" meta row
        # rendered blank in hub mode. Guard the row on !HUB && x.path.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("(!HUB&&x.path)", html)
    def test_project_detail_keyed_by_name_and_machine(self):
        # E2: renderProjDetail found a row with `find(y=>y.name===S.sel)` — in hub mode two
        # machines can both have a project called "alpha", so the detail always showed the
        # first one, no matter which row was clicked.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function projKey", html)
        self.assertIn("projKey(y)===S.sel", html)
    def test_harness_row_and_detail_keyed_by_name_and_machine(self):
        # G1: harness rows used e.name alone as key — in hub mode two machines can both have a
        # project called "alpha", so the detail always resolved the first one. Mirror projKey.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function harKey", html)
        self.assertIn("harKey(x)===name", html)
    def test_unknown_routes(self):
        with self.assertRaises(urllib.error.HTTPError): self.get("/api/nope")
        code, _ = self.post("/api/nope", {}); self.assertEqual(code, 404)
    # ---------- S1: /api/health ----------
    def test_health_endpoint_shape(self):
        d = self.get("/api/health")
        self.assertNotIn("error", d)
        self.assertIn("ran_at", d)
        self.assertFalse(d["quick"])
        sevs = {f["sev"] for f in d["findings"]}
        self.assertIn("crit", sevs)       # the broken.md agent added in setUpClass
        self.assertIn("warn", sevs)       # the dead hook / shadowing agent in the base fixture
        for f in d["findings"]:
            self.assertIn(f["sev"], ("crit", "warn", "info"))
            for k in ("title", "detail", "fix"):
                self.assertIn(k, f)
    def test_health_endpoint_survives_check_run_exception(self):
        # The tab must never render blank: if check.run() throws, the endpoint still answers
        # 200 with an empty findings list and the error message, never a 500.
        from unittest import mock
        with mock.patch("cabina.server.CHECK.run", side_effect=RuntimeError("boom")):
            d = self.get("/api/health")
        self.assertEqual(d["findings"], [])
        self.assertIn("boom", d["error"])
    # ---------- Fase 3: /api/health-history ----------
    def test_health_history_endpoint(self):
        from cabina import healthlog as HL
        from datetime import datetime, timedelta
        now = datetime.now().astimezone()
        older = now - timedelta(days=3)
        HL.append(self.env.cfg, [{"sev": "crit"} for _ in range(11)], now=older)
        HL.append(self.env.cfg, [{"sev": "crit"} for _ in range(22)], now=now)
        d = self.get("/api/health-history?days=30")
        self.assertIn("series", d)
        series = d["series"]
        self.assertIsInstance(series, list)
        idx11 = next(i for i, s in enumerate(series) if s.get("crit") == 11)
        idx22 = next(i for i, s in enumerate(series) if s.get("crit") == 22)
        self.assertLess(idx11, idx22)             # oldest first
        for s in series:
            for k in ("when", "crit", "warn", "info"):
                self.assertIn(k, s)
    def test_health_history_endpoint_defaults_and_caps_days(self):
        d = self.get("/api/health-history")
        self.assertIn("series", d)
        d2 = self.get("/api/health-history?days=999999")
        self.assertIn("series", d2)   # never errors out on an out-of-range days value
    # ---------- Fase 3: /api/tiles (R13 project dashboard) ----------
    def test_project_tiles_shape(self):
        d = self.get("/api/tiles")
        self.assertIn("tiles", d); self.assertIn("health", d); self.assertIn("ran_at", d)
        names = {t["project"] for t in d["tiles"]}
        self.assertIn("alpha", names)
        allowed = {"project", "last_session", "active", "health", "open_findings_count"}
        for t in d["tiles"]:
            self.assertEqual(set(t), allowed)
            self.assertIsInstance(t["active"], bool)
            for k in ("crit", "warn", "info"):
                self.assertIn(k, t["health"])
            self.assertEqual(t["open_findings_count"], sum(t["health"].values()))
        alpha = next(t for t in d["tiles"] if t["project"] == "alpha")
        self.assertGreaterEqual(alpha["health"]["warn"], 1)   # dead hook / shadow warning, attributed per Unit 1
    def test_project_tiles_calls_check_run_with_quick_false(self):
        # api_tiles must agree with the Health tab, which runs check.run(quick=False) --
        # quick=True silently drops the "never invoked agents" info finding.
        from unittest import mock
        calls = {}
        def fake_run(cfg, quick=False):
            calls["quick"] = quick
            return []
        with mock.patch("cabina.server.CHECK.run", side_effect=fake_run):
            self.get("/api/tiles")
        self.assertIn("quick", calls)
        self.assertFalse(calls["quick"])
    def test_health_totals_counts_each_finding_once_including_global_and_multi_project(self):
        # Unit fix: top-level `health` must count EVERY finding by severity exactly once --
        # including ones with no `projects` key (global findings, e.g. broken symlinks/MCP/stale
        # scan) -- never the SUM of per-tile attributed counts, which double-counts a finding
        # attributed to more than one project and drops global findings entirely.
        from cabina import server as SRV
        findings = [
            {"sev": "crit"},                          # global: no `projects` key at all
            {"sev": "warn", "projects": ["a", "b"]},   # attributed to two projects
            {"sev": "info", "projects": ["a"]},
            {"sev": "bogus"},                          # unknown severity: never counted
        ]
        self.assertEqual(SRV._health_totals(findings), {"crit": 1, "warn": 1, "info": 1})
    def test_project_tiles_order(self):
        from cabina import server as SRV
        tiles = [
            {"project": "z", "last_session": "2026-08-10T00:00:00", "active": False},
            {"project": "a", "last_session": None, "active": True},
            {"project": "b", "last_session": "2026-08-15T00:00:00", "active": True},
            {"project": "c", "last_session": None, "active": False},
            {"project": "d", "last_session": "2026-08-01T00:00:00", "active": False},
        ]
        ordered = [t["project"] for t in SRV._order_tiles(tiles)]
        self.assertEqual(ordered, ["b", "a", "z", "d", "c"])
    def test_project_tiles_never_task_like_fields(self):
        # R13: tiles are a read-only summary, never a Kanban -- no status/assignee/free text,
        # neither in the API shape (Unit 2) nor accidentally introduced by the renderer (Unit 3).
        tile = self.app.api_tiles()["tiles"][0]
        self.assertEqual(set(tile), {"project", "last_session", "active", "health", "open_findings_count"})
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("function healthPills")
        end = html.index("function renderProjects(){if(!S.projs)")
        src = html[start:end]
        for bad in ("assignee", "todo", "\"status\"", "'status'"):
            self.assertNotIn(bad, src)
        # the crit/warn/info pills must actually be built from the health counts (not silently
        # dropped) -- both per-tile (t.health, passed to healthPills) and in the tiles header
        # (the global S.tiles.health totals from Unit fix #2).
        for k in ("health.crit", "health.warn", "health.info"):
            self.assertIn(k, src)
        self.assertIn("healthPills(t.health)", src)
        self.assertIn("healthPills(S.tiles.health)", src)
        import re
        pattern = re.compile(r"\$\{([^{}]*\bt\.(?:project|last_session)\b[^{}]*)\}")
        hits = list(pattern.finditer(src))
        self.assertGreater(len(hits), 0)
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
    def test_project_tiles_grid_is_compact_and_height_capped(self):
        # Live-check finding: with 21 real projects the tiles grid took 5 rows and pushed the
        # project list off-screen. Compact row tiles + a capped, scrollable grid area.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("minmax(220px,1fr)", html)
        self.assertIn("max-height:30vh", html)
        self.assertIn("overflow:auto", html)
    def test_tiles_and_sparkline_i18n_keys_present_in_both_languages(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("const I18N={")
        end = html.index("const T=(k,v)=>")
        block = html[start:end]
        split = block.index("\nes:{")
        en_block, es_block = block[:split], block[split:]
        for key in ("tilesTitle", "tilesSparkAria", "tileActive", "tileIdle", "tileNever"):
            self.assertIn(key + ":", en_block, key)
            self.assertIn(key + ":", es_block, key)
    def test_projects_tab_lazy_loads_tiles_never_in_hub(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("/api/tiles", html)
        self.assertIn("/api/health-history", html)
        # both fetches are guarded the same way every other server-only call is: `if(HUB)return;`
        loadtiles = html[html.index("async function loadTiles"):html.index("async function loadTiles") + 60]
        self.assertIn("HUB", loadtiles)
    # ---------- S1-b/c: Health tab ----------
    def test_index_health_tab_is_first_and_default_view_outside_hub(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        # health is the FIRST entry of the non-hub VIEWS array, and the boot default view.
        self.assertIn(':["health","agents",', html)
        self.assertIn('view:HUB?"agents":"health"', html)
        self.assertIn("/api/health", html)
    def test_hub_view_list_has_no_health_tab(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        # the hub-mode branch of the VIEWS ternary is untouched: no "health" in it.
        self.assertIn('HUB?["agents","skills","projects","harness","activity"]', html)
    def test_health_block_fields_always_escaped(self):
        import re
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("// ---------- HEALTH ----------")
        end = html.index("// ---------- AGENTS ----------")
        body = html[start:end]
        pattern = re.compile(r"\$\{([^{}]*\b(?:f\.(?:title|detail|fix)|H\.error)\b[^{}]*)\}")
        hits = list(pattern.finditer(body))
        self.assertGreater(len(hits), 0)
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
    # ---------- S2-b: /api/hooks, /api/hooks-install ----------
    def test_hooks_status_endpoint_shape(self):
        d = self.get("/api/hooks")
        self.assertEqual(d["settings_path"], os.path.join(self.env.claude, "settings.json"))
        for k in ("exists", "valid_json", "guard_installed", "brief_installed", "cmd_resolves", "cmd_path", "snippet"):
            self.assertIn(k, d)

    def test_hooks_status_endpoint_accepts_cmd_query(self):
        from unittest import mock
        with mock.patch("cabina.guard.shutil.which", return_value=None):
            d = self.get("/api/hooks?cmd=definitely-not-a-real-cmd-xyz")
        self.assertFalse(d["cmd_resolves"])
        self.assertIsNone(d["cmd_path"])

    def test_hooks_install_refused_when_cmd_does_not_resolve_no_backup(self):
        from unittest import mock
        settings = os.path.join(self.env.claude, "settings.json")
        self.assertFalse(os.path.isfile(settings))
        with mock.patch("cabina.guard.shutil.which", return_value=None):
            code, r = self.post("/api/hooks-install", {"cmd": "cabina-missing-xyz"})
        self.assertFalse(r["ok"], r)
        self.assertIn("not on PATH", r["message"])
        self.assertFalse(os.path.isfile(settings))
        self.assertFalse(any(f.startswith("settings.json.bak-") for f in os.listdir(self.env.claude)))

    def test_hooks_install_rejects_non_cabina_command_even_with_force(self):
        # U2: hooks may only ever run cabina -- a `bash -c '...'` payload must be refused
        # regardless of force=True (force only bypasses the "not on PATH" check).
        settings = os.path.join(self.env.claude, "settings.json")
        if os.path.isfile(settings):
            os.remove(settings)
        code, r = self.post("/api/hooks-install", {"cmd": "bash -c 'echo pwned'", "force": True})
        self.assertFalse(r["ok"], r)
        self.assertIn("cabina", r["message"])
        self.assertFalse(os.path.isfile(settings))

    def test_hooks_install_ok_and_idempotent(self):
        from unittest import mock
        settings = os.path.join(self.env.claude, "settings.json")
        try:
            with mock.patch("cabina.guard.shutil.which", return_value="/usr/local/bin/cabina"):
                code, r = self.post("/api/hooks-install", {"cmd": "cabina"})
            self.assertTrue(r["ok"], r)
            self.assertTrue(os.path.isfile(settings))
            d = json.load(open(settings))
            self.assertTrue(any("cabina guard" in h["command"] for grp in d["hooks"]["PreToolUse"] for h in grp["hooks"]))
            self.assertTrue(any("cabina brief" in h["command"] for grp in d["hooks"]["SessionStart"] for h in grp["hooks"]))
            self.assertTrue(r["status"]["guard_installed"]); self.assertTrue(r["status"]["brief_installed"])
            with mock.patch("cabina.guard.shutil.which", return_value="/usr/local/bin/cabina"):
                code2, r2 = self.post("/api/hooks-install", {"cmd": "cabina"})
            self.assertTrue(r2["ok"], r2)
            self.assertTrue(any(f.startswith("settings.json.bak-") for f in os.listdir(self.env.claude)))   # 2nd write backs up the 1st
            d2 = json.load(open(settings))
            self.assertEqual(sum(1 for grp in d2["hooks"]["PreToolUse"] for h in grp["hooks"] if "cabina guard" in h["command"]), 1)
        finally:
            if os.path.isfile(settings):
                os.remove(settings)
            for f in os.listdir(self.env.claude):
                if f.startswith("settings.json.bak-"):
                    os.remove(os.path.join(self.env.claude, f))

    def test_hooks_install_requires_token(self):
        code, _ = self.post("/api/hooks-install", {"cmd": "cabina"}, token="wrong")
        self.assertEqual(code, 403)

    # ---------- S2-c: Harness tab, Cabina hooks panel ----------
    def test_hooks_block_fields_always_escaped(self):
        import re
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("// ---------- HOOKS ----------")
        end = html.index("// ---------- DOCS ----------")
        body = html[start:end]
        pattern = re.compile(r"\$\{([^{}]*\b(?:s\.(?:settings_path|cmd_path|error)|j\.message)\b[^{}]*)\}")
        hits = list(pattern.finditer(body))
        self.assertGreater(len(hits), 0)
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")

    def test_hooks_install_button_hidden_in_hub_mode_by_source_guard(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn('HUB?"":renderHooksPanel()', html)

    def test_health_i18n_keys_present_in_both_languages(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("const I18N={")
        end = html.index("const T=(k,v)=>")
        block = html[start:end]
        split = block.index("\nes:{")
        en_block, es_block = block[:split], block[split:]
        for key in ("health", "recheck", "checking", "ranAt", "copy", "copied", "healthOk", "sevCrit", "sevWarn", "sevInfo"):
            self.assertIn(key + ":", en_block, key)
            self.assertIn(key + ":", es_block, key)
if __name__ == "__main__": unittest.main()
