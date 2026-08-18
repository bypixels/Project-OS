import json, os, threading, time, unittest, urllib.request
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
            if self.app._roster is None:
                break
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
            if self.app._roster is None:
                break
            time.sleep(0.02)
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
            code, r = self.post("/api/hooks-install", {"cmd": "definitely-not-a-real-cmd-xyz"})
        self.assertFalse(r["ok"], r)
        self.assertIn("not on PATH", r["message"])
        self.assertFalse(os.path.isfile(settings))
        self.assertFalse(any(f.startswith("settings.json.bak-") for f in os.listdir(self.env.claude)))

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
