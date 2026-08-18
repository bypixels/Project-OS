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

if __name__ == "__main__":
    unittest.main()
