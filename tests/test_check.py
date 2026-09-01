import unittest
import _helpers  # noqa
from _env import Env
from cabina import scan, check


class TestCheckWarnAgentsDetail(unittest.TestCase):
    """M0 (i): the "kind" of a contract warning was derived with
    w.split("(")[0].split(":")[0].strip(), which happily splits on a ":" that sits
    INSIDE a backtick-quoted span. The alpha fixture's `reviewer` agent shadows the
    global one without `overrides: global` (see contract.py's warning text), and
    that ":" landed right in the middle of the backtick span -> the rendered detail
    showed a dangling, unbalanced "`overrides" instead of the full `overrides: global`."""
    def test_shadow_warning_detail_keeps_backtick_span_intact(self):
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            warn = next(f for f in findings if f["title"].endswith("contract warnings"))
            self.assertIn("`overrides: global`", warn["detail"])
        finally:
            env.cleanup()


class TestCheckProjectAttribution(unittest.TestCase):
    """Findings that are genuinely about one project (dead hook, a document-shaped file in
    agents/) carry a `projects` list naming it; findings about the environment as a whole
    (e.g. a stale/missing scan cache) carry no `projects` key at all — never guessed."""
    def test_dead_hook_and_docs_in_agents_carry_alpha_project(self):
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            dead = next(f for f in findings if "settings.json wires" in f["title"] or "ningún settings.json cablea" in f["title"])
            self.assertIn("projects", dead)
            self.assertIn("alpha", dead["projects"])
            docs = next(f for f in findings if "document" in f["title"].lower() or f["title"].endswith("agents/"))
            self.assertIn("projects", docs)
            self.assertIn("alpha", docs["projects"])
        finally:
            env.cleanup()

    def test_global_finding_has_no_projects_key(self):
        env = Env()
        try:
            # no scan cache saved -> "no scan" is a global finding, never attributed to a project
            findings = check.run(env.cfg, quick=True)
            no_scan = next(f for f in findings if "scan" in f["title"].lower())
            self.assertNotIn("projects", no_scan)
        finally:
            env.cleanup()


class TestCheckStaleWorktrees(unittest.TestCase):
    """dirty/branch are now always real (see scan._git_info); the stale-clean-worktree
    finding must (a) skip prunable rows — they have no directory, they belong to
    `git worktree prune`, not to this warning — and (b) never print a fake '0.0 GB'
    when sizes were not measured."""
    OLD_MTIME = "2025-07-14"   # well past the default 14-day threshold

    def _stale_row(self, name, mb=None, prunable=False, dirty=0):
        return {"path": f"/wt/{name}", "name": name, "mb": mb, "mtime": self.OLD_MTIME,
                "dirty": None if prunable else dirty, "branch": "" if prunable else "feature",
                "prunable": prunable}

    def _set_git(self, alpha, worktrees, measured):
        alpha["git"] = {"branch": "main", "commit": "abc1234", "dirty": 0, "worktrees": worktrees,
                        "worktree_mb": sum(w["mb"] for w in worktrees if w["mb"] is not None),
                        "worktree_mb_measured": measured, "last": "2026-08-01"}

    def test_prunable_stale_row_is_skipped(self):
        env = Env()
        try:
            data = scan.run(env.cfg)
            alpha = next(p for p in data["projects"] if p["name"] == "alpha")
            self._set_git(alpha, [self._stale_row("gone-wt", prunable=True)], measured=False)
            scan.save(env.cfg, data)
            findings = check.run(env.cfg, quick=True)
            self.assertFalse(any("worktree" in f["title"].lower() and f["sev"] == "warn" for f in findings))
        finally:
            env.cleanup()

    def test_unmeasured_size_does_not_print_fake_gb(self):
        env = Env()
        try:
            data = scan.run(env.cfg)
            alpha = next(p for p in data["projects"] if p["name"] == "alpha")
            self._set_git(alpha, [self._stale_row("clean-wt", mb=None)], measured=False)
            scan.save(env.cfg, data)
            findings = check.run(env.cfg, quick=True)
            stale = next(f for f in findings if "worktree" in f["title"].lower() and f["sev"] == "warn")
            self.assertNotIn("0.0 GB", stale["title"])
            self.assertIn("alpha", stale["projects"])
        finally:
            env.cleanup()

    def test_unmeasured_size_title_says_not_measured_not_a_question_mark(self):
        # "? GB" is indecipherable on its own -- unknown must say "unknown", not "?".
        env = Env()
        try:
            data = scan.run(env.cfg)
            alpha = next(p for p in data["projects"] if p["name"] == "alpha")
            self._set_git(alpha, [self._stale_row("clean-wt", mb=None)], measured=False)
            scan.save(env.cfg, data)
            findings = check.run(env.cfg, quick=True)
            stale = next(f for f in findings if "worktree" in f["title"].lower() and f["sev"] == "warn")
            self.assertNotIn("? GB", stale["title"])
            self.assertIn("size not measured", stale["title"])
        finally:
            env.cleanup()

    def test_measured_size_still_reports_real_gb(self):
        env = Env()
        try:
            data = scan.run(env.cfg)
            alpha = next(p for p in data["projects"] if p["name"] == "alpha")
            self._set_git(alpha, [self._stale_row("clean-wt", mb=2048)], measured=True)
            scan.save(env.cfg, data)
            findings = check.run(env.cfg, quick=True)
            stale = next(f for f in findings if "worktree" in f["title"].lower() and f["sev"] == "warn")
            self.assertIn("2.0 GB", stale["title"])
        finally:
            env.cleanup()


if __name__ == "__main__":
    unittest.main()
