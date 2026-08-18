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

if __name__ == "__main__":
    unittest.main()
