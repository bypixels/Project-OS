import json, unittest
import _helpers  # noqa
from _env import Env
from cabina import snapshot as SNAP

class TestExportActivity(unittest.TestCase):
    def setUp(self):
        self.env = Env(); self.env.refresh_sessions()
    def tearDown(self):
        self.env.cleanup()

    def test_export_activity_aggregated_by_default(self):
        out = SNAP.export_activity(self.env.cfg)
        self.assertNotIn("sessions", out)
        row = next(a for a in out["aggregated"] if a["project"] == "alpha")
        # 2, not 1: the Env fixture already carries a second alpha-attributed transcript
        # (projects/-x/s.jsonl, from the Fase 1 usage fixtures) besides "sess-1.jsonl".
        self.assertEqual(row["sessions"], 2)
        self.assertIn("tokens", row); self.assertIn("tool_calls", row)

    def test_export_activity_detail_adds_per_session_rows(self):
        out = SNAP.export_activity(self.env.cfg, detail=True)
        row = next(s for s in out["sessions"] if s["project"] == "alpha")
        self.assertIn("branch", row); self.assertNotIn("title", row)
        self.assertEqual(row["files_touched"], ["src/widget.py"])

    def test_export_activity_titles_requires_detail(self):
        with self.assertRaises(ValueError):
            SNAP.export_activity(self.env.cfg, titles=True)

    def test_export_activity_never_includes_cwd_or_source_path(self):
        out = SNAP.export_activity(self.env.cfg, detail=True, titles=True)
        dumped = json.dumps(out)
        self.assertNotIn("source_path", dumped)
        self.assertNotIn('"cwd"', dumped)

class TestExportProjectsDetail(unittest.TestCase):
    # Orchestrator amendment to Tarea 28 (plan Concern 2): export() also embeds
    # "projects_detail" — per-project fields from projects.load(), never "path" (local-only).
    def test_export_includes_projects_detail_without_path(self):
        env = Env()
        try:
            out = SNAP.export(env.cfg)
            self.assertIn("projects_detail", out)
            row = next(p for p in out["projects_detail"] if p["name"] == "alpha")
            self.assertEqual(set(row.keys()),
                              {"name", "branch", "dirty", "worktrees", "docs", "memory_days", "last_commit", "agents", "skills"})
            self.assertTrue(all("path" not in p for p in out["projects_detail"]))
        finally:
            env.cleanup()

class TestCompareActivity(unittest.TestCase):
    def test_compare_activity_deltas(self):
        a = {"machine": "m1", "agents": [], "skills": [], "projects": [],
             "activity": {"aggregated": [{"project": "alpha", "sessions": 2, "hours": 1.5, "commits": 1}]}}
        b = {"machine": "m2", "agents": [], "skills": [], "projects": [],
             "activity": {"aggregated": [{"project": "alpha", "sessions": 5, "hours": 4.0, "commits": 3}]}}
        r = SNAP.compare(a, b)
        self.assertEqual(r["activity"][0]["sessions"], {"a": 2, "b": 5})
        txt = SNAP.render_compare(r, "m1", "m2")
        self.assertIn("alpha", txt)

if __name__ == "__main__":
    unittest.main()
