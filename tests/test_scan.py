"""scan._git_info: worktree dirty/branch must always be real (cheap), size stays opt-in,
and prunable worktrees (directory removed) must degrade cleanly instead of raising."""
import os, shutil, subprocess, tempfile, unittest
import _helpers  # noqa
from project_os import scan


def _git(d, *a):
    subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, text=True)


class TestGitInfoWorktrees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "main")
        os.makedirs(self.root)
        _git(self.root, "init", "-q")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        # clean worktree
        self.clean_wt = os.path.join(self.tmp.name, "clean-wt")
        _git(self.root, "worktree", "add", "-q", "-b", "clean-branch", self.clean_wt)
        # dirty worktree: an untracked file makes `git status --porcelain` non-empty
        self.dirty_wt = os.path.join(self.tmp.name, "dirty-wt")
        _git(self.root, "worktree", "add", "-q", "-b", "dirty-branch", self.dirty_wt)
        open(os.path.join(self.dirty_wt, "untracked.txt"), "w").write("x")
        # prunable worktree: add it, then remove its directory without `git worktree remove`
        self.gone_wt = os.path.join(self.tmp.name, "gone-wt")
        _git(self.root, "worktree", "add", "-q", "-b", "gone-branch", self.gone_wt)
        shutil.rmtree(self.gone_wt)

    def tearDown(self):
        self.tmp.cleanup()

    def _by_name(self, wt, name):
        return next(w for w in wt if w["name"] == name)

    def test_dirty_and_branch_are_real_without_measuring(self):
        info = scan._git_info(self.root, measure_worktrees=False)
        clean = self._by_name(info["worktrees"], "clean-wt")
        dirty = self._by_name(info["worktrees"], "dirty-wt")
        self.assertEqual(clean["dirty"], 0)
        self.assertEqual(clean["branch"], "clean-branch")
        self.assertGreaterEqual(dirty["dirty"], 1)
        self.assertEqual(dirty["branch"], "dirty-branch")

    def test_mb_is_none_when_not_measured(self):
        info = scan._git_info(self.root, measure_worktrees=False)
        for w in info["worktrees"]:
            self.assertIsNone(w["mb"])
        self.assertFalse(info["worktree_mb_measured"])
        self.assertEqual(info["worktree_mb"], 0)

    def test_mb_is_measured_when_requested(self):
        info = scan._git_info(self.root, measure_worktrees=True)
        clean = self._by_name(info["worktrees"], "clean-wt")
        self.assertIsInstance(clean["mb"], int)
        self.assertTrue(info["worktree_mb_measured"])

    def test_prunable_only_for_removed_worktree(self):
        info = scan._git_info(self.root, measure_worktrees=False)
        clean = self._by_name(info["worktrees"], "clean-wt")
        gone = self._by_name(info["worktrees"], "gone-wt")
        self.assertFalse(clean["prunable"])
        self.assertTrue(gone["prunable"])

    def test_main_worktree_is_excluded(self):
        """`git worktree list --porcelain` lists the repo's own main worktree FIRST, same as
        the old `git worktree list` this replaced — the old code's `[1:]` deliberately skipped
        it. `_git_info`'s `worktrees` must only ever contain the OTHER (linked) worktrees: 3
        were added (clean/dirty/gone), so exactly 3 rows, none of them the repo root itself."""
        info = scan._git_info(self.root, measure_worktrees=False)
        self.assertEqual(len(info["worktrees"]), 3)
        root_real = os.path.realpath(self.root)
        self.assertFalse(any(os.path.realpath(w["path"]) == root_real for w in info["worktrees"]))

    def test_prunable_worktree_degrades_without_raising(self):
        info = scan._git_info(self.root, measure_worktrees=True)   # even with measuring on
        gone = self._by_name(info["worktrees"], "gone-wt")
        self.assertIsNone(gone["dirty"])
        self.assertEqual(gone["branch"], "")
        self.assertIsNone(gone["mb"])
        self.assertEqual(gone["mtime"], "?")


class TestProjectsCarriesWorktreeFields(unittest.TestCase):
    """projects.load must carry the new scan.py fields through: worktrees_mb (sum of KNOWN
    sizes) + worktrees_mb_measured, and prunable/branch on each worktrees_detail row."""
    def _data(self, worktrees, measured):
        return {"projects": [{
            "name": "alpha", "path": "/does/not/exist/alpha", "agents": [], "skills": [],
            "commands": [], "rules": [],
            "git": {"branch": "main", "commit": "abc1234", "dirty": 0, "worktrees": worktrees,
                    "worktree_mb": sum(w["mb"] for w in worktrees if w["mb"] is not None),
                    "worktree_mb_measured": measured, "last": "2026-08-01"},
        }]}

    def test_unmeasured_sizes_carry_none_flag(self):
        from project_os import projects
        wt = [{"path": "/wt/a", "name": "a", "mb": None, "mtime": "2026-08-01", "dirty": 0,
               "branch": "feature", "prunable": False}]
        rows = projects.load(self._data(wt, measured=False))
        self.assertEqual(rows[0]["worktrees_mb"], 0)
        self.assertFalse(rows[0]["worktrees_mb_measured"])
        detail = rows[0]["worktrees_detail"][0]
        self.assertEqual(detail["branch"], "feature")
        self.assertFalse(detail["prunable"])

    def test_measured_sizes_and_prunable_row_carry_through(self):
        from project_os import projects
        wt = [{"path": "/wt/a", "name": "a", "mb": 512, "mtime": "2026-08-01", "dirty": 0,
               "branch": "feature", "prunable": False},
              {"path": "/wt/gone", "name": "gone", "mb": None, "mtime": "?", "dirty": None,
               "branch": "", "prunable": True}]
        rows = projects.load(self._data(wt, measured=True))
        self.assertEqual(rows[0]["worktrees_mb"], 512)
        self.assertTrue(rows[0]["worktrees_mb_measured"])
        gone = next(d for d in rows[0]["worktrees_detail"] if d["name"] == "gone")
        self.assertTrue(gone["prunable"])
        self.assertEqual(gone["branch"], "")


if __name__ == "__main__":
    unittest.main()
