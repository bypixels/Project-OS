import os, json, tempfile, unittest
from unittest import mock
import _helpers  # noqa
from project_os import harness as H

def project(d, harness_md=True, memory=True, hooks=("a.sh", "b.sh"), wired=("a.sh", "b.sh"), rules=2, workflows=1):
    c = os.path.join(d, ".claude"); os.makedirs(os.path.join(c, "hooks"), exist_ok=True)
    if harness_md: open(os.path.join(c, "HARNESS.md"), "w").write("#")
    if memory: open(os.path.join(c, "MEMORY.md"), "w").write("#")
    open(os.path.join(d, "CLAUDE.md"), "w").write("#")
    for h in hooks: open(os.path.join(c, "hooks", h), "w").write("#!/bin/sh")
    if rules: os.makedirs(os.path.join(c, "rules")); [open(os.path.join(c, "rules", f"r{i}.md"), "w").write("x") for i in range(rules)]
    if workflows: os.makedirs(os.path.join(c, "workflows")); [open(os.path.join(c, "workflows", f"w{i}.js"), "w").write("x") for i in range(workflows)]
    json.dump({"hooks": {"PreToolUse": [{"hooks": [{"command": f"$CLAUDE_PROJECT_DIR/.claude/hooks/{h}"} for h in wired]}]}}, open(os.path.join(c, "settings.json"), "w"))
    return d

TABLE = """| Date | Task | Vehicle | Agents | Tokens | Funnel | Consq. | Notes |
|---|---|---|---|---|---|---|---|
| 2026-07-29 | Follow-ups | loose agents | writer, skeptic | ~194k in subagents | 6 → 0 → 2 | 1 (HIGH: x) | n1 |
| 2026-07-31 | Claims | loose agent | web-researcher | n/a | 5 claims → 1 refuted → 3 verified | 0 | n2 |
"""

class TestHarness(unittest.TestCase):
    def test_complete(self):
        with tempfile.TemporaryDirectory() as d:
            e = H.project_state(project(d)); self.assertEqual((e["level"], e["hooks_dead"], e["missing"]), ("complete", [], []))
    def test_dead_hook(self):
        with tempfile.TemporaryDirectory() as d:
            e = H.project_state(project(d, hooks=("a.sh", "b.sh", "orphan.sh"), wired=("a.sh", "b.sh")))
            self.assertEqual((e["hooks_dead"], e["level"]), (["orphan.sh"], "partial"))
    def test_broken_hook(self):
        with tempfile.TemporaryDirectory() as d:
            e = H.project_state(project(d, hooks=("a.sh",), wired=("a.sh", "ghost.sh")))
            self.assertEqual((e["hooks_broken"], e["level"]), (["ghost.sh"], "partial"))
    def test_helper_not_dead(self):
        with tempfile.TemporaryDirectory() as d:
            e = H.project_state(project(d, hooks=("a.sh", "b.sh", "test-hooks.sh"), wired=("a.sh", "b.sh")))
            self.assertEqual((e["hooks_dead"], e["hooks_helpers"], e["level"]), ([], ["test-hooks.sh"], "complete"))
    def test_none(self):
        with tempfile.TemporaryDirectory() as d:
            e = H.project_state(project(d, harness_md=False, memory=False, hooks=(), wired=(), rules=0, workflows=0))
            self.assertEqual(e["level"], "none")
    def test_workflows_optional(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(H.project_state(project(d, workflows=0))["level"], "complete")
    def test_runlog(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "harness-runs.md"); open(p, "w").write(TABLE); r = H.read_runlog(p)
            self.assertEqual([x["date"] for x in r], ["2026-07-31", "2026-07-29"])
            self.assertEqual((r[1]["tokens_k"], r[1]["funnel"], r[1]["consequential"]), (194, [6, 0, 2], 1))
            self.assertEqual((r[0]["tokens_k"], r[0]["funnel"], r[0]["consequential"]), (None, [5, 1, 3], 0))
    def test_summary(self):
        s = H.summarize([{"tokens_k": 200, "consequential": 2}, {"tokens_k": 100, "consequential": 0}, {"tokens_k": None, "consequential": 1}])
        self.assertEqual((s["runs"], s["consequential"], s["tokens_k_measured"], s["k_per_consequential"]), (3, 3, 300, 150))
    def test_missing_runlog(self): self.assertEqual(H.read_runlog("/no/x.md"), [])

    def test_memory_getmtime_toctou_does_not_crash(self):
        """MEMORY.md passes os.path.isfile (line 34/46) but is deleted before os.path.getmtime
        runs on it (line 56) -- a real TOCTOU race. Must not crash project_state(); memory_days
        must fall back to None, the same value it already gets when isfile() itself catches the
        absence (see the ternary at line 56 today)."""
        with tempfile.TemporaryDirectory() as d:
            root = project(d)
            mem = os.path.join(root, ".claude", "MEMORY.md")
            real_getmtime = os.path.getmtime

            def flaky_getmtime(path):
                if path == mem:
                    raise OSError("deleted between isfile() and getmtime()")
                return real_getmtime(path)

            with mock.patch("os.path.getmtime", side_effect=flaky_getmtime):
                e = H.project_state(root)   # must not raise
            self.assertIsNone(e["memory_days"])
if __name__ == "__main__": unittest.main()
