import io, json, os, tempfile, unittest
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
            ok, msg = G.hooks_write(settings, "cabina")
            self.assertTrue(ok); d2 = json.load(open(settings))
            self.assertIn("Stop", d2["hooks"])                    # existing hooks kept
            self.assertTrue(any("cabina guard" in h["command"] for grp in d2["hooks"]["PreToolUse"] for h in grp["hooks"]))
            self.assertTrue(any(f.startswith("settings.json.bak-") for f in os.listdir(d)))
            ok2, msg2 = G.hooks_write(settings, "cabina")        # idempotent
            self.assertTrue(ok2); d3 = json.load(open(settings))
            self.assertEqual(sum(1 for grp in d3["hooks"]["PreToolUse"] for h in grp["hooks"] if "cabina guard" in h["command"]), 1)
if __name__ == "__main__": unittest.main()
