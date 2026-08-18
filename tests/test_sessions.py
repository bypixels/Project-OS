import json, os, unittest
import _helpers  # noqa
from _env import Env

class TestSessionsFixture(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_fixture_has_a_session_file_and_a_subagent_file(self):
        self.assertTrue(os.path.isfile(self.env.session_file))
        sub_dir = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents")
        self.assertEqual(len([f for f in os.listdir(sub_dir) if f.endswith(".jsonl")]), 1)


import tempfile
from cabina import sessions as S

class TestReadNewLines(unittest.TestCase):
    def test_only_returns_bytes_after_offset(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.jsonl")
            open(p, "w").write('{"a":1}\n{"a":2}\n')
            lines1, off1 = S._read_new_lines(p, 0)
            self.assertEqual(len(lines1), 2)
            open(p, "a").write('{"a":3}\n')
            lines2, off2 = S._read_new_lines(p, off1)
            self.assertEqual(lines2, ['{"a":3}'])
            self.assertGreater(off2, off1)

    def test_never_consumes_a_partial_trailing_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.jsonl")
            first_line = '{"a":1}\n'
            open(p, "w").write(first_line + '{"a":2, "partial')  # no trailing \n: still being written
            lines1, off1 = S._read_new_lines(p, 0)
            self.assertEqual(lines1, ['{"a":1}'])
            self.assertEqual(off1, len(first_line))
            open(p, "a").write('": true}\n')  # the writer finishes the line
            lines2, off2 = S._read_new_lines(p, off1)
            self.assertEqual(lines2, ['{"a":2, "partial": true}'])

class TestMergeLinesCore(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_turns_tokens_and_sidechain_exclusion(self):
        lines, _ = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["turns"], 1)                     # only the one real human text message
        self.assertEqual(state["tokens"], {"in": 230, "out": 420, "cache_read": 50, "cache_write": 10})
        self.assertEqual(state["sidechain_lines"], 1)           # the isSidechain:true line, excluded above
        self.assertEqual(state["branch"], "main")
        self.assertEqual(state["title"], "Refactor the widget loader")

    def test_sidechain_excluded_from_started_ended_too(self):
        # a standalone, minimal pair of lines (not the shared fixture): the sidechain line's
        # timestamp is LATER than the real one, so if it leaked into `ended` this would catch it.
        lines = [
            '{"type":"user","timestamp":"2026-08-10T09:00:00Z","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}',
            '{"type":"assistant","timestamp":"2026-08-10T09:05:00Z","isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{}}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}',
        ]
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["ended"], "2026-08-10T09:00:00Z")     # the sidechain line's later timestamp never counts

    def test_tool_extraction_excludes_sidechain(self):
        lines, _ = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["tool_calls"], {"Edit": 1, "Agent": 1, "Skill": 1, "Bash": 1})   # no "Read" (sidechain)
        self.assertEqual(state["files_touched"], [f"{self.env.alpha}/src/widget.py"])           # absolute here; relpath happens at _finalize
        self.assertEqual(state["agents"], {"sessions-demo-agent": 1})
        self.assertEqual(state["skills"], {"sessions-demo-skill": 1})
        self.assertEqual(state["commits"], 1)

class TestFinalize(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_finalize_majority_cwd_and_local_time(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        roots = {"alpha": self.env.alpha}
        summary = S._finalize(state, self.env.session_file, roots, off)
        self.assertEqual(summary["cwd"], self.env.alpha)          # 3 lines with alpha vs 1 with alpha/apps
        self.assertTrue(summary["cwd_changed"])
        self.assertEqual(summary["project"], "alpha")
        self.assertEqual(summary["started"], S._to_local_iso("2026-08-10T09:00:00Z"))
        self.assertEqual(summary["ended"], S._to_local_iso("2026-08-10T09:03:00Z"))
        self.assertEqual(summary["duration_s"], 180)
        self.assertEqual(summary["files_touched"], ["src/widget.py"])   # relative to the project root now

    def test_finalize_unknown_project_when_no_cwd_lines(self):
        state = S._merge_lines(S._new_state(), ['{"type":"ai-title","aiTitle":"x"}'])
        summary = S._finalize(state, "/tmp/fake/-nowhere/s.jsonl", {}, 0)
        self.assertEqual(summary["project"], "unknown")
        self.assertIsNone(summary["cwd"])
        self.assertFalse(summary["cwd_changed"])

    def test_subagents_count_and_unsummed_tokens(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        summary = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
        self.assertEqual(summary["subagents"], 1)
        self.assertEqual(summary["subagent_tokens"], {"in": 15, "out": 25, "cache_read": 0, "cache_write": 0})
        self.assertEqual(summary["tokens"]["in"], 230)             # unchanged: subagent tokens NOT added in

    def test_never_stores_prompt_text_and_matches_allowlist(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        summary = S._redact_unknown_fields(S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off))
        dumped = json.dumps(summary)
        self.assertNotIn("PROMPT_MARKER_DO_NOT_LEAK", dumped)
        self.assertEqual(set(summary), set(S.SUMMARY_FIELDS))

if __name__ == "__main__":
    unittest.main()
