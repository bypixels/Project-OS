"""Permanent break-tests: each test removes ONE guard in memory and asserts a canary
test would notice. If a guard is ever deleted from the code, these go red first."""
import os, tempfile, unittest
from datetime import datetime, timedelta
from unittest import mock
import _helpers  # noqa
from cabina import contract as C, docs as D, harness as H, server as SRV, sessions as SESS, usage as U
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
if __name__ == "__main__": unittest.main()
