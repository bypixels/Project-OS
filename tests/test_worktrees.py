import unittest
import _helpers  # noqa
from _env import Env
from project_os import worktrees


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
            ": '# project-os worktree cleanup — review before running; project-os never executes these itself.'\n"
            ": '# Branches are kept; only worktree directories are affected.'\n"
            "\n"
            'git -C "/repo/alpha" worktree prune\n'
            "\n"
            'git -C "/repo/alpha" worktree remove "/repo/alpha-wt/clean1"\n'
            'git -C "/repo/beta" worktree remove "/repo/beta-wt/clean2"\n'
            "\n"
            ": '# skipped (uncommitted changes): /repo/alpha-wt/dirty1'\n"
            ": '# skipped (status unknown — run: project-os scan): /repo/alpha-wt/unknown1'\n"
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


class TestWorktreesScriptUnsafePaths(unittest.TestCase):
    """Double quotes alone are not safe across the shells this script targets: `$` and `` ` ``
    still expand inside double quotes in POSIX shells (command substitution runs when the user
    pastes the line), a literal `"` in the path closes the quote early, `` ` `` is PowerShell's
    escape char, and `%`/`!` are cmd's variable markers. A path carrying any of those (or a
    control character) must never be turned into a command — only a plain space is still safe
    quoted as-is."""

    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.cleanup()

    UNSAFE_PATHS = [
        '/repo/gamma-wt/wt"quote',
        "/repo/gamma-wt/wt'quote",
        '/repo/gamma-wt/wt$(whoami)',
        '/repo/gamma-wt/wt`cmd`',
        '/repo/gamma-wt/wt%VAR%',
        '/repo/gamma-wt/wt!bang',
        '/repo/gamma-wt/wt\nline',
        '/repo/gamma-wt/wt & whoami',      # cmd.exe: & chains commands; legal in a dir name
        '/repo/gamma-wt/wt^caret',         # cmd.exe: ^ is its escape character
        '/repo/gamma-wt/wt(1)',            # cmd.exe: ( ) group commands
    ]
    SAFE_PATH_WITH_SPACE = '/repo/gamma-wt/wt with space'

    def _fixture(self):
        wts = [{"path": p, "name": f"n{i}", "mb": 1, "mtime": "2026-08-01", "dirty": 0,
                "branch": "b", "prunable": False} for i, p in enumerate(self.UNSAFE_PATHS)]
        wts.append({"path": self.SAFE_PATH_WITH_SPACE, "name": "safe", "mb": 1, "mtime": "2026-08-01",
                    "dirty": 0, "branch": "b", "prunable": False})
        return _data(_project("gamma", "/repo/gamma", wts))

    def test_unsafe_worktree_paths_are_never_emitted_as_commands_but_are_commented(self):
        text = worktrees.script(self.env.cfg, self._fixture())
        for p in self.UNSAFE_PATHS:
            self.assertNotIn(f'worktree remove "{p}"', text)
            # built through the same helper the source uses, so a path containing a literal
            # single quote (like "/repo/gamma-wt/wt'quote" above) is asserted against its
            # correctly ESCAPED form, not a naive f-string that would never match.
            self.assertIn(worktrees._comment(f"skipped (path needs manual handling — unusual characters): {p}"), text)
        # exactly one safe worktree -> exactly one remove command in the whole script
        self.assertEqual(text.count("worktree remove"), 1)

    def test_safe_path_with_a_plain_space_is_still_quoted_and_emitted(self):
        text = worktrees.script(self.env.cfg, self._fixture())
        self.assertIn(f'git -C "/repo/gamma" worktree remove "{self.SAFE_PATH_WITH_SPACE}"', text)

    def test_unsafe_repo_path_suppresses_all_of_its_worktrees_including_prune(self):
        repo = '/repo/qu"ote'
        wts = [
            {"path": f"{repo}-wt/clean", "name": "clean", "mb": 1, "mtime": "2026-08-01",
             "dirty": 0, "branch": "b", "prunable": False},
            {"path": f"{repo}-wt/gone", "name": "gone", "mb": None, "mtime": "2026-07-01",
             "dirty": None, "branch": "b", "prunable": True},
        ]
        data = _data(_project("qrepo", repo, wts))
        text = worktrees.script(self.env.cfg, data)
        self.assertNotIn("worktree prune", text)
        self.assertNotIn("worktree remove", text)
        self.assertIn(worktrees._comment(f"skipped (path needs manual handling — unusual characters): {repo}-wt/clean"), text)
        self.assertIn(worktrees._comment(f"skipped (path needs manual handling — unusual characters): {repo}-wt/gone"), text)


class TestWorktreesScriptPasteSafety(unittest.TestCase):
    """Production defect: a raw `#` line pasted into an interactive zsh (default: no
    `setopt interactive_comments`) is NOT a comment there -- it gets parsed as a real command,
    and a stray ';' inside one (the old header comment had one) chains a second real command
    right after it. Falsifiable invariant: every non-empty line of script()'s output must start
    with 'git ' (a real, reviewed command) or with ": '#" (the inert no-op form) -- nothing
    else is ever safe to leave on its own line in a script meant to be pasted whole."""

    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.cleanup()

    def _assert_every_line_is_paste_safe(self, text):
        for line in text.splitlines():
            if not line:
                continue
            self.assertTrue(line.startswith("git ") or line.startswith(": '#"),
                             f"unsafe non-command line: {line!r}")

    def test_every_line_is_a_command_or_an_inert_comment(self):
        alpha = _project("alpha", "/repo/alpha", [
            {"path": "/repo/alpha-wt/clean1", "name": "clean1", "mb": 12, "mtime": "2026-08-01",
             "dirty": 0, "branch": "feat-clean", "prunable": False},
            {"path": "/repo/alpha-wt/dirty1", "name": "dirty1", "mb": 30, "mtime": "2026-08-02",
             "dirty": 3, "branch": "feat-dirty", "prunable": False},
            {"path": "/repo/alpha-wt/gone1", "name": "gone1", "mb": None, "mtime": "2026-07-01",
             "dirty": None, "branch": "old-branch", "prunable": True},
            {"path": "/repo/alpha-wt/unknown1", "name": "unknown1", "mb": 5, "mtime": "2026-08-03",
             "dirty": -1, "branch": "feat-unk", "prunable": False},
            {"path": "/repo/alpha-wt/wt'quote", "name": "unsafeq", "mb": 1, "mtime": "2026-08-01",
             "dirty": 0, "branch": "b", "prunable": False},
            {"path": "/repo/alpha-wt/wt\nline", "name": "unsafen", "mb": 1, "mtime": "2026-08-01",
             "dirty": 0, "branch": "b", "prunable": False},
        ])
        text = worktrees.script(self.env.cfg, _data(alpha))
        self._assert_every_line_is_paste_safe(text)

    def test_empty_message_is_also_paste_safe(self):
        text = worktrees.script(self.env.cfg, _data(_project("alpha", "/repo/alpha", [])))
        self._assert_every_line_is_paste_safe(text)


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
