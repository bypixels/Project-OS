import unittest
import _helpers  # noqa
from _env import Env, sample_export

class TestHubFixtures(unittest.TestCase):
    def test_refresh_sessions_and_sample_export_shape(self):
        env = Env()
        try:
            items = env.refresh_sessions()
            self.assertTrue(any(s["session_id"] == "sess-1" for s in items))
        finally:
            env.cleanup()
        ex = sample_export("mac-mini")
        self.assertEqual(ex["machine"], "mac-mini")
        self.assertEqual(ex["activity"]["aggregated"][0]["project"], "alpha")

if __name__ == "__main__":
    unittest.main()
