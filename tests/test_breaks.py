"""Permanent break-tests: each test removes ONE guard in memory and asserts a canary
test would notice. If a guard is ever deleted from the code, these go red first."""
import copy, http.client, json, os, re, tempfile, threading, time, unittest
from datetime import datetime, timedelta
from unittest import mock
import _helpers  # noqa
from project_os import contract as C, desired as DS, docs as D, guard as G, harness as H, healthlog as HL, server as SRV, sessions as SESS, skills as SK, usage as U, worktrees as WT
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
    def test_skills_read_file_confinement_guard(self):
        # GET /api/skill-file must refuse any rel path that resolves outside the skill's own
        # directory -- the only thing stopping "../x" from reading an arbitrary file.
        with tempfile.TemporaryDirectory() as d:
            outside = os.path.join(d, "secret.txt"); open(outside, "w").write("nope")
            skill = os.path.join(d, "s"); os.makedirs(skill)
            open(os.path.join(skill, "SKILL.md"), "w").write("---\nname: s\ndescription: d\n---\n")
            self.assertFalse(SK.read_file(skill, "../secret.txt")["ok"])          # guard present: rejected
            with mock.patch.object(SK, "_confined", return_value=True):           # guard disabled
                r = SK.read_file(skill, "../secret.txt")
            self.assertTrue(r["ok"])                                              # canary red: escapes
            self.assertEqual(r["content"], "nope")
            # Same guard also governs the recursive DIRECTORY LISTING: a symlink inside the
            # skill dir pointing outside must not be listed either -- read_file's guard alone
            # would not catch a deleted/weakened check in _list_files (skills.py:94-100).
            os.symlink(outside, os.path.join(skill, "link.txt"))
            names = {f["path"] for f in SK.read_body(skill)["files"]}
            self.assertNotIn("link.txt", names)                                   # guard present: not listed
            with mock.patch.object(SK, "_confined", return_value=True):           # guard disabled
                names2 = {f["path"] for f in SK.read_body(skill)["files"]}
            self.assertIn("link.txt", names2)                                     # canary red: listed
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
    def test_docs_backup_confinement_guard(self):
        # _backup_loc mirrors rel's dirname under <backups>/<project>/; _confined is the only
        # thing stopping that mirrored dir from escaping <backups>/<project>/ when rel carries
        # a directory-traversal dirname (which _resolve would normally have already refused --
        # mock it away here to isolate this guard on its own, same idiom as test_docs_allowlist_guard).
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as b:
            d = D.Docs({"p": t}, b)
            bp = os.path.realpath(os.path.join(b, "p"))
            with mock.patch.object(D.Docs, "_resolve", lambda self, proj, rel: (os.path.join(t, "x.md"), None)):
                bd, base, err = d._backup_loc("p", "../../escape/x.md")
                self.assertIsNone(bd)                                          # guard present: rejected
                with mock.patch.object(D, "_confined", return_value=True):     # guard disabled
                    bd2, base2, err2 = d._backup_loc("p", "../../escape/x.md")
            self.assertIsNotNone(bd2)                                         # canary red: escapes
            self.assertFalse(bd2 == bp or bd2.startswith(bp + os.sep))

    def test_docs_version_stamp_regex_guard(self):
        # The stamp regex (`^\d{8}-\d{6}$`) is what keeps version_text's resolved file a direct
        # child of the document's own mirrored backup dir -- disabling it lets a crafted stamp
        # walk out of that dir (while staying inside the project's overall backups dir, so the
        # separate fp-vs-bp containment check does not also catch it) and read an unrelated file.
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as b:
            os.makedirs(os.path.join(t, "sub"))
            open(os.path.join(t, "sub/X.md"), "w").write("v1")
            d = D.Docs({"p": t}, b)
            bp = os.path.join(b, "p")
            os.makedirs(bp, exist_ok=True)
            open(os.path.join(bp, "secret.md"), "w").write("LEAKED")
            malicious = "x/../../secret"
            self.assertFalse(d.version_text("p", "sub/X.md", malicious)["ok"])   # guard present: rejected
            with mock.patch.object(D, "_STAMP_RE", re.compile(r".*")):           # guard disabled
                res = d.version_text("p", "sub/X.md", malicious)
            self.assertTrue(res.get("ok"))                                      # canary red: reads outside bd
            self.assertEqual(res["content"], "LEAKED")

    def test_docs_prune_pattern_guard(self):
        # _prune must only ever remove files matching the backup naming pattern; disabling that
        # filter lets it delete any unrelated old file that happens to sit in the backups tree.
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as b:
            d = D.Docs({"p": t}, b, retention_days=1)
            bp = os.path.join(b, "p"); os.makedirs(bp)
            unrelated = os.path.join(bp, "notes.txt")
            open(unrelated, "w").write("keep me")
            old = time.time() - 999999
            os.utime(unrelated, (old, old))
            d._prune(bp)
            self.assertTrue(os.path.isfile(unrelated))                         # guard present: untouched
            with mock.patch.object(D, "_is_backup_file", return_value=True):    # guard disabled
                d._prune(bp)
            self.assertFalse(os.path.isfile(unrelated))                        # canary red: unrelated file deleted

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

    def test_sessions_backfill_head_line_bound_guard(self):
        # _HEAD_LINES bounds _backfill_entrypoint's head read -- without it, a cached-but-
        # unmigrated record with no entrypoint would force a FULL re-read of every such
        # transcript on every refresh(), the exact perf regression Fase 4 exists to prevent.
        entrypoint_line_idx = SESS._HEAD_LINES
        content = "".join('{"n":%d}\n' % i for i in range(entrypoint_line_idx)) + '{"entrypoint":"sdk-py"}\n'
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "far.jsonl")
            open(fp, "w").write(content)
            self.assertIsNone(SESS._backfill_entrypoint(fp))                          # guard present: line past the bound, not found
            with mock.patch.object(SESS, "_HEAD_LINES", entrypoint_line_idx + 1):     # guard disabled: read one line further
                self.assertEqual(SESS._backfill_entrypoint(fp), "sdk-py")             # canary red: bound was the only thing stopping the read

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
        from project_os import snapshot as SNAP
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
        from project_os import hub as HUB, config as CFG
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
        from project_os import hub as HUB
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
        from project_os import hub as HUB
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
        from project_os import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "dir.json"))
            out = HUB.load_dir(d, 5)
            self.assertEqual(out["files"][0]["status"], "not-a-file")                    # guard present: rejected
            with mock.patch.object(HUB, "_is_regular_file", return_value=True):          # guard disabled
                out2 = HUB.load_dir(d, 5)
            self.assertEqual(out2["files"][0]["status"], "unreadable")                   # falls through to open() -> IsADirectoryError -> canary red

    def test_guard_hooks_dead_cmd_guard(self):
        # S2-a: hooks_write must refuse to wire a `cmd` that does not resolve on PATH — the
        # exact "dead hook" problem project-os flags elsewhere for hand-written hooks. Disable the
        # resolution check in memory and show the canary ("hooks_write with a nonexistent cmd
        # must refuse") turns green (wrongly installs) before restoring the guard.
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(G, "_cmd_resolves", return_value=(True, None)):    # guard disabled
                ok, _ = G.hooks_write(settings, "project-os")
            self.assertTrue(ok)                                    # would wire a dead hook -> canary red
            self.assertTrue(os.path.isfile(settings))
            with mock.patch.object(G, "_cmd_resolves", return_value=(False, None)):
                ok2, msg2 = G.hooks_write(settings, "project-os")      # guard present
            self.assertFalse(ok2)                                  # refused: no PATH resolution, no force
            self.assertIn("not on PATH", msg2)

    def test_hub_unreadable_file_guard(self):
        # Orchestrator amendment: json.loads is wrapped per file via an isolated helper
        # (_read_export). If that per-file try/except around it were ever deleted, a single
        # broken export would make load_dir itself raise instead of marking one entry
        # "unreadable" — this asserts the guard's actual mechanism, not just its outcome.
        from project_os import hub as HUB
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

    def test_server_local_only_guard_canary(self):
        # If serve() ever stops calling the isolated loopback guard, this canary turns green
        # under the disabled guard and therefore fails the test.
        cfg = __import__("copy").deepcopy(SRV.config.DEFAULTS) if hasattr(SRV, "config") else None
        if cfg is None:
            env = Env(); cfg = env.cfg
        else:
            env = None
        try:
            cfg["server"]["host"] = "10.0.0.5"
            fake = mock.Mock(); fake.server_address = ("10.0.0.5", 9999)
            with mock.patch.object(SRV, "_loopback_only", return_value=True), \
                 mock.patch.object(SRV, "App"), \
                 mock.patch.object(SRV, "ThreadingHTTPServer", return_value=fake) as ctor:
                SRV.serve(cfg, port=0, open_browser=False)
            ctor.assert_called_once()
        finally:
            if env:
                env.cleanup()

    def test_snapshot_token_whitelist_canary(self):
        row = {"project": "p", "tokens": {"in": 1, "out": 2, "thinking": 3}}
        self.assertNotIn("thinking", SRV.SNAP._detail_row(row, False)["tokens"])
        with mock.patch.object(SRV.SNAP, "_DETAIL_TOKEN_FIELDS", ("in", "out", "cache_read", "cache_write", "thinking")):
            self.assertIn("thinking", SRV.SNAP._detail_row(row, False)["tokens"])

    def test_server_origin_guard_rejects_lan_and_foreign_origin(self):
        # POST CSRF guard: only loopback origins are accepted, regardless of configured bind host.
        # LAN and foreign origins are refused, even when the configured bind host is non-loopback.
        # The route remains protected by the loopback-only origin guard.
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
                               "Content-Type": "application/json", "X-ProjectOS-Token": app.token}
                    conn.request("POST", "/api/open", body=json.dumps({"path": env.alpha + "/CLAUDE.md"}).encode(), headers=headers)
                    r = conn.getresponse(); code = r.status; r.read()
                    return code
                finally:
                    conn.close()
            try:
                expected_path = os.path.realpath(os.path.join(env.alpha, "CLAUDE.md"))
                with mock.patch.object(SRV.host, "open_path", return_value=(True, "opened")) as opener:
                    self.assertEqual(post_with_origin("http://10.0.0.5:1234"), 403)   # LAN origin: refused
                    self.assertEqual(post_with_origin("http://evil.example"), 403)    # foreign origin: refused
                    opener.assert_not_called()                                          # neither rejection reaches the route
                    opener.reset_mock()
                    with mock.patch.object(SRV, "origin_allowed", return_value=True):   # guard disabled
                        self.assertNotEqual(post_with_origin("http://evil.example"), 403)   # canary red
                    opener.assert_called_once_with(expected_path)                       # only the neutralized guard reaches open
            finally:
                srv.shutdown(); srv.server_close()
        finally:
            env.cleanup()

    def test_hub_host_origin_guard(self):
        from project_os import hub as HUB, config as CFG
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

    def test_hooks_install_project_os_only_allowlist_guard(self):
        # U2: hooks_write must refuse anything that is not project-os itself, even with force=True.
        # Disable _cmd_is_project_os in memory and show a `bash -c '...'` payload would be accepted
        # (and written to settings.json) before restoring the guard.
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(G, "_cmd_is_project_os", return_value=(True, "")):        # guard disabled
                ok, _ = G.hooks_write(settings, "bash -c 'echo pwned'", force=True)
            self.assertTrue(ok)                                            # would wire an arbitrary command -> canary red
            self.assertTrue(os.path.isfile(settings))
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            ok2, msg2 = G.hooks_write(settings, "bash -c 'echo pwned'", force=True)     # guard present
            self.assertFalse(ok2)
            self.assertFalse(os.path.isfile(settings))
        # Impostor-basename regression: the guard must match the basename EXACTLY, not with
        # startswith -- otherwise "project-os-evil" masquerades as project-os. Show the real
        # guard refuses it, and that a startswith-shaped stand-in (the check's old, buggy form)
        # would wrongly accept it.
        def _old_startswith_check(cmd):
            base = os.path.basename(cmd.split()[0]).lower()
            return (base.startswith("project-os"), "")
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            ok3, _ = G.hooks_write(settings, "project-os-evil", force=True)             # guard present
            self.assertFalse(ok3)
            self.assertFalse(os.path.isfile(settings))
            with mock.patch.object(G, "_cmd_is_project_os", side_effect=_old_startswith_check):  # guard reverted to the old shape
                ok4, _ = G.hooks_write(settings, "project-os-evil", force=True)
            self.assertTrue(ok4)                                             # canary red: impostor accepted
            self.assertTrue(os.path.isfile(settings))

    def test_healthlog_dedup_guard(self):
        # If _should_append ever always returned True, two identical-and-recent `check` runs
        # would each append their own line instead of collapsing into one.
        env = Env()
        try:
            findings = [{"sev": "crit", "title": "x"}]
            with mock.patch.object(HL, "_should_append", return_value=True):   # guard disabled
                HL.append(env.cfg, findings)
                HL.append(env.cfg, findings)
            self.assertEqual(len(HL.read(env.cfg)), 2)                          # duplicate line -> canary red
        finally:
            env.cleanup()
        env2 = Env()
        try:
            findings = [{"sev": "crit", "title": "x"}]
            HL.append(env2.cfg, findings)                                       # guard present
            HL.append(env2.cfg, findings)
            self.assertEqual(len(HL.read(env2.cfg)), 1)                         # collapsed: no-op
        finally:
            env2.cleanup()

    def test_healthlog_prune_guard(self):
        # If _prune were ever a no-op, health.jsonl would grow forever past cfg.check.history_days.
        from datetime import datetime, timedelta
        env = Env()
        try:
            p = HL.path(env.cfg)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            old = (datetime.now().astimezone() - timedelta(days=400)).isoformat(timespec="seconds")
            with open(p, "w", encoding="utf-8") as f:
                f.write('{"when": "%s", "crit": 9, "warn": 0, "info": 0}\n' % old)
            with mock.patch.object(HL, "_prune", lambda path, days: None):     # guard disabled
                self.assertTrue(HL.append(env.cfg, [{"sev": "crit", "title": "y"}]))
            self.assertEqual(len(HL.read(env.cfg)), 2)                          # stale line survives -> canary red
        finally:
            env.cleanup()
        env2 = Env()
        try:
            p = HL.path(env2.cfg)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            old = (datetime.now().astimezone() - timedelta(days=400)).isoformat(timespec="seconds")
            with open(p, "w", encoding="utf-8") as f:
                f.write('{"when": "%s", "crit": 9, "warn": 0, "info": 0}\n' % old)
            HL.append(env2.cfg, [{"sev": "crit", "title": "y"}])                # guard present
            self.assertEqual(len(HL.read(env2.cfg)), 1)                         # stale line pruned
        finally:
            env2.cleanup()

    def test_open_path_confinement_guard(self):
        # U3: POST /api/open must refuse any path outside project-os's own roots.
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

    def test_terminal_target_confinement_guard(self):
        # W3: POST /api/open-terminal must refuse any path outside project-os's own roots (same
        # confinement as /api/open, plus a directory check).
        env = Env()
        try:
            app = SRV.App(env.cfg)
            roots = list(app.roots().values()) + [env.cfg["claude_home"], env.cfg["codex_home"], env.cfg["state_dir"]]
            self.assertFalse(SRV._terminal_target_ok("/tmp", roots))           # guard present: rejected
            with mock.patch.object(SRV, "_terminal_target_ok", return_value=True):   # guard disabled
                with mock.patch.object(SRV.host, "open_terminal", return_value=(True, "opened")) as m:
                    r = app.api_open_terminal({"path": "/tmp"})
            self.assertTrue(r["ok"])                                        # would open a terminal anywhere -> canary red
            m.assert_called_once()
        finally:
            env.cleanup()

    def test_worktree_script_unsafe_path_guard(self):
        # W3 follow-up: worktrees.script() must never put a path containing shell metacharacters
        # (e.g. a command-substitution payload) on a `git worktree remove` line -- _is_unsafe()
        # is what keeps it off, routing it to the "# skipped (... unusual characters)" comment
        # instead.
        data = {"projects": [{"name": "alpha", "path": "/repo/alpha", "git": {"worktrees": [
            {"path": "/repo/alpha-wt/$(whoami)", "name": "evil", "mb": 1, "mtime": "2026-08-01",
             "dirty": 0, "branch": "b", "prunable": False},
        ]}}]}
        cfg = {}   # never touched: script()/rows() only read `data`, which is passed explicitly
        out = WT.script(cfg, data)
        self.assertNotIn('worktree remove "/repo/alpha-wt/$(whoami)"', out)     # guard present: kept off the remove line
        with mock.patch.object(WT, "_is_unsafe", return_value=False):            # guard disabled
            out2 = WT.script(cfg, data)
        self.assertIn('worktree remove "/repo/alpha-wt/$(whoami)"', out2)       # canary red: unsafe path now emitted

    def test_terminal_target_directory_only_guard(self):
        # W3: even a path INSIDE the allowed roots must be refused if it is a regular file --
        # a terminal opens AT a directory, never "on" a file.
        env = Env()
        try:
            app = SRV.App(env.cfg)
            roots = list(app.roots().values()) + [env.cfg["claude_home"], env.cfg["codex_home"], env.cfg["state_dir"]]
            claude_md = os.path.join(env.alpha, "CLAUDE.md")
            self.assertTrue(os.path.isfile(claude_md))
            self.assertFalse(SRV._terminal_target_ok(claude_md, roots))        # guard present: rejected (not a dir)
            with mock.patch.object(SRV.os.path, "isdir", return_value=True):   # guard disabled
                with mock.patch.object(SRV.host, "open_terminal", return_value=(True, "opened")) as m:
                    r = app.api_open_terminal({"path": claude_md})
            self.assertTrue(r["ok"])                                        # would open a terminal on a file -> canary red
            m.assert_called_once()
        finally:
            env.cleanup()

    def test_doc_version_command_unsafe_path_guard(self):
        # Doc-versions follow-up: /api/doc-version must never hand the user a restore command
        # for a path containing shell metacharacters -- reuses WT._is_unsafe (same guard
        # test_worktree_script_unsafe_path_guard above defends) rather than reimplementing it.
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as backups:
            evil = os.path.join(root, "$(whoami)")
            os.makedirs(evil)
            open(os.path.join(evil, "CLAUDE.md"), "w").write("v1")
            d = D.Docs({"evil": evil}, backups)
            h = d.read("evil", "CLAUDE.md")["hash"]
            self.assertTrue(d.save("evil", "CLAUDE.md", "v2", h)["ok"])
            stamp = d.versions("evil", "CLAUDE.md")[0]["stamp"]
            env = Env()
            try:
                app = SRV.App(env.cfg)
                app.docs = lambda: d          # a Docs instance rooted at the unsafe path, in place of the real one
                r = app.api_doc_version({"project": ["evil"], "rel": ["CLAUDE.md"], "stamp": [stamp]})
                self.assertTrue(r["ok"], r)
                self.assertIsNone(r["command"])                        # guard present: withheld
                with mock.patch.object(WT, "_is_unsafe", return_value=False):   # guard disabled
                    r2 = app.api_doc_version({"project": ["evil"], "rel": ["CLAUDE.md"], "stamp": [stamp]})
                self.assertIsNotNone(r2["command"])
                self.assertIn("$(whoami)", r2["command"])              # canary red: unsafe path now emitted
            finally:
                env.cleanup()
    def test_desired_verification_path_confinement_guard(self):
        # `[desired.verification] tests = "..."` is an untrusted path from the scanned repo's OWN
        # .project-os.toml. _confined_path is the only thing stopping it from making gaps() stat
        # a path outside that repo -- and from reporting the RESULT of that stat as a finding.
        env = Env()
        try:
            open(os.path.join(env.alpha, ".project-os.toml"), "w").write(
                '[desired.verification]\ntests = "../../.."\n')
            from project_os import scan
            data = scan.run(env.cfg); scan.save(env.cfg, data)
            p = next(pr for pr in data["projects"] if pr["name"] == "alpha")
            g = DS.gaps(env.cfg, p, data)
            self.assertIn({"kind": "bad_value", "field": "verification.tests"}, g)   # guard present
            self.assertFalse(any(x["kind"] == "tests_absent" for x in g), g)
            with mock.patch.object(DS, "_confined_path", lambda root, rel: rel):     # guard disabled
                g2 = DS.gaps(env.cfg, p, data)
            self.assertFalse(any(x["kind"] == "bad_value" and x["field"] == "verification.tests"
                                 for x in g2), g2)                                   # canary red: escape accepted
        finally:
            env.cleanup()
    def test_desired_verification_confined_path_null_byte_guard(self):
        # A declared `tests` path containing a NUL byte is valid TOML (a backslash-u-0000 escape
        # inside a basic string) but makes os.path.realpath() raise ValueError, not OSError --
        # a different exception type than the one _confined_path already caught before this
        # guard existed. Without the try/except, this reaches gaps()'s caller uncaught and takes
        # down the whole check run (check.py has no try/except of its own around gaps()).
        env = Env()
        try:
            open(os.path.join(env.alpha, ".project-os.toml"), "w").write(
                '[desired.verification]\ntests = "a\\u0000b"\n')
            from project_os import scan
            data = scan.run(env.cfg); scan.save(env.cfg, data)
            p = next(pr for pr in data["projects"] if pr["name"] == "alpha")
            g = DS.gaps(env.cfg, p, data)                                            # guard present: no crash
            self.assertIn({"kind": "bad_value", "field": "verification.tests"}, g)

            def _unguarded(root, rel):   # same body, minus the try/except -- the guard under test
                base = os.path.realpath(root)
                resolved = os.path.realpath(os.path.join(root, rel))
                return resolved if (resolved == base or resolved.startswith(base + os.sep)) else None

            with mock.patch.object(DS, "_confined_path", _unguarded):                # guard disabled
                with self.assertRaises(ValueError):                                  # canary red: crash
                    DS.gaps(env.cfg, p, data)
        finally:
            env.cleanup()
    def test_desired_verification_blank_gate_guard(self):
        # "" is a substring of every string in Python: `"" in text` is always True. Without a
        # blank-gate check, an empty `gates` entry would silently be reported as "found" against
        # any workflow file -- an assertion the config never actually made.
        env = Env()
        try:
            wf = os.path.join(env.alpha, ".github", "workflows")
            os.makedirs(wf)
            open(os.path.join(wf, "ci.yml"), "w").write("steps:\n  - run: echo hi\n")
            open(os.path.join(env.alpha, ".project-os.toml"), "w").write(
                '[desired.verification]\ngates = [""]\n')
            from project_os import scan
            data = scan.run(env.cfg); scan.save(env.cfg, data)
            p = next(pr for pr in data["projects"] if pr["name"] == "alpha")
            g = DS.gaps(env.cfg, p, data)
            self.assertEqual(g, [{"kind": "bad_value", "field": "verification.gates"}])   # guard present
            with mock.patch.object(DS, "_is_blank_gate", return_value=False):        # guard disabled
                g2 = DS.gaps(env.cfg, p, data)
            self.assertEqual(g2, [])                                                 # canary red: blank gate "satisfied"
        finally:
            env.cleanup()
if __name__ == "__main__": unittest.main()
