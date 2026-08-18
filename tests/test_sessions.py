import os, unittest
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

if __name__ == "__main__":
    unittest.main()
