import unittest
import _helpers  # noqa
from _env import Env
from cabina import worktrees


def _data(*projects):
    return {"projects": list(projects)}


def _project(name, path, wts):
    return {"name": name, "path": path, "git": {"worktrees": wts}}


class TestWorktreesRows(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.cleanup()

    def _fixture(self):
        alpha = _project("alpha", "/repo/alpha", [
            {"path": "/repo/alpha-wt/clean1", "name": "clean1", "mb": 12, "mtime": "2026-08-01",
             "dirty": 0, "branch": "feat-clean", "prunable": False},
            {"path": "/repo/alpha-wt/dirty1", "name": "dirty1", "mb": 30, "mtime": "2026-08-02",
             "dirty": 3, "branch": "feat-dirty", "prunable": False},
            {"path": "/repo/alpha-wt/gone1", "name": "gone1", "mb": None, "mtime": "2026-07-01",
             "dirty": None, "branch": "old-branch", "prunable": True},
            {"path": "/repo/alpha-wt/unknown1", "name": "unknown1", "mb": 5, "mtime": "2026-08-03",
             "dirty": -1, "branch": "feat-unk", "prunable": False},
        ])
        beta = _project("beta", "/repo/beta", [
            {"path": "/repo/beta-wt/clean2", "name": "clean2", "mb": 8, "mtime": "2026-08-01",
             "dirty": 0, "branch": "feat-b", "prunable": False},
        ])
        return _data(alpha, beta)

    def test_rows_flattens_and_normalizes_unknown_dirty(self):
        data = self._fixture()
        rs = worktrees.rows(self.env.cfg, data)
        self.assertEqual(len(rs), 5)
        by_name = {r["name"]: r for r in rs}
        self.assertEqual(by_name["clean1"]["project"], "alpha")
        self.assertEqual(by_name["clean1"]["dirty"], 0)
        self.assertEqual(by_name["dirty1"]["dirty"], 3)
        # missing/negative dirty -> normalized to -1 (unknown), never treated as clean
        self.assertEqual(by_name["gone1"]["dirty"], -1)
        self.assertEqual(by_name["unknown1"]["dirty"], -1)
        # tolerant defaults
        self.assertTrue(by_name["gone1"]["prunable"])
        self.assertFalse(by_name["clean1"]["prunable"])

    def test_rows_tolerates_missing_prunable_field(self):
        row = {"path": "/repo/alpha-wt/x", "name": "x", "mb": 1, "mtime": "2026-08-01", "dirty": 0, "branch": "b"}
        data = _data(_project("alpha", "/repo/alpha", [row]))
        rs = worktrees.rows(self.env.cfg, data)
        self.assertEqual(rs[0]["prunable"], False)

    def test_rows_filters_by_project(self):
        data = self._fixture()
        rs = worktrees.rows(self.env.cfg, data, project="beta")
        self.assertEqual([r["name"] for r in rs], ["clean2"])

    def test_rows_empty_when_no_worktrees(self):
        data = _data(_project("alpha", "/repo/alpha", []))
        self.assertEqual(worktrees.rows(self.env.cfg, data), [])


class TestWorktreesScript(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.cleanup()

    def _fixture(self):
        alpha = _project("alpha", "/repo/alpha", [
            {"path": "/repo/alpha-wt/clean1", "name": "clean1", "mb": 12, "mtime": "2026-08-01",
             "dirty": 0, "branch": "feat-clean", "prunable": False},
            {"path": "/repo/alpha-wt/dirty1", "name": "dirty1", "mb": 30, "mtime": "2026-08-02",
             "dirty": 3, "branch": "feat-dirty", "prunable": False},
            {"path": "/repo/alpha-wt/gone1", "name": "gone1", "mb": None, "mtime": "2026-07-01",
             "dirty": None, "branch": "old-branch", "prunable": True},
            {"path": "/repo/alpha-wt/unknown1", "name": "unknown1", "mb": 5, "mtime": "2026-08-03",
             "dirty": -1, "branch": "feat-unk", "prunable": False},
        ])
        beta = _project("beta", "/repo/beta", [
            {"path": "/repo/beta-wt/clean2", "name": "clean2", "mb": 8, "mtime": "2026-08-01",
             "dirty": 0, "branch": "feat-b", "prunable": False},
        ])
        return _data(alpha, beta)

    def test_script_exact_text(self):
        data = self._fixture()
        text = worktrees.script(self.env.cfg, data)
        expected = (
            "# cabina worktree cleanup — review before running; cabina never executes these itself.\n"
            "# Branches are kept; only worktree directories are affected.\n"
            "\n"
            'git -C "/repo/alpha" worktree prune\n'
            "\n"
            'git -C "/repo/alpha" worktree remove "/repo/alpha-wt/clean1"\n'
            'git -C "/repo/beta" worktree remove "/repo/beta-wt/clean2"\n'
            "\n"
            "# skipped (uncommitted changes): /repo/alpha-wt/dirty1\n"
            "# skipped (status unknown — run: cabina scan): /repo/alpha-wt/unknown1\n"
        )
        self.assertEqual(text, expected)

    def test_script_has_no_loops_or_conditionals_and_never_forces(self):
        data = self._fixture()
        text = worktrees.script(self.env.cfg, data)
        self.assertNotIn("for ", text)
        self.assertNotIn("if ", text)
        self.assertNotIn("--force", text)
        self.assertNotIn("branch -d", text)
        self.assertNotIn("branch -D", text)

    def test_script_project_filter(self):
        data = self._fixture()
        text = worktrees.script(self.env.cfg, data, project="beta")
        self.assertNotIn("alpha", text)
        self.assertIn('git -C "/repo/beta" worktree remove "/repo/beta-wt/clean2"', text)

    def test_script_empty_when_nothing_to_clean(self):
        data = _data(_project("alpha", "/repo/alpha", []))
        text = worktrees.script(self.env.cfg, data)
        self.assertNotIn("worktree remove", text)
        self.assertNotIn("worktree prune", text)


class TestWorktreesSummary(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.cleanup()

    def test_summary_counts(self):
        alpha = _project("alpha", "/repo/alpha", [
            {"path": "/repo/alpha-wt/clean1", "name": "clean1", "mb": 12, "mtime": "2026-08-01",
             "dirty": 0, "branch": "feat-clean", "prunable": False},
            {"path": "/repo/alpha-wt/dirty1", "name": "dirty1", "mb": 30, "mtime": "2026-08-02",
             "dirty": 3, "branch": "feat-dirty", "prunable": False},
            {"path": "/repo/alpha-wt/gone1", "name": "gone1", "mb": None, "mtime": "2026-07-01",
             "dirty": None, "branch": "old-branch", "prunable": True},
            {"path": "/repo/alpha-wt/unknown1", "name": "unknown1", "mb": 5, "mtime": "2026-08-03",
             "dirty": -1, "branch": "feat-unk", "prunable": False},
        ])
        data = _data(alpha)
        s = worktrees.summary(self.env.cfg, data)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["clean"], 1)
        self.assertEqual(s["dirty"], 1)
        self.assertEqual(s["unknown"], 1)
        self.assertEqual(s["prunable"], 1)
        self.assertEqual(s["mb"], 47)          # 12 + 30 + 5 (None excluded)
        self.assertFalse(s["mb_measured"])     # gone1's mb is None

    def test_summary_mb_measured_true_when_all_known(self):
        data = _data(_project("alpha", "/repo/alpha", [
            {"path": "/repo/alpha-wt/clean1", "name": "clean1", "mb": 12, "mtime": "2026-08-01",
             "dirty": 0, "branch": "b", "prunable": False},
        ]))
        s = worktrees.summary(self.env.cfg, data)
        self.assertTrue(s["mb_measured"])

    def test_summary_empty(self):
        data = _data(_project("alpha", "/repo/alpha", []))
        s = worktrees.summary(self.env.cfg, data)
        self.assertEqual(s, {"total": 0, "clean": 0, "dirty": 0, "unknown": 0, "prunable": 0, "mb": 0, "mb_measured": True})


if __name__ == "__main__":
    unittest.main()
