import os, time, unittest
import _helpers  # noqa
from _env import Env
from cabina import live as LIVE, scan

class TestTranscriptProvider(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_active_from_fresh_session_file(self):
        self.env.touch_session(fresh=True)
        roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
        out = LIVE.TranscriptProvider(self.env.cfg).active_projects(roots)
        self.assertIn("alpha", out)

    def test_fixture_is_stale_by_default(self):
        # guards the CRITICAL fix from Tarea 8: an ordinary Env, untouched, must NOT look active
        roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
        out = LIVE.TranscriptProvider(self.env.cfg).active_projects(roots)
        self.assertNotIn("alpha", out)

    def test_active_from_fresh_subagent_alone(self):
        old = time.time() - 3600
        os.utime(self.env.session_file, (old, old))         # main file stays stale
        sub = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents", "agent-1.jsonl")
        os.utime(sub, (time.time(), time.time()))            # only the subagent file is fresh
        roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
        out = LIVE.TranscriptProvider(self.env.cfg).active_projects(roots)
        self.assertIn("alpha", out)

if __name__ == "__main__":
    unittest.main()
