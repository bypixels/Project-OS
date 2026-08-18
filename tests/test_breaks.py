"""Permanent break-tests: each test removes ONE guard in memory and asserts a canary
test would notice. If a guard is ever deleted from the code, these go red first."""
import os, tempfile, unittest
from datetime import datetime, timedelta
from unittest import mock
import _helpers  # noqa
from cabina import contract as C, docs as D, guard as G, harness as H, server as SRV, sessions as SESS, usage as U
from _env import Env

class TestBreaks(unittest.TestCase):
    def test_contract_kebab_guard(self):
        c = C.Contract()
        # name matches the filename, so ONLY the kebab rule can reject it
        txt = "---\nname: Bad Name\ndescription: d\nmodel: sonnet\ntools: Read\n---\nb"
        with mock.patch.object(C, "_KEBAB", __import__("re").compile(r"^[A-Za-z0-9 ]+$")):
            self.assertNotEqual(c.validate_text(txt, "Bad Name").category, "invalid")   # guard removed -> passes
        self.assertEqual(c.validate_text(txt, "Bad Name").category, "invalid")          # guard present -> caught
    def test_contract_severity_is_config_driven(self):
        c = C.Contract({"contract": {"critical": ["name", "description", "model"]}})
        self.assertEqual(c.validate_text("---\nname: x\ndescription: d\ntools: Read\n---\nb", "x").category, "invalid")
    def test_docs_hash_guard(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as b:
            open(os.path.join(t, "A.md"), "w").write("v1"); d = D.Docs({"p": t}, b)
            h = d.read("p", "A.md")["hash"]; open(os.path.join(t, "A.md"), "w").write("v2")
            self.assertFalse(d.save("p", "A.md", "mine", h)["ok"])
            with mock.patch.object(D, "_h", lambda s: "same"):          # guard disabled
                self.assertTrue(d.save("p", "A.md", "mine", "same")["ok"])
    def test_docs_allowlist_guard(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as b:
            d = D.Docs({"p": t}, b)
            self.assertFalse(d.read("p", "../x.md")["ok"])
            with mock.patch.object(D.Docs, "_resolve", lambda self, p, rel: (os.path.join(t, rel), None)):
                self.assertNotIn("outside", d.read("p", "../x.md").get("message", ""))
    def test_docs_working_guard(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as b:
            open(os.path.join(t, "A.md"), "w").write("v1"); d = D.Docs({"p": t}, b); h = d.read("p", "A.md")["hash"]
            self.assertFalse(d.save("p", "A.md", "x", h, working=["p"])["ok"])
            self.assertTrue(d.save("p", "A.md", "x", h, working=[])["ok"])
    def test_docs_backup_guard(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as b:
            open(os.path.join(t, "A.md"), "w").write("v1"); d = D.Docs({"p": t}, b); h = d.read("p", "A.md")["hash"]
            d.save("p", "A.md", "v2", h)
            self.assertEqual(sum(len(fn) for _, _, fn in os.walk(b)), 1)
    def test_harness_dead_hook_guard(self):
        with tempfile.TemporaryDirectory() as t:
            c = os.path.join(t, ".claude"); os.makedirs(os.path.join(c, "hooks")); open(os.path.join(c, "hooks", "x.sh"), "w").write("#")
            self.assertEqual(H.project_state(t)["hooks_dead"], ["x.sh"])
            with mock.patch.object(H, "_wired_hooks", lambda cdir: {"x.sh"}):
                self.assertEqual(H.project_state(t)["hooks_dead"], [])
    def test_usage_never_regresses(self):
        r = U.merge({"a": {"last": "2026-08-10", "n_total": 9}}, {"a": {"last": "2026-08-01", "n": 1}})
        self.assertEqual(r["a"]["last"], "2026-08-10")
    def test_usage_history_diff_guard(self):
        # si el registro por archivo se ignorara (se sumara el conteo bruto en vez del delta),
        # una relectura completa del mismo archivo duplicaría el conteo
        with mock.patch.object(U, "_file_delta", lambda new, old: new):   # guard disabled: delta = new, ignora old
            out = U._accumulate({"reviewer": {"n_total": 7}}, {"reviewer": {"n": 7}})   # ya se había contado
            self.assertEqual(out["reviewer"]["n_total"], 14)                             # duplicado -> canary red
        out2 = U._accumulate({"reviewer": {"n_total": 7}}, {"reviewer": {"n": 7}})       # guard presente
        self.assertEqual(out2["reviewer"]["n_total"], 7)                                 # sin cambio: ya estaba contado

    def test_usage_dual_output_single_pass_guard(self):
        # si refresh() solo actualizara la salida de SU kind (el bug original), el otro kind
        # perdería las invocaciones que aparecieron en la misma pasada.
        env = Env()
        try:
            p = os.path.join(env.state, "usage-agents.json")
            skills_path = os.path.join(env.state, "usage-skills.json")
            history_dir = os.path.join(env.claude, "projects")
            roots = {"alpha": env.alpha}
            env.append_usage_line(
                '{"timestamp":"2026-08-05T00:00:00Z","cwd":"%s","x":{"name":"Skill","input":{"skill":"deploy"}}}' % env.alpha)
            with mock.patch.object(U, "_save_sibling_output", lambda *a, **k: None):  # guard disabled: solo guarda el kind pedido
                U.refresh(p, history_dir, "agents", roots)
                skill_items = U.load(skills_path)
                self.assertNotIn("deploy", skill_items)                    # se perdio -> canary red
            U.refresh(p, history_dir, "agents", roots)                     # guard presente
            self.assertIn("deploy", U.load(skills_path))                   # no se perdio
        finally:
            env.cleanup()

    def test_usage_first_scan_finds_full_history_without_a_second_run_guard(self):
        # constraint (g): agents --unused (check.py, que lee usage.load() del cache) no puede
        # dar falsos positivos porque el registro nuevo este vacio. Con offsets, un archivo sin
        # entrada en usage-history.json se lee desde offset=0 — completo — asi que esto deberia
        # cumplirse "gratis" por construccion; este break-test lo deja demostrado, no asumido.
        env = Env()
        try:
            p = os.path.join(env.state, "usage-agents.json")
            history_dir = os.path.join(env.claude, "projects")
            roots = {"alpha": env.alpha}
            self.assertFalse(os.path.isfile(os.path.join(env.state, "usage-history.json")))
            self.assertFalse(os.path.isfile(p))
            with mock.patch.object(U, "_scan_file", lambda *a, **k: ({}, {}, 0)):   # guard disabled: "primer scan" roto
                items_broken, _ = U.refresh(p, history_dir, "agents", roots)
                self.assertNotIn("reviewer", items_broken)                          # no lo encontro -> canary red
            os.remove(os.path.join(env.state, "usage-agents.json"))
            os.remove(os.path.join(env.state, "usage-skills.json"))
            os.remove(os.path.join(env.state, "usage-history.json"))
            items, _ = U.refresh(p, history_dir, "agents", roots)                   # guard presente
            self.assertGreaterEqual(items["reviewer"]["n_total"], 1)                # lo encontro en UNA sola corrida
        finally:
            env.cleanup()

    def test_usage_truncated_file_guard(self):
        # con un archivo que se encoge (rotacion/reescritura), desactivar la resta por delta y
        # confirmar que el total DUPLICA lo esperado tras dos refresh — no solo se queda igual.
        env = Env()
        try:
            p = os.path.join(env.state, "usage-agents.json")
            history_dir = os.path.join(env.claude, "projects")
            roots = {"alpha": env.alpha}
            items1, _ = U.refresh(p, history_dir, "agents", roots)
            before = items1["reviewer"]["n_total"]
            env.truncate_usage_history(
                '{"timestamp":"2026-08-01T00:00:00Z","cwd":"%s","x":{"subagent_type":"reviewer"}}\n' % env.alpha)
            with mock.patch.object(U, "_file_delta", lambda new, old: new):   # guard disabled
                items2, _ = U.refresh(p, history_dir, "agents", roots)
                self.assertEqual(items2["reviewer"]["n_total"], before + 1)   # duplicado -> canary red
            os.remove(os.path.join(env.state, "usage-history.json"))
            os.remove(os.path.join(env.state, "usage-agents.json"))
            os.remove(os.path.join(env.state, "usage-skills.json"))
            env.truncate_usage_history(
                '{"timestamp":"2026-08-01T00:00:00Z","cwd":"%s","x":{"subagent_type":"reviewer"}}\n' % env.alpha)
            U.refresh(p, history_dir, "agents", roots)
            items3, _ = U.refresh(p, history_dir, "agents", roots)            # guard presente, sin truncar de nuevo
            self.assertEqual(items3["reviewer"]["n_total"], 1)                # no duplica
        finally:
            env.cleanup()

    def test_usage_deleted_file_does_not_regress_the_total_guard(self):
        # rotacion normal: el archivo fuente desaparece por completo del disco. Su ultima
        # contribucion conocida se queda en el acumulador para siempre (mismo espiritu que
        # sessions.py con `ended`) — nunca se resta por desaparicion.
        env = Env()
        try:
            p = os.path.join(env.state, "usage-agents.json")
            history_dir = os.path.join(env.claude, "projects")
            roots = {"alpha": env.alpha}
            U.refresh(p, history_dir, "agents", roots)
            before = U.load(p)["reviewer"]["n_total"]
            os.remove(env.usage_history_file)              # rotacion normal: el archivo ya no existe
            U.refresh(p, history_dir, "agents", roots)
            after = U.load(p)["reviewer"]["n_total"]
            self.assertEqual(after, before)                 # nunca baja por desaparicion del archivo
        finally:
            env.cleanup()

    def test_sessions_no_text_leak_guard(self):
        leak = {"session_id": "s1", "prompt_text": "the secret prompt string XYZ123"}
        self.assertNotIn("prompt_text", SESS._redact_unknown_fields(leak))                     # guard present
        with mock.patch.object(SESS, "SUMMARY_FIELDS", SESS.SUMMARY_FIELDS + ("prompt_text",)):
            self.assertIn("prompt_text", SESS._redact_unknown_fields(leak))                     # guard removed -> leaks

    def test_sessions_partial_state_allowlist_guard(self):
        leak_state = dict(SESS._new_state())
        leak_state["prompt_text"] = "the secret prompt string XYZ123"
        self.assertNotIn("prompt_text", SESS._redact_partial_state(leak_state))                # guard present
        with mock.patch.object(SESS, "PARTIAL_STATE_FIELDS", SESS.PARTIAL_STATE_FIELDS + ("prompt_text",)):
            self.assertIn("prompt_text", SESS._redact_partial_state(leak_state))                # guard removed -> leaks

    def test_sessions_on_disk_registry_never_leaks_prompt_text_via_merge_lines(self):
        # R8 canary, made real: the old canary (formerly in test_sessions.py) stayed green
        # even if _redact_partial_state were identity, because _merge_lines never actually
        # copies prompt text into `state` — there was nothing for the guard to catch. This
        # wraps the REAL _merge_lines and injects a marker into `state`, so the guard at the
        # write site (_redact_partial_state, called from refresh()) is genuinely exercised.
        env = Env()
        try:
            real_merge = SESS._merge_lines
            def leaky_merge(state, lines):
                state = real_merge(state, lines)
                state["prompt_text"] = "PROMPT_MARKER_DO_NOT_LEAK leaked"
                return state
            with mock.patch.object(SESS, "_merge_lines", leaky_merge):
                SESS.refresh(env.cfg, days=30)
            raw = open(SESS.registry_path(env.cfg), encoding="utf-8").read()
            self.assertNotIn("PROMPT_MARKER_DO_NOT_LEAK", raw)                      # guard present: caught

            os.remove(SESS.registry_path(env.cfg))
            with mock.patch.object(SESS, "_merge_lines", leaky_merge), \
                 mock.patch.object(SESS, "_redact_partial_state", lambda state: state):
                SESS.refresh(env.cfg, days=30)
            raw2 = open(SESS.registry_path(env.cfg), encoding="utf-8").read()
            self.assertIn("PROMPT_MARKER_DO_NOT_LEAK", raw2)                        # guard removed -> canary red
        finally:
            env.cleanup()

    def test_sessions_retention_prune_guard(self):
        now_local = datetime.now().astimezone()
        old_ended = (now_local - timedelta(days=400)).isoformat()
        reg = {"old.jsonl": {"summary": {"ended": old_ended}}}
        self.assertEqual(SESS._prune_by_retention(reg, 365, now_local), {})                     # guard present: pruned
        with mock.patch.object(SESS, "_age_days", return_value=0):                              # guard disabled: "everything is fresh"
            self.assertIn("old.jsonl", SESS._prune_by_retention(reg, 365, now_local))            # over-age entry survives -> canary red
        # R4: existence is irrelevant to this guard — a deleted file's cached summary survives
        # as long as it is within retention (no os.path.exists check anywhere in here)
        fresh_reg = {"/no/such/file/deleted.jsonl": {"summary": {"ended": now_local.isoformat()}}}
        self.assertIn("/no/such/file/deleted.jsonl", SESS._prune_by_retention(fresh_reg, 365, now_local))

    def test_transcript_activity_blocks_the_real_save_path(self):
        env = Env()
        try:
            env.touch_session(fresh=True)                        # simulate recent activity
            app = SRV.App(env.cfg)                                # herdr absent (Env forces live.provider="none")
            d = app.docs().read("alpha", "CLAUDE.md")
            r = app.docs().save("alpha", "CLAUDE.md", d["content"], d["hash"], working=app.working())
            self.assertFalse(r["ok"])                             # fresh transcript -> blocked, even without herdr
            env.touch_session(fresh=False)                        # backdate past active_seconds
            app2 = SRV.App(env.cfg)
            r2 = app2.docs().save("alpha", "CLAUDE.md", d["content"], d["hash"], working=app2.working())
            self.assertTrue(r2["ok"], r2)                          # stale -> allowed
        finally:
            env.cleanup()

    def test_export_activity_never_leaks_local_only_guard(self):
        from cabina import snapshot as SNAP
        import json as _json
        env = Env()
        try:
            env.refresh_sessions()
            real_row = SNAP._detail_row
            def leaky_row(s, titles):
                r = real_row(s, titles)
                r["cwd"] = s.get("cwd"); r["source_path"] = s.get("source_path")
                return r
            with mock.patch.object(SNAP, "_detail_row", leaky_row):
                out = SNAP.export_activity(env.cfg, detail=True)
            self.assertNotIn("cwd", _json.dumps(out))                              # guard present: caught
            with mock.patch.object(SNAP, "_detail_row", leaky_row), \
                 mock.patch.object(SNAP, "_strip_local_only", lambda row: row):
                out2 = SNAP.export_activity(env.cfg, detail=True)
            self.assertIn(env.alpha, _json.dumps(out2))                            # guard removed -> cwd leaks -> canary red
        finally:
            env.cleanup()

    def test_hub_no_write_path_guard(self):
        from cabina import hub as HUB, config as CFG
        self.assertFalse(hasattr(HUB.HubApp, "POSTS"))
        for m in ("api_archive", "api_create", "api_archive_skill", "api_save_doc", "api_commit", "api_open", "api_focus", "api_rescan"):
            self.assertFalse(hasattr(HUB.HubApp, m))
        import threading, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as d:
            app = HUB.HubApp(d, CFG.load(None))
            H = HUB.make_hub_handler(app)
            def run_posts():
                srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
                port = srv.server_address[1]
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                try:
                    codes = []
                    for path in ("/api/archive", "/api/create", "/api/archive-skill", "/api/save-doc",
                                 "/api/open", "/api/focus", "/api/rescan", "/api/commit"):
                        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}", method="POST")
                        try:
                            urllib.request.urlopen(req); codes.append(200)
                        except urllib.error.HTTPError as e:
                            codes.append(e.code)
                    return codes
                finally:
                    srv.shutdown()
            self.assertEqual(run_posts(), [405] * 8)                                  # guard present: every write route blocked
            leaky_do_post = lambda self: self._json({"ok": True, "message": "SHOULD NEVER HAPPEN"}, 200)
            with mock.patch.object(H, "do_POST", leaky_do_post):
                self.assertEqual(run_posts(), [200] * 8)                              # guard removed -> canary red

    def test_hub_path_confinement_guard(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            secret = os.path.join(outside, "secret.json")
            open(secret, "w").write('{"machine": "evil", "agents": [{"name": "leaked"}], "skills": [], "harness": [], "projects": []}')
            os.symlink(secret, os.path.join(d, "escape.json"))
            out = HUB.load_dir(d, 5)
            self.assertEqual(out["files"][0]["status"], "outside")                     # guard present: rejected
            self.assertEqual(out["merged"]["agents"], [])
            with mock.patch.object(HUB, "_confined", return_value=True):               # guard disabled
                out2 = HUB.load_dir(d, 5)
            self.assertEqual(out2["files"][0]["status"], "ok")                          # confinement bypassed -> canary red
            self.assertEqual(out2["merged"]["agents"][0]["name"], "leaked")

    def test_hub_size_cap_guard(self):
        # Orchestrator amendment: the size cap in load_dir must be an isolated helper
        # (_over_cap) so this break-test can disable it without touching os.path.getsize itself.
        from cabina import hub as HUB
        import json as _json
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "big.json"), "w").write(_json.dumps(
                {"machine": "m1", "agents": [], "skills": [], "harness": [], "projects": [], "pad": "x" * 2000}))
            out = HUB.load_dir(d, max_mb=0.001)
            self.assertEqual(out["files"][0]["status"], "too-large")                    # guard present: rejected
            with mock.patch.object(HUB, "_over_cap", return_value=False):               # guard disabled
                out2 = HUB.load_dir(d, max_mb=0.001)
            self.assertEqual(out2["files"][0]["status"], "ok")                          # cap bypassed -> the oversized file is read -> canary red

    def test_hub_regular_file_guard(self):
        # D1: a directory named `*.json` is also non-regular, but (unlike a FIFO) safe to probe
        # here — os.path.getsize/open on it never block, so this canary can disable the guard
        # without risking a hang, unlike the FIFO case covered in test_hub.py.
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "dir.json"))
            out = HUB.load_dir(d, 5)
            self.assertEqual(out["files"][0]["status"], "not-a-file")                    # guard present: rejected
            with mock.patch.object(HUB, "_is_regular_file", return_value=True):          # guard disabled
                out2 = HUB.load_dir(d, 5)
            self.assertEqual(out2["files"][0]["status"], "unreadable")                   # falls through to open() -> IsADirectoryError -> canary red

    def test_guard_hooks_dead_cmd_guard(self):
        # S2-a: hooks_write must refuse to wire a `cmd` that does not resolve on PATH — the
        # exact "dead hook" problem cabina flags elsewhere for hand-written hooks. Disable the
        # resolution check in memory and show the canary ("hooks_write with a nonexistent cmd
        # must refuse") turns green (wrongly installs) before restoring the guard.
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(G, "_cmd_resolves", return_value=(True, None)):    # guard disabled
                ok, _ = G.hooks_write(settings, "cabina-missing-xyz")
            self.assertTrue(ok)                                    # would wire a dead hook -> canary red
            self.assertTrue(os.path.isfile(settings))
            ok2, msg2 = G.hooks_write(settings, "cabina-missing-xyz")      # guard present
            self.assertFalse(ok2)                                  # refused: no PATH resolution, no force
            self.assertIn("not on PATH", msg2)

    def test_hub_unreadable_file_guard(self):
        # Orchestrator amendment: json.loads is wrapped per file via an isolated helper
        # (_read_export). If that per-file try/except around it were ever deleted, a single
        # broken export would make load_dir itself raise instead of marking one entry
        # "unreadable" — this asserts the guard's actual mechanism, not just its outcome.
        from cabina import hub as HUB
        import json as _json
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "bad.json"), "w").write("{not valid json")
            open(os.path.join(d, "good.json"), "w").write(_json.dumps(
                {"machine": "m1", "agents": [{"name": "x", "project": "p", "tool": "claude", "category": "valid", "model": "sonnet", "uses": 1}],
                 "skills": [], "harness": [], "projects": ["p"]}))
            real_read = HUB._read_export
            def flaky(path):
                if path.endswith("bad.json"):
                    raise ValueError("boom")
                return real_read(path)
            with mock.patch.object(HUB, "_read_export", side_effect=flaky):
                out = HUB.load_dir(d, 5)                                                 # must NOT raise: guard present
            statuses = {f["name"]: f["status"] for f in out["files"]}
            self.assertEqual(statuses["bad.json"], "unreadable")                         # the flaky file is isolated
            self.assertEqual(statuses["good.json"], "ok")                                # the other file still loads
            self.assertEqual(out["merged"]["agents"][0]["name"], "x")                    # its data still merged

    def test_server_host_origin_guard(self):
        # Anti DNS-rebinding: a request whose Host header names anything but loopback/the
        # configured bind host must never reach any route.
        import http.client, threading
        from http.server import ThreadingHTTPServer
        env = Env()
        try:
            app = SRV.App(env.cfg)
            srv = ThreadingHTTPServer(("127.0.0.1", 0), SRV.make_handler(app))
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            def evil_get():
                conn = http.client.HTTPConnection("127.0.0.1", port)
                try:
                    conn.request("GET", "/", headers={"Host": "evil.example"})
                    r = conn.getresponse(); code = r.status; r.read()
                    return code
                finally:
                    conn.close()
            try:
                self.assertEqual(evil_get(), 421)                          # guard present
                with mock.patch.object(SRV, "host_allowed", return_value=True):   # guard disabled
                    self.assertEqual(evil_get(), 200)                      # canary red
            finally:
                srv.shutdown(); srv.server_close()
        finally:
            env.cleanup()

    def test_server_origin_guard_accepts_bind_host_but_rejects_foreign_origin(self):
        # POST CSRF guard: origin_allowed() must accept loopback OR the configured bind host
        # (server.host can be a LAN IP -- config.py DEFAULTS/example), and still refuse a
        # genuinely foreign Origin. Disable it in memory and show a forged Origin from
        # evil.example would be accepted before restoring the guard.
        import copy, http.client, threading
        from http.server import ThreadingHTTPServer
        env = Env()
        try:
            cfg2 = copy.deepcopy(env.cfg)
            cfg2["server"]["host"] = "10.0.0.5"
            app = SRV.App(cfg2)
            srv = ThreadingHTTPServer(("127.0.0.1", 0), SRV.make_handler(app))
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            def post_with_origin(origin):
                conn = http.client.HTTPConnection("127.0.0.1", port)
                try:
                    headers = {"Host": f"127.0.0.1:{port}", "Origin": origin,
                               "Content-Type": "application/json", "X-Cabina-Token": app.token}
                    conn.request("POST", "/api/open", body=b'{"path": "/tmp"}', headers=headers)
                    r = conn.getresponse(); code = r.status; r.read()
                    return code
                finally:
                    conn.close()
            try:
                self.assertEqual(post_with_origin("http://10.0.0.5:1234"), 200)   # bind host: allowed (not 403)
                self.assertEqual(post_with_origin("http://evil.example"), 403)    # foreign origin: refused
                with mock.patch.object(SRV, "origin_allowed", return_value=True):   # guard disabled
                    self.assertNotEqual(post_with_origin("http://evil.example"), 403)   # canary red
            finally:
                srv.shutdown(); srv.server_close()
        finally:
            env.cleanup()

    def test_hub_host_origin_guard(self):
        from cabina import hub as HUB, config as CFG
        import http.client, threading
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as d:
            app = HUB.HubApp(d, CFG.load(None))
            srv = ThreadingHTTPServer(("127.0.0.1", 0), HUB.make_hub_handler(app))
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            def evil_get():
                conn = http.client.HTTPConnection("127.0.0.1", port)
                try:
                    conn.request("GET", "/", headers={"Host": "evil.example"})
                    r = conn.getresponse(); code = r.status; r.read()
                    return code
                finally:
                    conn.close()
            try:
                self.assertEqual(evil_get(), 421)                          # guard present
                with mock.patch.object(SRV, "host_allowed", return_value=True):   # guard disabled (shared function)
                    self.assertEqual(evil_get(), 200)                      # canary red
            finally:
                srv.shutdown(); srv.server_close()

    def test_hooks_install_cabina_only_allowlist_guard(self):
        # U2: hooks_write must refuse anything that is not cabina itself, even with force=True.
        # Disable _cmd_is_cabina in memory and show a `bash -c '...'` payload would be accepted
        # (and written to settings.json) before restoring the guard.
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(G, "_cmd_is_cabina", return_value=(True, "")):        # guard disabled
                ok, _ = G.hooks_write(settings, "bash -c 'echo pwned'", force=True)
            self.assertTrue(ok)                                            # would wire an arbitrary command -> canary red
            self.assertTrue(os.path.isfile(settings))
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            ok2, msg2 = G.hooks_write(settings, "bash -c 'echo pwned'", force=True)     # guard present
            self.assertFalse(ok2)
            self.assertFalse(os.path.isfile(settings))

    def test_open_path_confinement_guard(self):
        # U3: POST /api/open must refuse any path outside cabina's own roots.
        env = Env()
        try:
            app = SRV.App(env.cfg)
            roots = list(app.roots().values()) + [env.cfg["claude_home"], env.cfg["codex_home"], env.cfg["state_dir"]]
            self.assertFalse(SRV._open_allowed("/tmp", roots))              # guard present: rejected
            with mock.patch.object(SRV, "_open_allowed", return_value=True):   # guard disabled
                with mock.patch.object(SRV.host, "open_path", return_value=(True, "opened")) as m:
                    r = app.api_open({"path": "/tmp"})
            self.assertTrue(r["ok"])                                        # would open an arbitrary path -> canary red
            m.assert_called_once()
        finally:
            env.cleanup()
if __name__ == "__main__": unittest.main()
