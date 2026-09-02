import copy, json, os, threading, time, unittest, urllib.request
import _helpers  # noqa
from _env import Env
from project_os import server, scan
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
                                     headers={"Content-Type": "application/json", "X-ProjectOS-Token": token if token is not None else self.app.token})
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
    def _views_parts(self, html):
        # (hub_part, nonhub_part) of the `const VIEWS=HUB?[...]:[...]` line -- asserting against
        # this line specifically (not the whole document) is what makes these tests able to go
        # red: a tab id also appears in i18n/LOADERS/render()/the fetch call even when missing
        # from VIEWS itself, so a bare `assertIn(id, html)` never catches a tab dropped from VIEWS.
        start = html.index("const VIEWS=")
        end = html.index(";", start)
        hub_part, nonhub_part = html[start:end].split(":", 1)
        return hub_part, nonhub_part
    def test_index_has_activity_tab(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        hub_part, nonhub_part = self._views_parts(html)
        self.assertIn('"activity"', hub_part); self.assertIn('"activity"', nonhub_part)   # in BOTH arrays
        self.assertIn("/api/activity", html)
    def test_index_has_mcp_tab(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        hub_part, nonhub_part = self._views_parts(html)
        self.assertIn('"mcp"', nonhub_part)          # full mode: has the tab
        self.assertNotIn('"mcp"', hub_part)          # hub mode: local-only by omission
        self.assertIn("/api/mcp", html)
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
        from project_os import usage
        from unittest import mock
        tdir = os.path.join(self.env.alpha, ".claude", "skills", "throwaway")
        os.makedirs(tdir, exist_ok=True)
        open(os.path.join(tdir, "SKILL.md"), "w").write("---\nname: throwaway\ndescription: t\n---\n")
        self.app._skills = None                      # force a real recompute inside the patched block below
        with mock.patch("project_os.server.usage.refresh", wraps=usage.refresh) as m:
            s1 = self.get("/api/skills")
            self.assertTrue(any(x["name"] == "throwaway" for x in s1["skills"]))
            self.get("/api/skills")
            self.assertEqual(m.call_count, 1)                 # second GET served from cache: no re-refresh
            code, r = self.post("/api/archive-skill", {"name": "throwaway", "path": tdir, "project": "alpha"})
            self.assertTrue(r["ok"], r)
            s2 = self.get("/api/skills")
            self.assertEqual(m.call_count, 2)                 # archive invalidated the cache: refreshes again
            self.assertFalse(any(x["name"] == "throwaway" for x in s2["skills"]))
    def test_projects_endpoint_caches_codex_sessions_walk(self):
        # api_projects called usage.codex_sessions() (an os.walk over every Codex session file)
        # on EVERY GET, unlike api_agents' cached, TTL'd roster(). Mirror that pattern: two
        # consecutive GETs must walk Codex sessions only once.
        from project_os import usage
        from unittest import mock
        self.app._codex = None                        # force a real recompute inside the patched block below
        with mock.patch("project_os.server.usage.codex_sessions", wraps=usage.codex_sessions) as m:
            self.get("/api/projects")
            self.get("/api/projects")
            self.assertEqual(m.call_count, 1)          # second GET served from cache: no re-walk
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
        with mock.patch("project_os.server.scan.run", side_effect=fake_run), mock.patch("project_os.server.scan.save"):
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
        with mock.patch("project_os.server.scan.run", side_effect=slow_run), mock.patch("project_os.server.scan.save"):
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
        with mock.patch("project_os.server.scan.run", return_value=marker), mock.patch("project_os.server.scan.save"):
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
        with mock.patch("project_os.server.scan.run", side_effect=boom):
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
        for k in ("project_os", "machine", "agents", "skills", "projects"): self.assertIn(k, body)
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
        self.assertEqual(p["projects"][0]["codex_last"], "2026-08-04")   # from the synthetic Codex session cwd'd into alpha
        h = self.get("/api/harness"); self.assertEqual(h["states"][0]["hooks_dead"], ["dead.sh"])
        self.assertEqual(h["drift"]["twins"][0]["status"], "same")                       # reviewer.md ≡ reviewer.toml
        # beta-codex-only is the solo-Codex project fixture (AGENTS.md, no CLAUDE.md): drift
        # correctly classifies it "only-agents" now that scan.py discovers it as a project.
        self.assertEqual({x["project"]: x["status"] for x in h["drift"]["rules"]},
                          {"alpha": "diverged", "beta-codex-only": "only-agents"})
        d = self.get("/api/docs"); self.assertTrue(any(x["rel"] == ".claude/MEMORY.md" for x in d["docs"]))
        l = self.get("/api/live"); self.assertFalse(l["ok"]); self.assertEqual(l["provider"], "none")
    def test_skill_body_endpoint(self):
        d = self.get("/api/skill-body?tool=claude&project=alpha&name=deploy")
        self.assertTrue(d["ok"], d)
        self.assertIn("name: deploy", d["content"])
        self.assertTrue(any(f["path"] == "SKILL.md" for f in d["files"]))
    def test_skill_body_unknown_skill(self):
        d = self.get("/api/skill-body?tool=claude&project=alpha&name=does-not-exist")
        self.assertFalse(d["ok"])
    def test_skill_file_rejects_traversal(self):
        # The escape target must actually EXIST as a sibling of the skill dir -- otherwise
        # "not a file" would also produce ok:False even with the confinement guard deleted,
        # and the test could never go red.
        outside = os.path.join(self.env.alpha, ".claude", "skills", "outside.txt")
        open(outside, "w").write("secret")
        try:
            d = self.get("/api/skill-file?tool=claude&project=alpha&name=deploy&path=../outside.txt")
            self.assertFalse(d["ok"])
            self.assertEqual(d["message"], "path outside the skill")
        finally:
            os.remove(outside)
    def test_skill_file_null_byte_returns_ok_false_not_500(self):
        d = self.get("/api/skill-file?tool=claude&project=alpha&name=deploy&path=%00")
        self.assertFalse(d["ok"])
    def test_find_skill_returns_none_when_ambiguous(self):
        from unittest import mock
        rows = [{"tool": "claude", "project": "alpha", "name": "dup", "path": "/a"},
                {"tool": "claude", "project": "alpha", "name": "dup", "path": "/b"}]
        with mock.patch.object(self.app, "skills", return_value=(rows, {})):
            row = self.app._find_skill({"tool": ["claude"], "project": ["alpha"], "name": ["dup"]})
        self.assertIsNone(row)
    def test_activity_endpoint_serves_cache(self):
        from project_os import sessions as SESS
        SESS.refresh(self.env.cfg)                      # populate the cache once, synchronously, for the test
        d = self.get("/api/activity?days=30")
        self.assertTrue(any(s["project"] == "alpha" for s in d["sessions"]))
        self.assertIn("active_seconds", d)
        d2 = self.get("/api/activity?project=alpha&days=30")
        self.assertTrue(d2["sessions"]); self.assertTrue(all(s["project"] == "alpha" for s in d2["sessions"]))
    def test_activity_endpoint_filters_by_days(self):
        # H3(i): api_activity received `days` but returned EVERY cached session regardless
        # (measured: identical payload size for days=7 and days=365). Filter by `started`.
        from project_os import sessions as SESS
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
    def test_activity_endpoint_serves_cwd_and_source_path_deliberately(self):
        # INTENT, not accident: cwd and source_path are LOCAL-ONLY fields (sessions.py:50,
        # SUMMARY_FIELDS) -- absolute filesystem paths on the operator's own machine. /api/activity
        # is project-os's own local UI (server.py binds loopback-only, guarded by the CSRF token),
        # never the hub/export surface (snapshot._detail_row is a separate whitelist that omits
        # both). If someone "fixes" this endpoint by dropping these fields, or copies this shape
        # into the hub or `project-os export`, that must be a conscious decision -- not a refactor
        # that quietly leaks local paths into a shared snapshot, or quietly breaks whatever in the
        # UI reads sessKey()'s x.source_path. This test exists to force that decision to be made
        # on purpose.
        from project_os import sessions as SESS
        SESS.refresh(self.env.cfg)
        d = self.get("/api/activity?days=30")
        self.assertTrue(d["sessions"])
        for s in d["sessions"]:
            self.assertIn("cwd", s)
            self.assertIn("source_path", s)
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
        headers = {"Host": "evil.example", "Content-Type": "application/json", "X-ProjectOS-Token": self.app.token}
        code, body = self._raw("POST", "/api/open", headers=headers, body=json.dumps({"path": "/tmp"}).encode())
        self.assertEqual(code, 421)
        self.assertFalse(json.loads(body)["ok"])
    def test_post_with_bad_origin_rejected_even_with_valid_token(self):
        headers = {"Host": f"127.0.0.1:{self.port}", "Origin": "http://evil.example",
                   "Content-Type": "application/json", "X-ProjectOS-Token": self.app.token}
        code, body = self._raw("POST", "/api/open", headers=headers, body=json.dumps({"path": "/tmp"}).encode())
        self.assertEqual(code, 403)
        self.assertFalse(json.loads(body)["ok"])
    def test_post_with_loopback_origin_allowed(self):
        from unittest import mock
        with mock.patch("project_os.server.host.open_path", return_value=(True, "opened")):
            headers = {"Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}",
                       "Content-Type": "application/json", "X-ProjectOS-Token": self.app.token}
            code, body = self._raw("POST", "/api/open", headers=headers,
                                    body=json.dumps({"path": self.env.alpha}).encode())
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])
    def test_post_origin_matching_configured_bind_host_allowed(self):
        # Local-only is the trust boundary: a LAN bind/origin is never accepted, even when it
        # matches the configured value. The TEST server still binds 127.0.0.1 so this suite can
        # talk to it; only cfg["server"]["host"] differs.
        import copy, http.client, threading
        from http.server import ThreadingHTTPServer
        from unittest import mock
        from project_os import server as SRV
        cfg2 = copy.deepcopy(self.env.cfg)
        cfg2["server"]["host"] = "10.0.0.5"
        app2 = SRV.App(cfg2)
        srv2 = ThreadingHTTPServer(("127.0.0.1", 0), SRV.make_handler(app2))
        port2 = srv2.server_address[1]
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        try:
            with mock.patch("project_os.server.host.open_path", return_value=(True, "opened")):
                conn = http.client.HTTPConnection("127.0.0.1", port2)
                headers = {"Host": f"127.0.0.1:{port2}", "Origin": "http://10.0.0.5:1234",
                           "Content-Type": "application/json", "X-ProjectOS-Token": app2.token}
                conn.request("POST", "/api/open", body=json.dumps({"path": app2.cfg["claude_home"]}).encode(), headers=headers)
                r = conn.getresponse(); code = r.status; body = json.loads(r.read()); conn.close()
            self.assertEqual(code, 403, body)          # non-loopback Origin: refused
            conn = http.client.HTTPConnection("127.0.0.1", port2)
            headers2 = {"Host": f"127.0.0.1:{port2}", "Origin": "http://evil.example",
                        "Content-Type": "application/json", "X-ProjectOS-Token": app2.token}
            conn.request("POST", "/api/open", body=json.dumps({"path": "/tmp"}).encode(), headers=headers2)
            r2 = conn.getresponse(); code2 = r2.status; r2.read(); conn.close()
            self.assertEqual(code2, 403)               # still refuses a genuinely foreign origin
        finally:
            srv2.shutdown(); srv2.server_close()

    def test_non_loopback_host_and_origin_are_never_allowed(self):
        self.assertFalse(server.host_allowed("10.0.0.5:8930", "10.0.0.5"))
        self.assertFalse(server.host_allowed("[2001:db8::5]:8930", "2001:db8::5"))
        self.assertFalse(server.origin_allowed("http://10.0.0.5:8930", "10.0.0.5"))

    def test_serve_rejects_non_loopback_before_constructing_server(self):
        from unittest import mock
        cfg = copy.deepcopy(self.env.cfg)
        cfg["server"]["host"] = "10.0.0.5"
        with mock.patch.object(server, "App") as app, mock.patch.object(server, "ThreadingHTTPServer") as http:
            with self.assertRaises(ValueError):
                server.serve(cfg, port=0, open_browser=False)
        app.assert_not_called()
        http.assert_not_called()
    # ---------- /api/open path confinement ----------
    def test_open_outside_roots_refused_and_never_calls_host_open_path(self):
        from unittest import mock
        with mock.patch("project_os.server.host.open_path") as m:
            code, r = self.post("/api/open", {"path": "/tmp"})
        self.assertFalse(r["ok"], r)
        self.assertIn("outside", r["message"])
        m.assert_not_called()
    def test_open_inside_project_root_allowed(self):
        from unittest import mock
        with mock.patch("project_os.server.host.open_path", return_value=(True, "opened")) as m:
            code, r = self.post("/api/open", {"path": os.path.join(self.env.alpha, "CLAUDE.md")})
        self.assertTrue(r["ok"], r)
        m.assert_called_once()

    def test_archive_skill_uses_fresh_canonical_identity_not_body_path(self):
        from unittest import mock
        import shutil
        victim = os.path.join(self.env.tmp.name, "victim.txt")
        open(victim, "w").write("do not touch")
        name = "archive-canonical-only"
        skill = os.path.join(self.env.alpha, ".claude", "skills", name)
        os.makedirs(skill)
        open(os.path.join(skill, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: temporary\n---\n")
        try:
            # Deliberately poison the in-memory catalog: the archive identity must be resolved
            # from the current filesystem catalog, never from this stale path or the POST body.
            self.app._skills = ([{"name": name, "project": "alpha", "path": victim,
                                  "state": "ok"}], {"stale": True})
            self.app._skills_t = time.time()
            with mock.patch.object(server.SK, "archive_path", wraps=server.SK.archive_path) as archive:
                code, r = self.post("/api/archive-skill", {"name": name, "project": "alpha", "path": victim})
            self.assertTrue(r["ok"], r)
            self.assertEqual(open(victim).read(), "do not touch")
            archive.assert_called_once()
            self.assertEqual(os.path.realpath(archive.call_args.args[0]), os.path.realpath(skill))
        finally:
            shutil.rmtree(skill, ignore_errors=True)

    def test_archive_skill_rejects_unknown_identity_and_does_not_use_body_path(self):
        victim = os.path.join(self.env.tmp.name, "victim-unknown.txt")
        open(victim, "w").write("keep")
        r = self.app.api_archive_skill({"name": "does-not-exist", "project": "alpha", "path": victim})
        self.assertFalse(r["ok"])
        self.assertEqual(open(victim).read(), "keep")
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
        with mock.patch("project_os.server.host.open_terminal") as m:
            code, r = self.post("/api/open-terminal", {"path": "/tmp"})
        self.assertFalse(r["ok"], r)
        m.assert_not_called()
    def test_open_terminal_refuses_a_file(self):
        from unittest import mock
        with mock.patch("project_os.server.host.open_terminal") as m:
            code, r = self.post("/api/open-terminal", {"path": os.path.join(self.env.alpha, "CLAUDE.md")})
        self.assertFalse(r["ok"], r)
        m.assert_not_called()
    def test_open_terminal_inside_project_root_allowed(self):
        from unittest import mock
        with mock.patch("project_os.server.host.open_terminal", return_value=(True, "opened")) as m:
            code, r = self.post("/api/open-terminal", {"path": self.env.alpha})
        self.assertTrue(r["ok"], r)
        m.assert_called_once()
    def test_open_terminal_requires_token(self):
        from unittest import mock
        with mock.patch("project_os.server.host.open_terminal") as launcher:
            code, _ = self.post("/api/open-terminal", {"path": self.env.alpha}, token="wrong")
        self.assertEqual(code, 403)
        launcher.assert_not_called()
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
        # W3: project-os never runs `git worktree remove`/prune itself -- the script is only ever
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
        # rows no longer render sizes (bare worktree count since the lanes redesign). The three
        # surviving uses of worktrees_mb all sit behind the measured-guard (footer total, dot
        # threshold, dot evidence sentence); any NEW unguarded use fails the count below.
        self.assertIn("x.worktrees_mb_measured&&x.worktrees_mb>5000", body)
        self.assertIn("x.worktrees_mb_measured?x.worktrees_mb:0", body)
        self.assertIn('T("dotWt",{gb:(x.worktrees_mb/1024', body)
        import re as _re
        self.assertEqual(len(_re.findall(r"x\.worktrees_mb(?!_measured)", body)), 3)
        # footer: GB total only when every project with worktrees was measured, the
        # wtSizeUnmeasured words otherwise (one unknown vocabulary, never a "? GB" glyph),
        # and omitted entirely when nothing has worktrees at all (no more unconditional "(0.0 GB)")
        self.assertIn("wtMeasured?wtG.toFixed(1)", body)
        self.assertIn('esc(T("wtSizeUnmeasured"))', body)
        self.assertNotIn('"? GB"', body)
        self.assertIn("wtProjects.length?", body)
        # the red/amber dot must never trigger the size condition on an unmeasured project
        self.assertIn("x.worktrees_mb_measured&&x.worktrees_mb>5000", body)
        self.assertNotIn('x.worktrees_mb>5000?"invalid"', body)   # the old, ungated heuristic
    # ---------- MCP tab: /api/mcp ----------
    def test_mcp_endpoint_shape_ordering_and_counts(self):
        orig_data = self.app.data
        try:
            self.app.data = copy.deepcopy(orig_data)
            self.app.data["mcp"] = {"checked": True, "servers": [
                {"name": "z-ok", "target": "https://ok.example/mcp", "status": "ok", "detail": "Connected"},
                {"name": "a-failed", "target": "https://failed.example/mcp", "status": "failed", "detail": "Refused"},
                {"name": "m-unverified", "target": "https://unv.example/mcp", "status": "unverified", "detail": "Unverified"},
                {"name": "b-auth", "target": "https://auth.example/mcp", "status": "auth", "detail": "Needs authentication"},
            ]}
            d = self.get("/api/mcp")
            self.assertTrue(d["checked"])
            self.assertEqual([s["status"] for s in d["servers"]], ["failed", "auth", "unverified", "ok"])
            self.assertEqual(d["counts"], {"ok": 1, "auth": 1, "unverified": 1, "failed": 1, "total": 4})
            self.assertEqual({s["name"] for s in d["servers"]}, {"z-ok", "a-failed", "m-unverified", "b-auth"})
        finally:
            self.app.data = orig_data
    def test_mcp_endpoint_unchecked_returns_false_and_zeroed_counts_never_raises(self):
        orig_data = self.app.data
        try:
            self.app.data = copy.deepcopy(orig_data)
            self.app.data["mcp"] = {"checked": False, "servers": []}
            d = self.get("/api/mcp")
            self.assertFalse(d["checked"])
            self.assertEqual(d["servers"], [])
            self.assertEqual(d["counts"], {"ok": 0, "auth": 0, "unverified": 0, "failed": 0, "total": 0})
            del self.app.data["mcp"]                     # missing key entirely: still no KeyError
            d2 = self.get("/api/mcp")
            self.assertFalse(d2["checked"])
            self.assertEqual(d2["counts"]["total"], 0)
        finally:
            self.app.data = orig_data
    def test_mcp_block_fields_always_escaped(self):
        # name/target/detail are raw text: every interpolation of them must go through esc().
        # status is additionally used as a CSS-class lookup key (`cls[x.status]`, mirroring the
        # Health tab's healthSevClass(f.sev) precedent) -- that's a safe, enum-constrained lookup,
        # not a text interpolation, so it's checked separately below rather than by the blanket regex.
        import re
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("// ---------- MCP ----------")
        end = html.index("// ---------- DOCS ----------")
        body = html[start:end]
        pattern = re.compile(r"\$\{([^{}]*\bx\.(?:name|target|detail)\b[^{}]*)\}")
        hits = list(pattern.finditer(body))
        self.assertGreater(len(hits), 0)
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
        self.assertIn("esc(x.status)", body)          # the visible status label is escaped too
        self.assertIn("cls[x.status]", body)           # the class suffix comes from a lookup table, never x.status raw
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
    # ---------- doc versions: /api/doc-versions, /api/doc-version ----------
    def test_doc_versions_endpoint_shape_and_unknown_doc_returns_empty_list(self):
        d = self.get("/api/doc?project=alpha&rel=CLAUDE.md"); self.assertTrue(d["ok"])
        code, r = self.post("/api/save-doc", {"project": "alpha", "rel": "CLAUDE.md",
                                               "content": d["content"] + "\nversions-test\n", "hash": d["hash"]})
        self.assertTrue(r["ok"], r)
        vs = self.get("/api/doc-versions?project=alpha&rel=CLAUDE.md")
        self.assertIn("versions", vs); self.assertTrue(vs["versions"])
        v0 = vs["versions"][0]
        for k in ("stamp", "iso", "size", "ambiguous"): self.assertIn(k, v0)
        self.assertTrue(v0["ambiguous"])   # CLAUDE.md is root-level: the flat backup dir is shared
        missing = self.get("/api/doc-versions?project=alpha&rel=NOPE.md")
        self.assertEqual(missing["versions"], [])   # unknown doc: empty list, never an error
    def test_doc_version_endpoint_bad_stamp_rejected(self):
        bad = self.get("/api/doc-version?project=alpha&rel=CLAUDE.md&stamp=not-a-stamp")
        self.assertFalse(bad["ok"])
        self.assertIn("message", bad)
        blank = self.get("/api/doc-version?project=alpha&rel=CLAUDE.md&stamp=")
        self.assertFalse(blank["ok"])
    def test_doc_version_endpoint_diff_and_command_present(self):
        d = self.get("/api/doc?project=alpha&rel=CLAUDE.md"); self.assertTrue(d["ok"])
        code, r = self.post("/api/save-doc", {"project": "alpha", "rel": "CLAUDE.md",
                                               "content": d["content"] + "\ndiff-test\n", "hash": d["hash"]})
        self.assertTrue(r["ok"], r)
        vs = self.get("/api/doc-versions?project=alpha&rel=CLAUDE.md")
        stamp = vs["versions"][0]["stamp"]
        good = self.get(f"/api/doc-version?project=alpha&rel=CLAUDE.md&stamp={stamp}")
        self.assertTrue(good["ok"], good)
        self.assertIn("diff", good)
        self.assertTrue(good["diff"].strip())          # non-empty: stored version differs from current
        self.assertIn("command", good)
        self.assertIsNotNone(good["command"])          # normal temp-dir paths are safe to embed
        self.assertIn("CLAUDE.md", good["command"])
    def test_doc_version_endpoint_unsafe_path_never_emits_a_command(self):
        # W3-style guard, mirrored for docs: a path containing a shell metacharacter must never
        # be handed to the user as a pasteable command.
        from unittest import mock
        with mock.patch("project_os.server.WT._is_unsafe", return_value=True):
            d = self.get("/api/doc?project=alpha&rel=CLAUDE.md"); self.assertTrue(d["ok"])
            code, r = self.post("/api/save-doc", {"project": "alpha", "rel": "CLAUDE.md",
                                                   "content": d["content"] + "\nunsafe-test\n", "hash": d["hash"]})
            self.assertTrue(r["ok"], r)
            vs = self.get("/api/doc-versions?project=alpha&rel=CLAUDE.md")
            stamp = vs["versions"][0]["stamp"]
            got = self.get(f"/api/doc-version?project=alpha&rel=CLAUDE.md&stamp={stamp}")
        self.assertTrue(got["ok"], got)
        self.assertIsNone(got["command"])
        self.assertIn("command_reason", got)
    def test_commit_endpoint_requires_repo_and_only_that_path(self):
        import subprocess
        a = self.env.alpha
        subprocess.run(["git", "init", "-q", a], check=True)
        subprocess.run(["git", "-C", a, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        r = self.get("/api/in-repo?path=" + os.path.join(a, "CLAUDE.md")); self.assertTrue(r["in_repo"])
        d = self.get("/api/doc?project=alpha&rel=CLAUDE.md")
        self.post("/api/save-doc", {"project": "alpha", "rel": "CLAUDE.md", "content": "# alpha 3\n", "hash": d["hash"]})
        code, r = self.post("/api/commit", {"path": os.path.join(a, "CLAUDE.md"), "message": "project-os: edit CLAUDE.md"})
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
        for field in ('esc(x.started||"—")', r'(x.files_touched||[]).map(esc).join("\n")'):
            self.assertIn(field, body, f"activity field sink changed: {field}")
    def test_activity_entrypoint_fields_always_escaped(self):
        # New in this unit: entrypoint is raw data straight from a transcript file (sessions.py),
        # surfaced as a filter-chip label/attribute (built from the map key `v`) and a per-row
        # column (`x.entrypoint`). The field list in test_activity_and_hub_fields_always_escaped
        # above predates this field, so it is checked separately here. Scoped tightly to the
        # epChips.map(...) statement for `v` (a single-letter name reused harmlessly elsewhere in
        # this file, e.g. the timeline sparkline and the unrelated tool_calls map, so a bare
        # \bv\b scan over the whole ACTIVITY section would false-positive on those).
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        import re
        start = html.index("// ---------- ACTIVITY ----------")
        end = html.index("// ---------- PROJECTS ----------")
        body = html[start:end]
        chip_start = body.index("epChips.map(([v,n])")
        chip_end = body.index(";", body.index("chipFocus()", chip_start))
        chip_snippet = body[chip_start:chip_end]
        # the chip's "on"/"off" class only ever resolves to one of those two fixed literals — v
        # itself is never written into HTML there, so it is not an escaping concern. Whitelisted
        # by exact substring (same idiom as the git-message whitelist above) so any other change
        # to this line is still caught.
        on_off_ternary = 'S.chips.has("ep:"+v)?"on":""'
        self.assertIn(on_off_ternary, chip_snippet, "chip on/off ternary moved; update whitelist")
        chip_snippet = chip_snippet.replace(on_off_ternary, "")
        chip_pattern = re.compile(r"\$\{([^{}]*\bv\b[^{}]*)\}")
        chip_hits = list(chip_pattern.finditer(chip_snippet))
        self.assertGreater(len(chip_hits), 0)                # sanity: the chip line actually interpolates v
        for m in chip_hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
        row_pattern = re.compile(r"\$\{([^{}]*\bx\.entrypoint\b[^{}]*)\}")
        row_hits = list(row_pattern.finditer(body))
        self.assertGreater(len(row_hits), 0)                 # sanity: the row actually interpolates x.entrypoint
        for m in row_hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
    def test_session_detail_reasoning_unknown_guard(self):
        # Defends the "unknown, not zero" rule: tokens.thinking_lines did not exist before
        # 2026-08-12, and hub-detail exports never carry thinking/thinking_lines at all
        # (snapshot._detail_row is a whitelist that omits them). thinking_lines===0 must mean
        # "this file cannot tell us", never "no reasoning happened" — rendering a bare 0 there
        # would be a fabricated measurement. Asserts the actual conditional guard is present, not
        # merely the word "thinking" (which also appears in the tokReasoning i18n key), so
        # replacing the guard with an unconditional fmtNum(tThink) makes this go red.
        # Uses the dedicated tokNa key ("n/a"/"n/d"), not tokNd (whose value is the inline suffix
        # "· tokens n/a" used elsewhere in the harness run log) -- tokNd in a label/value meta grid
        # rendered as "reasoning  · tokens n/a", a value starting with a stray bullet.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn('tLines>0?fmtNum(tThink):T("tokNa")', html)
        self.assertNotIn('tLines>0?fmtNum(tThink):T("tokNd")', html)
    def test_session_detail_cache_rate_divide_by_zero_guard(self):
        # Defends: cache_read/(in+cache_read+cache_write) must never divide by zero (a session
        # with no token usage recorded at all, in+cache_read+cache_write===0) — asserts the guard
        # expression itself, not just that a "cache rate" label exists somewhere on the page.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn('denom>0?Math.round(tCR/denom*100)+"%":"—"', html)
    def test_session_detail_subagent_tokens_shown_only_when_subagents_used(self):
        # subagent_tokens is a SEPARATE aggregate from the session's own tokens (sessions.py R3:
        # never summed together) and was invisible in the UI. Must render only when x.subagents>0
        # -- a session with none must not show a zero row for tokens no subagent ever spent.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("if(x.subagents>0){", html)
        self.assertIn("x.subagent_tokens", html)
        self.assertIn('T("subagentTokens")', html)
        # hub-detail rows never carry subagent_tokens at all (snapshot._detail_row omits it),
        # so each field must fall back to tokNa individually rather than fmtNum(undefined),
        # which renders as a fabricated "0". Assert the actual per-field guard, not just that
        # the word "subagentTokens" is present.
        start = html.index("if(x.subagents>0){")
        end = html.index("$(\"detail\").innerHTML=h;", start)
        block = html[start:end]
        for field in ("st.in", "st.cache_read", "st.cache_write", "st.out"):
            self.assertIn(f'{field}!=null?fmtNum({field}):esc(T("tokNa"))', block)
    def test_activity_top_files_block_respects_focus_and_top_ten(self):
        # Client-side only, over sessions already in S.activity -- no new endpoint. Must respect
        # project focus (same as every other Activity row) and cap at 10.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("function topFilesHtml(sessions)")
        end = html.index("function renderActivity()", start)
        fn = html[start:end]
        self.assertIn("!S.focus||x.project===S.focus", fn)
        self.assertIn(".slice(0,10)", fn)
        self.assertIn("files_touched", fn)
        self.assertIn("topFilesHtml(a)", html)
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
        # (`project-os: archive ${x.name} (${x.project})`), never into innerHTML — not an escaping
        # concern. Whitelisted by exact substring so any other change to this block is still caught.
        git_message = "`project-os: archive ${x.name} (${x.project})`"
        self.assertIn(git_message, body, "git message literal moved; update whitelist")
        body = body.replace(git_message, "")
        pattern = re.compile(r"\$\{([^{}]*\bx\.(?:title|project|machine|branch|desc|description|name)\b[^{}]*)\}")
        hits = list(pattern.finditer(body))
        self.assertGreater(len(hits), 0)                    # sanity: the section actually interpolates these fields
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
        for field in ('esc(x.model||"—")', 'esc(x.tools||"—")',
                      '(x.critical||[]).map(c=>`<li>${esc(c)}</li>`)',
                      '(x.warnings||[]).map(c=>`<li>${esc(c)}</li>'):
            self.assertIn(field, body, f"agent field sink changed: {field}")
        agent_detail = html[html.index("function renderAgentDetail"):html.index("function renderArchive")]
        skill_detail = html[html.index("function renderSkillDetail"):html.index("// ---------- ACTIVITY ----------")]
        self.assertIn("esc(x.path)", agent_detail, "agent path sink changed")
        self.assertIn("esc(x.path)", skill_detail, "skill path sink changed")
        self.assertIn("esc(x.target)", skill_detail, "skill target sink changed")
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
        # x.name is only compared to select the fixed CSS class/text; it never enters the output
        # in these two ternaries. Keep this exact whitelist so field sinks remain covered.
        focus_ternary = '${S.focus===x.name?"focus":""}'
        self.assertIn(focus_ternary, body, "focus ternary moved; update whitelist")
        body = body.replace(focus_ternary, "")
        focus_button = '${S.focus===x.name?T("focusOff"):T("focusOn")}'
        self.assertIn(focus_button, body, "focus button ternary moved; update whitelist")
        body = body.replace(focus_button, "")
        pattern = re.compile(r"\$\{([^{}]*\b(?:x\.(?:title|project|machine|branch|name|last_commit)|f\.(?:name|machine|status))\b[^{}]*)\}")
        hits = list(pattern.finditer(body))
        self.assertGreater(len(hits), 0)
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
        self.assertIn('esc(x.last_commit||"—")', body)

    def test_harness_export_fields_always_escaped(self):
        # Harness export names, paths and runlog labels are data, while level is a CSS enum.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("// ---------- HARNESS ----------")
        end = html.index("// ---------- HOOKS ----------")
        body = html[start:end]
        for field in ("esc(e.name)", "esc(e.path)", "harnessClass(e.level)",
                      "esc(b.project)", "esc(b.path)", "esc(f.date)",
                      "esc(f.vehicle)", "esc(f.task)", "esc(f.agents)"):
            self.assertIn(field, body, f"harness field sink changed: {field}")
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
    def test_project_detail_last_codex_session_row_unknown_is_na_never_blank(self):
        # codex_last (api_projects) is null when Codex is absent or this project has no Codex
        # sessions -- the house "unknown" vocabulary (tokNa, reused from the memory_days row just
        # above it) must render, never an empty dash or a fabricated value.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn('T("codexLast")', html)
        self.assertIn('x.codex_last?esc(x.codex_last):T("tokNa")', html)
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
        with mock.patch("project_os.server.CHECK.run", side_effect=RuntimeError("boom")):
            d = self.get("/api/health")
        self.assertEqual(d["findings"], [])
        self.assertIn("boom", d["error"])
    def test_health_endpoint_includes_changes(self):
        # F2 "since last check": seed a baseline whose only identity cannot appear in a real run
        # ("check.nonexistent_marker"), so this call is guaranteed to report it resolved and to
        # report at least one new item (the fixture's real findings), regardless of test order.
        from project_os import healthlog as HL
        self.assertTrue(HL.append(self.env.cfg, [{"sev": "warn", "title": "x", "id": "check.nonexistent_marker"}]))
        d = self.get("/api/health")
        self.assertIn("changes", d)
        ch = d["changes"]
        self.assertIsNotNone(ch)
        resolved_ids = [i for i, _ in ch["resolved"]]
        self.assertIn("check.nonexistent_marker", resolved_ids)
        self.assertTrue(len(ch["new"]) > 0)
    # ---------- Fase 3: /api/health-history ----------
    def test_health_history_endpoint(self):
        from project_os import healthlog as HL
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
        with mock.patch("project_os.server.CHECK.run", side_effect=fake_run):
            self.get("/api/tiles")
        self.assertIn("quick", calls)
        self.assertFalse(calls["quick"])
    def test_health_totals_counts_each_finding_once_including_global_and_multi_project(self):
        # Unit fix: top-level `health` must count EVERY finding by severity exactly once --
        # including ones with no `projects` key (global findings, e.g. broken symlinks/MCP/stale
        # scan) -- never the SUM of per-tile attributed counts, which double-counts a finding
        # attributed to more than one project and drops global findings entirely.
        from project_os import server as SRV
        findings = [
            {"sev": "crit"},                          # global: no `projects` key at all
            {"sev": "warn", "projects": ["a", "b"]},   # attributed to two projects
            {"sev": "info", "projects": ["a"]},
            {"sev": "bogus"},                          # unknown severity: never counted
        ]
        self.assertEqual(SRV._health_totals(findings), {"crit": 1, "warn": 1, "info": 1})
    def test_project_tiles_order(self):
        from project_os import server as SRV
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
        # the tiles UI died with the lanes redesign, but the concern survives on its successor:
        # the projects renderer stays a read-only summary, never a Kanban.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("function renderProjects(){if(!S.projs)")
        end = html.index("function renderProjDetail(){")
        src = html[start:end]
        for bad in ("assignee", "todo", "\"status\"", "'status'"):
            self.assertNotIn(bad, src)
    def test_lanes_and_columns_i18n_keys_present_in_both_languages(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("const I18N={")
        end = html.index("const T=(k,v)=>")
        block = html[start:end]
        split = block.index("\nes:{")
        en_block, es_block = block[:split], block[split:]
        for key in ("colUncommitted", "colWorktrees", "colMemory", "colActivity", "laneLegend"):
            self.assertIn(key + ":", en_block, key)
            self.assertIn(key + ":", es_block, key)
    def test_new_addition_i18n_keys_present_in_both_languages(self):
        # Session subagent-token aggregate, Activity's top-files block and Projects' Last Codex
        # session row all added new I18N keys.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("const I18N={")
        end = html.index("const T=(k,v)=>")
        block = html[start:end]
        split = block.index("\nes:{")
        en_block, es_block = block[:split], block[split:]
        for key in ("subagentTokens", "topFiles", "topFilesN", "codexLast"):
            self.assertIn(key + ":", en_block, key)
            self.assertIn(key + ":", es_block, key)
    def test_projects_tab_no_longer_calls_tiles_or_health_history(self):
        # Lanes redesign: one representation. /api/tiles stays dead everywhere (a reappearance
        # means dead tiles code came back). /api/health-history is legitimately consumed again --
        # by the Health tab's 30-day trend (loadHealthHistory), not by Projects -- so this test is
        # scoped to the PROJECTS section only, same idiom as test_project_tiles_never_task_like_fields.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertNotIn("/api/tiles", html)
        self.assertNotIn("loadTiles", html)
        projects = html[html.index("// ---------- PROJECTS ----------"):html.index("// ---------- HARNESS ----------")]
        self.assertNotIn("/api/health-history", projects)
        self.assertIn("/api/health-history", html)             # confirms the Health tab still fetches it
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
        with mock.patch("project_os.guard.shutil.which", return_value=None):
            d = self.get("/api/hooks?cmd=definitely-not-a-real-cmd-xyz")
        self.assertFalse(d["cmd_resolves"])
        self.assertIsNone(d["cmd_path"])

    def test_hooks_install_refused_when_cmd_does_not_resolve_no_backup(self):
        from unittest import mock
        settings = os.path.join(self.env.claude, "settings.json")
        self.assertFalse(os.path.isfile(settings))
        with mock.patch("project_os.guard.shutil.which", return_value=None):
            code, r = self.post("/api/hooks-install", {"cmd": "project-os"})
        self.assertFalse(r["ok"], r)
        self.assertIn("not on PATH", r["message"])
        self.assertFalse(os.path.isfile(settings))
        self.assertFalse(any(f.startswith("settings.json.bak-") for f in os.listdir(self.env.claude)))

    def test_hooks_install_rejects_non_project_os_command_even_with_force(self):
        # U2: hooks may only ever run project-os -- a `bash -c '...'` payload must be refused
        # regardless of force=True (force only bypasses the "not on PATH" check).
        settings = os.path.join(self.env.claude, "settings.json")
        if os.path.isfile(settings):
            os.remove(settings)
        code, r = self.post("/api/hooks-install", {"cmd": "bash -c 'echo pwned'", "force": True})
        self.assertFalse(r["ok"], r)
        self.assertIn("project-os", r["message"])
        self.assertFalse(os.path.isfile(settings))

    def test_hooks_install_ok_and_idempotent(self):
        from unittest import mock
        settings = os.path.join(self.env.claude, "settings.json")
        try:
            with mock.patch("project_os.guard.shutil.which", return_value="/usr/local/bin/project-os"):
                code, r = self.post("/api/hooks-install", {"cmd": "project-os"})
            self.assertTrue(r["ok"], r)
            self.assertTrue(os.path.isfile(settings))
            d = json.load(open(settings))
            self.assertTrue(any("project-os guard" in h["command"] for grp in d["hooks"]["PreToolUse"] for h in grp["hooks"]))
            self.assertTrue(any("project-os brief" in h["command"] for grp in d["hooks"]["SessionStart"] for h in grp["hooks"]))
            self.assertTrue(r["status"]["guard_installed"]); self.assertTrue(r["status"]["brief_installed"])
            with mock.patch("project_os.guard.shutil.which", return_value="/usr/local/bin/project-os"):
                code2, r2 = self.post("/api/hooks-install", {"cmd": "project-os"})
            self.assertTrue(r2["ok"], r2)
            self.assertTrue(any(f.startswith("settings.json.bak-") for f in os.listdir(self.env.claude)))   # 2nd write backs up the 1st
            d2 = json.load(open(settings))
            self.assertEqual(sum(1 for grp in d2["hooks"]["PreToolUse"] for h in grp["hooks"] if "project-os guard" in h["command"]), 1)
        finally:
            if os.path.isfile(settings):
                os.remove(settings)
            for f in os.listdir(self.env.claude):
                if f.startswith("settings.json.bak-"):
                    os.remove(os.path.join(self.env.claude, f))

    def test_hooks_install_requires_token(self):
        code, _ = self.post("/api/hooks-install", {"cmd": "project-os"}, token="wrong")
        self.assertEqual(code, 403)

    # ---------- S2-c: Harness tab, Project-OS hooks panel ----------
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

    # ---------- Doc version history panel (UI) ----------
    def test_doc_versions_i18n_keys_present_in_both_languages(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("const I18N={")
        end = html.index("const T=(k,v)=>")
        block = html[start:end]
        split = block.index("\nes:{")
        en_block, es_block = block[:split], block[split:]
        for key in ("dvTitle", "dvAmbiguous", "dvNoDiff", "dvNoCommand", "dvLoadError", "dvRestoreCmd"):
            self.assertIn(key + ":", en_block, key)
            self.assertIn(key + ":", es_block, key)
    def test_doc_version_panel_fields_always_escaped(self):
        import re
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("// ---------- DOCS ----------")
        end = html.index("// ---------- LIVE ----------")
        body = html[start:end]
        # x.stamp is also used as a CSS-class lookup key (S.docVersionSel===x.stamp?"on":"")
        # -- a safe ternary comparison, not a text interpolation, mirroring the cls[x.status]
        # precedent in test_mcp_block_fields_always_escaped. Whitelisted by exact substring so
        # any OTHER change to that line is still caught; checked separately below.
        stamp_ternary = 'S.docVersionSel===x.stamp?"on":""'
        self.assertIn(stamp_ternary, body, "stamp ternary moved; update whitelist")
        self.assertIn('data-stamp="${esc(x.stamp)}"', body)   # the value itself IS escaped
        body_scan = body.replace(stamp_ternary, "")
        pattern = re.compile(r"\$\{([^{}]*\b(?:dd\.(?:diff|message|command|command_reason)|x\.iso)\b[^{}]*)\}")
        hits = list(pattern.finditer(body_scan))
        self.assertGreater(len(hits), 0)
        for m in hits:
            self.assertIn("esc(", m.group(1), f"unescaped interpolation: ${{{m.group(1)}}}")
    def test_doc_version_ambiguous_warning_rendered(self):
        # Defends the ambiguous-backup-folder warning: goes RED if renderVPanel stops checking
        # `x.ambiguous` or drops the dvAmbiguous string, not just if the word "ambiguous"
        # disappears anywhere in the document (it also lives in docs.py/test names).
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("function renderVPanel")
        end = html.index("async function selectDocVersion")
        body = html[start:end]
        self.assertIn("vs.some(x=>x.ambiguous)", body)
        self.assertIn('T("dvAmbiguous")', body)
    def test_doc_version_list_renders_human_readable_local_datetime_not_raw_iso(self):
        # Defends: the version list used to render x.iso verbatim
        # ("2026-08-15T14:30:12-06:00"), unreadable at a glance. fmtDT() must format it into a
        # local date+time string (still down to the second, so the exact instant a user would
        # need to pick the right version to restore stays unambiguous) using the same plain
        # "YYYY-MM-DD ..." style as the rest of the file (relSince/docs mtime), not a second
        # date convention. Asserts the actual construct, not just that "fmtDT" appears somewhere.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function fmtDT(iso)", html)
        fn_start = html.index("function fmtDT(iso)")
        fn_end = html.index("\n", fn_start)
        fn_body = html[fn_start:fn_end]
        for part in ("getFullYear()", "getMonth()", "getDate()", "getHours()", "getMinutes()", "getSeconds()"):
            self.assertIn(part, fn_body)
        start = html.index("function renderVPanel")
        end = html.index("async function selectDocVersion")
        body = html[start:end]
        self.assertIn("${esc(fmtDT(x.iso))}", body)
        self.assertNotIn("${esc(x.iso)}", body)
    def test_diff_lines_are_classified_added_removed_hunk(self):
        # Defends the diff coloring: +/-/@@ lines must be wrapped in dedicated classes built off
        # the EXISTING --moss/--rust/--dim variables (no new colours), and "+++"/"---" file
        # headers (which also start with +/-) must not be misclassified as content lines.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn(".dl-add{color:var(--moss)}", html)
        self.assertIn(".dl-del{color:var(--rust)}", html)
        self.assertIn(".dl-hunk{color:var(--dim)}", html)
        start = html.index("function diffLineHtml(diff)")
        end = html.index("\n", start)
        fn = html[start:end]
        self.assertIn('l.startsWith("+")&&!l.startsWith("+++")?"dl-add"', fn)
        self.assertIn('l.startsWith("-")&&!l.startsWith("---")?"dl-del"', fn)
        self.assertIn('l.startsWith("@@")?"dl-hunk"', fn)
        start = html.index("function renderVPanel")
        end = html.index("async function selectDocVersion")
        body = html[start:end]
        self.assertIn("dd.diff?diffLineHtml(dd.diff):esc(T(\"dvNoDiff\"))", body)
    def test_diff_line_rendering_escapes_content_before_styling(self):
        # The diff body is raw file content -- the highest-risk interpolation in this feature.
        # diffLineHtml must escape each line BEFORE it is ever wrapped in a <span>, so a line
        # like "+<script>" cannot break out of the <pre>. Breaking this (using the raw `l`
        # instead of the escaped `el` when building the span) is exactly the regression this
        # guards against.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("function diffLineHtml(diff)")
        end = html.index("\n", start)
        fn = html[start:end]
        self.assertIn("const el=esc(l)", fn)
        self.assertIn('`<span class="${cls}">${el}</span>`', fn)   # styled branch uses the escaped var
        self.assertNotIn("${l}", fn)                                # the raw line is never interpolated
    # ---------- Nested scroll containers (item 6): only .rows/.detail scroll independently ----------
    def test_only_two_pane_scroll_containers_plus_the_one_primary_content_cap(self):
        # F6 measurement: 4+ elements declaring their own max-height+overflow:auto at once, two
        # of which (list pane + detail pane) are the correct app-shell scroll regions and must
        # stay; everything else nested INSIDE the detail pane must flow with it instead of
        # opening its own inner scrollbar ("I scroll and the wrong thing moves").
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        # the two pane-level scrollers: kept, untouched
        self.assertIn(".rows{overflow-y:auto;flex:1}", html)
        self.assertIn('.detail{padding:18px 20px;display:flex;flex-direction:column;gap:14px;overflow-y:auto}', html)
        # the ONE primary-content cap inside .detail: kept (pre.doc/pre.preview, the document
        # preview itself -- without this cap the Edit/Open/Reload buttons below it would require
        # scrolling past an entire file first)
        self.assertIn("pre.doc,pre.preview{", html)
        self.assertIn("max-height:60vh;overflow:auto}", html)
        # small-screen tab strip fallback: kept, does not trigger at normal widths
        self.assertIn(".tabs{display:flex;gap:2px;padding:8px 14px 0;border-bottom:1px solid var(--line);background:var(--panel);overflow-x:auto}", html)
        # secondary blocks NESTED INSIDE the already-scrolling .detail pane must no longer pair
        # a max-height with overflow:auto -- they flow with the pane instead of opening their
        # own inner scrollbar. Checked as three independent constructs, not a blanket string
        # search, so any ONE of them silently regaining its own cap goes red on its own.
        self.assertIn('id="wtScript" style="margin-top:8px;max-height:none;overflow:visible"', html)
        self.assertNotIn('id="wtScript" style="margin-top:8px;max-height:200px"', html)
        self.assertIn('<pre class="doc" style="margin-top:6px;max-height:none;overflow:visible">${esc(x.diff)}</pre>', html)
        self.assertNotIn('<pre class="doc" style="margin-top:6px;max-height:200px">${esc(x.diff)}</pre>', html)
        self.assertIn('id="vDiff" style="margin-top:8px;max-height:none;overflow:visible"', html)
        # the version-history button list: no longer capped at 160px with its own scrollbar
        start = html.index("function renderVPanel")
        end = html.index("async function selectDocVersion")
        vpanel = html[start:end]
        self.assertIn('style="display:flex;flex-direction:column;gap:4px;margin-top:6px">', vpanel)
        self.assertNotIn("max-height:160px", vpanel)
        self.assertNotIn("overflow:auto", vpanel)
    def test_tiles_grid_fully_removed_by_lanes_redesign(self):
        # The tiles grid (and its deliberate 30vh scroll cap) died with the lanes redesign: one
        # representation per project. Any reappearance of these markers means the dead grid came
        # back without its old justification.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertNotIn(".tilesGrid{", html)
        self.assertNotIn("renderProjectTiles", html)
    # ---------- MCP tab: two-pane selection ----------
    def test_mcp_three_ui_states_still_render(self):
        # Do not weaken: the not-checked / empty / list branches from before this unit's
        # two-pane rework must all still be reachable.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("// ---------- MCP ----------")
        end = html.index("// ---------- DOCS ----------")
        body = html[start:end]
        self.assertIn("!d.checked", body); self.assertIn('T("mcpNotChecked")', body)
        self.assertIn("!d.servers.length", body); self.assertIn('T("mcpEmpty")', body)
        self.assertIn("d.servers.map(x=>", body)
    def test_mcp_detail_pane_shows_selected_server_fields_escaped(self):
        # The right-hand pane used to stay empty forever (F5). Selecting a row must populate it
        # with name/status/target/detail, following the S.sel + row/sel idiom used by the other
        # tabs, and a "pick a server" placeholder when nothing is selected yet.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("// ---------- MCP ----------")
        end = html.index("// ---------- DOCS ----------")
        body = html[start:end]
        self.assertIn("const cur=d.servers.find(y=>y.name===S.sel)", body)
        self.assertIn('T("pickMcp")', body)
        self.assertIn('S.sel=r.dataset.k', body)                # row click wires selection
        for field in ("esc(cur.name)", "esc(cur.status)", "esc(cur.target)", "esc(cur.detail)"):
            self.assertIn(field, body)
        self.assertIn('T("mcpTarget")', body)
    # ---------- Health tab: strip above the findings ----------
    def test_health_strip_reuses_live_and_activity_state_no_new_endpoint(self):
        # The owner rejected a separate Overview tab; Health gets a compact strip instead. Must
        # reuse S.live/S.activity and the existing loadLive/loadActivity loaders -- no new
        # /api route, and no re-fetch of what ensureLoaded already cached.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn("function healthStrip()", html)
        start = html.index("function healthStrip()")
        end = html.index("\n", html.index("return html", start))
        fn = html[start:end]
        self.assertIn("S.live", fn); self.assertIn("S.activity", fn)
        self.assertIn('T("healthActiveNow")', fn); self.assertIn('T("healthRecent")', fn)
        # findings themselves are never duplicated into the strip
        self.assertNotIn("f.title", fn); self.assertNotIn("f.detail", fn)
        self.assertIn("healthStrip()+body", html)
        self.assertIn('health:()=>{loadHealth();ensureLoaded("activity");}', html)
        self.assertIn('if(S.view==="health")renderHealth();', html)   # loadLive/loadActivity refresh it
        self.assertNotIn("/api/health-strip", html)                   # no new endpoint
    def test_health_strip_shows_quiet_line_for_nothing_active_and_omits_recent_before_loaded(self):
        # Never an empty box: no live provider or nobody working -> one quiet noLive/healthNoActive
        # line, never a blank <div>. And the recent-sessions half must be gated on S.activity being
        # loaded already (no skeleton flashed while ensureLoaded's fetch is still in flight).
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("function healthStrip()")
        end = html.index("\n", html.index("return html", start))
        fn = html[start:end]
        self.assertIn('(!live||!live.ok)?', fn)
        self.assertIn('T("healthNoActive")', fn)
        self.assertIn("if(S.activity){", fn)                          # recent half only once loaded
    def test_health_trend_fetched_once_and_rendered_honestly_below_two_points(self):
        # Fase 3's /api/health-history existed server-side with no consumer since the lanes
        # redesign (test_projects_tab_no_longer_calls_tiles_or_health_history above). The Health
        # tab is now that consumer: loadHealth() also kicks loadHealthHistory() (without touching
        # the LOADERS.health literal another test locks down), and healthTrendHtml() must refuse
        # to draw a "trend" out of fewer than two points.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        self.assertIn('async function loadHealthHistory(){S.healthHistory=await GET("/api/health-history?days=30")', html)
        self.assertIn("loadHealthHistory();", html)
        start = html.index("function healthTrendHtml()")
        end = html.index("\n", html.index("return ", start))
        fn = html[start:end]
        self.assertIn("series.length<2", fn)
        self.assertIn('T("healthTrendNone")', fn)
        self.assertIn("S.healthHistory", html)
    def test_health_i18n_keys_present_in_both_languages(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as r: html = r.read().decode()
        start = html.index("const I18N={")
        end = html.index("const T=(k,v)=>")
        block = html[start:end]
        split = block.index("\nes:{")
        en_block, es_block = block[:split], block[split:]
        for key in ("health", "recheck", "checking", "ranAt", "copy", "copied", "healthOk", "sevCrit", "sevWarn", "sevInfo",
                     "healthTrend", "healthTrendNone", "healthTrendAria"):
            self.assertIn(key + ":", en_block, key)
            self.assertIn(key + ":", es_block, key)
if __name__ == "__main__": unittest.main()
