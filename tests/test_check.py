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


if __name__ == "__main__":
    unittest.main()
