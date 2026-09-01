"""scan._git_info: worktree dirty/branch must always be real (cheap), size stays opt-in,
and prunable worktrees (directory removed) must degrade cleanly instead of raising."""
import os, shutil, subprocess, tempfile, unittest
import _helpers  # noqa
from _env import Env
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


class TestSoloCodexDiscovery(unittest.TestCase):
    """A directory with AGENTS.md at its root but no .claude/ (a Codex-only project) must be
    discovered as a project too -- not just directories that have .claude/ (see CLAUDE.md's
    'find_claude_dirs searches only .claude')."""
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_solo_agents_md_project_is_discovered(self):
        data = scan.run(self.env.cfg)
        names = {p["name"] for p in data["projects"]}
        self.assertIn("beta-codex-only", names)
        beta = next(p for p in data["projects"] if p["name"] == "beta-codex-only")
        self.assertTrue(beta["agents_md"])
        self.assertEqual(beta["agents"], [])
        self.assertEqual(beta["path"], self.env.codex_only)
        roots = scan.project_roots(self.env.cfg, data)
        self.assertEqual(roots["beta-codex-only"], self.env.codex_only)

    def test_project_with_both_claude_and_agents_md_is_not_duplicated(self):
        """alpha has BOTH .claude/ and AGENTS.md -- it must appear exactly once, via the
        .claude/ path, never a second time as a would-be solo-Codex entry."""
        data = scan.run(self.env.cfg)
        names = [p["name"] for p in data["projects"]]
        self.assertEqual(names.count("alpha"), 1)


class TestRootIsClaudeDir(unittest.TestCase):
    """Regression: the old walk matched a `.claude` dir by `basename(dp) == ".claude"`, which
    also caught a configured root that IS itself a `.claude` dir. The new walk only recognizes
    `.claude` as a CHILD (`".claude" in dn`), so a root that is a `.claude` dir directly is never
    its own child and was silently dropped."""
    def test_root_that_is_itself_a_claude_dir_is_found(self):
        with tempfile.TemporaryDirectory() as t:
            root = os.path.join(t, "x", ".claude")
            os.makedirs(os.path.join(root, "agents"))
            found, codex_only = scan.find_claude_dirs([root], set())
            self.assertEqual(found, [os.path.normpath(root)])
            self.assertEqual(codex_only, [])


class TestCodexOnlyRequiresOwnGit(unittest.TestCase):
    """A bare AGENTS.md used to qualify as a Codex-only project discovery at ANY depth -- in
    the real environment this caught a subdirectory of an existing Claude project and a
    vendor/composer package, neither of which is a project. New rule: a codex_only candidate
    must have its OWN `.git` entry in that same directory (dir or file -- worktrees use a
    file), i.e. its own repository."""
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def _codex_only(self):
        _, codex_only = scan.find_claude_dirs(self.env.cfg["roots"], set(self.env.cfg["scan"]["skip_dirs"]))
        return codex_only

    def test_nested_agents_md_without_git_inside_claude_project_not_discovered(self):
        sub = os.path.join(self.env.alpha, "some-subdir")
        os.makedirs(sub)
        open(os.path.join(sub, "AGENTS.md"), "w").write("# nested, no .git\n")
        self.assertNotIn(sub, self._codex_only())

    def test_vendor_package_agents_md_without_git_not_discovered(self):
        vendor = os.path.join(self.env.projects, "some-app", "vendor", "some", "package")
        os.makedirs(vendor)
        open(os.path.join(vendor, "AGENTS.md"), "w").write("# vendored package docs\n")
        self.assertNotIn(vendor, self._codex_only())

    def test_agents_md_with_own_git_dir_is_discovered(self):
        solo = os.path.join(self.env.projects, "solo-with-git")
        os.makedirs(os.path.join(solo, ".git"))
        open(os.path.join(solo, "AGENTS.md"), "w").write("# solo codex project\n")
        self.assertIn(solo, self._codex_only())

    def test_agents_md_with_own_git_file_worktree_is_discovered(self):
        """git worktrees use a `.git` FILE (a gitdir pointer), not a directory."""
        solo = os.path.join(self.env.projects, "solo-worktree")
        os.makedirs(solo)
        open(os.path.join(solo, ".git"), "w").write("gitdir: /somewhere/.git/worktrees/solo-worktree\n")
        open(os.path.join(solo, "AGENTS.md"), "w").write("# solo codex worktree\n")
        self.assertIn(solo, self._codex_only())


if __name__ == "__main__":
    unittest.main()
