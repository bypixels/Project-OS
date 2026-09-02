import json, os, unittest
from unittest import mock
import _helpers  # noqa
from _env import Env
from project_os import snapshot as SNAP, sessions as SESS, scan

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

    def test_export_activity_detail_drops_absolute_files_touched(self):
        # Privacy fix: files_touched entries outside the project (absolute paths, e.g. scratch
        # files under the user's home) must never leave the machine — they leak the username.
        fake_session = {"project": "alpha", "started": "2026-08-10T09:00", "ended": None,
                         "duration_s": 60, "turns": 1, "commits": 0, "branch": "main",
                         "files_touched": ["src/a.py", "/Users/x/secret.py"],
                         "agents": {}, "skills": {}, "tokens": {"in": 1, "out": 1}, "subagents": 0}
        with mock.patch.object(SESS, "load", return_value=[fake_session]):
            out = SNAP.export_activity(self.env.cfg, detail=True)
        row = out["sessions"][0]
        self.assertEqual(row["files_touched"], ["src/a.py"])
        self.assertEqual(row["files_outside"], 1)
        self.assertNotIn("/Users/x", json.dumps(out))

    def test_export_activity_detail_never_leaks_last_tools_or_subagent_rows(self):
        # last_tools/subagent_rows are local-only fields for the UI's own session view --
        # _detail_row is an explicit whitelist and must not grow to include them.
        fake_session = {"project": "alpha", "started": "2026-08-10T09:00", "ended": None,
                         "duration_s": 60, "turns": 1, "commits": 0, "branch": "main",
                         "files_touched": [], "agents": {}, "skills": {},
                         "tokens": {"in": 1, "out": 1}, "subagents": 0,
                         "last_tools": [{"name": "Bash", "detail": "rm -rf /", "ts": "2026-08-10T09:00:00Z"}],
                         "subagent_rows": [{"name": "agent-1", "tokens": 999}]}
        with mock.patch.object(SESS, "load", return_value=[fake_session]):
            out = SNAP.export_activity(self.env.cfg, detail=True)
        dumped = json.dumps(out)
        self.assertNotIn("last_tools", dumped)
        self.assertNotIn("subagent_rows", dumped)
        self.assertNotIn("rm -rf", dumped)

    def test_export_activity_detail_never_leaks_agent_names_or_subagent_tool_names(self):
        # F3 "permission drift" fields (sessions.py): local-only, same discipline as
        # last_tools/subagent_rows above -- _detail_row is an explicit whitelist and must not
        # grow to include them, or a subagent's per-invocation tool_use activity would leave
        # the machine through `project-os export` / hub / the MCP server.
        fake_session = {"project": "alpha", "started": "2026-08-10T09:00", "ended": None,
                         "duration_s": 60, "turns": 1, "commits": 0, "branch": "main",
                         "files_touched": [], "agents": {}, "skills": {},
                         "tokens": {"in": 1, "out": 1}, "subagents": 0,
                         "agent_names": {"exec-w": "worker"},
                         "subagent_tool_names": {"exec-w": {"Bash": 91}}}
        with mock.patch.object(SESS, "load", return_value=[fake_session]):
            out = SNAP.export_activity(self.env.cfg, detail=True)
        dumped = json.dumps(out)
        self.assertNotIn("agent_names", dumped)
        self.assertNotIn("subagent_tool_names", dumped)
        self.assertNotIn("exec-w", dumped)

    def test_detail_row_tokens_are_exact_historical_whitelist(self):
        row = SNAP._detail_row({"project": "alpha", "tokens": {
            "in": 1, "out": 2, "cache_read": 3, "cache_write": 4,
            "thinking": 99, "thinking_lines": 2, "future": "leak"
        }}, titles=False)
        self.assertEqual(set(row["tokens"]), {"in", "out", "cache_read", "cache_write"})
        self.assertEqual(row["tokens"], {"in": 1, "out": 2, "cache_read": 3, "cache_write": 4})

class TestExportActivityRefreshesRegistry(unittest.TestCase):
    # Review finding C: export_activity only ever READ the session registry (sessions.load) —
    # on a machine that never ran `project-os activity`, the registry is empty and export --activity
    # silently ships an empty payload. export_activity is a CLI call, not a request-thread hot
    # path, so it must refresh itself first.
    def test_export_activity_refreshes_without_a_prior_manual_refresh(self):
        env = Env()
        try:
            out = SNAP.export_activity(env.cfg)   # note: no env.refresh_sessions() call before this
            self.assertTrue(out["aggregated"])
        finally:
            env.cleanup()


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

class TestExportAgentsCarryContractFields(unittest.TestCase):
    # E1: hub's renderAgentDetail crashed with "Cannot read properties of undefined (reading
    # 'length')" because export() agent rows never carried critical/warnings — a teammate on
    # another machine had no way to see WHY an agent is invalid. desc is the frontmatter
    # description (truncated), never the full body/prompt, and "path" (local-only) stays out.
    def test_export_agents_carry_critical_warnings_and_desc_not_path(self):
        env = Env()
        try:
            out = SNAP.export(env.cfg)
            row = next(a for a in out["agents"] if a["name"] == "reviewer" and a["project"] == "alpha")
            self.assertEqual(row["critical"], [])
            self.assertIsInstance(row["warnings"], list)
            self.assertEqual(row["desc"], "Reviews things carefully")
            self.assertNotIn("path", row)
        finally:
            env.cleanup()

    def test_export_agents_desc_truncated_to_300_chars(self):
        env = Env()
        try:
            long_desc = "x" * 500
            open(os.path.join(env.claude, "agents", "longdesc.md"), "w").write(
                f"---\nname: longdesc\ndescription: {long_desc}\nmodel: sonnet\ntools: Read\n---\nBody.\n")
            scan.save(env.cfg, scan.run(env.cfg))
            out = SNAP.export(env.cfg)
            row = next(a for a in out["agents"] if a["name"] == "longdesc")
            self.assertEqual(len(row["desc"]), 300)
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
