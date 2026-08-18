import json, os, tempfile, unittest
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


class TestHubLoadDir(unittest.TestCase):
    def test_hub_lists_sessions_from_multiple_exports(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "m1.json"), "w").write(json.dumps({"cabina": 1, "machine": "m1", "os": "macOS", "when": "x",
                "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                "activity": {"aggregated": [{"project": "alpha", "sessions": 2, "hours": 1.0}]}}))
            open(os.path.join(d, "m2.json"), "w").write(json.dumps({"cabina": 1, "machine": "m2", "os": "Linux", "when": "y",
                "agents": [], "skills": [], "harness": [], "projects": ["alpha"],
                "activity": {"aggregated": [{"project": "alpha", "sessions": 3, "hours": 2.0}]}}))
            out = HUB.load_dir(d, 5)
            self.assertEqual(len(out["files"]), 2)
            self.assertTrue(all(f["status"] == "ok" for f in out["files"]))
            machines = {row["machine"] for row in out["merged"]["activity"]["aggregated"]}
            self.assertEqual(machines, {"m1", "m2"})

    def test_hub_rejects_symlink_escaping_dir(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            secret = os.path.join(outside, "secret.json")
            open(secret, "w").write(json.dumps({"machine": "evil", "agents": [{"name": "leaked"}], "skills": [], "harness": [], "projects": []}))
            os.symlink(secret, os.path.join(d, "escape.json"))
            out = HUB.load_dir(d, 5)
            self.assertEqual(out["files"][0]["status"], "outside")
            self.assertEqual(out["merged"]["agents"], [])

    def test_hub_skips_oversized_file(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "big.json"), "w").write(json.dumps({"machine": "m1", "agents": [], "skills": [], "harness": [], "projects": [], "pad": "x" * 2000}))
            out = HUB.load_dir(d, max_mb=0.001)          # ~1 KB cap, file is bigger
            self.assertEqual(out["files"][0]["status"], "too-large")

    def test_hub_marks_corrupt_json_as_unreadable_without_crashing(self):
        from cabina import hub as HUB
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "bad.json"), "w").write("{not valid json")
            open(os.path.join(d, "good.json"), "w").write(json.dumps({"machine": "m1",
                "agents": [{"name": "x", "project": "p", "tool": "claude", "category": "valid", "model": "sonnet", "uses": 1}],
                "skills": [], "harness": [], "projects": ["p"]}))
            out = HUB.load_dir(d, 5)
            statuses = {f["name"]: f["status"] for f in out["files"]}
            self.assertEqual(statuses["bad.json"], "unreadable")
            self.assertEqual(statuses["good.json"], "ok")
            self.assertEqual(out["merged"]["agents"][0]["machine"], "m1")


if __name__ == "__main__":
    unittest.main()
