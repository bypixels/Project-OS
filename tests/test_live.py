import os, time, unittest
import _helpers  # noqa
from _env import Env
from project_os import live as LIVE, scan

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

    def test_active_project_reflects_the_tail_cwd_not_the_session_start_one(self):
        # A session that changed project mid-way: the early lines say cwd=alpha (the fixture's
        # default), but the LAST lines — what the user is actually doing right now — say
        # cwd=beta. "active now" must reflect the tail, not where the session started.
        beta = os.path.join(self.env.projects, "beta")
        os.makedirs(os.path.join(beta, ".claude"))
        open(os.path.join(beta, "CLAUDE.md"), "w").write("# beta\n")   # scan.py only registers a
        self.env.touch_session(fresh=True)                              # project with SOME asset/harness/CLAUDE.md
        open(self.env.session_file, "a", encoding="utf-8").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:04:00Z","cwd":"%s","message":{"role":"assistant","content":[]}}\n' % beta)
        roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
        out = LIVE.TranscriptProvider(self.env.cfg).active_projects(roots)
        self.assertIn("beta", out)
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
