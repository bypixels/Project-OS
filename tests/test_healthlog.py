import json, os, subprocess, sys, tempfile, unittest
from unittest import mock
import _helpers  # noqa
from _env import Env
from project_os import healthlog as HL, server as SRV


def _findings(crit=0, warn=0, info=0):
    F = []
    for _ in range(crit): F.append({"sev": "crit", "title": "x"})
    for _ in range(warn): F.append({"sev": "warn", "title": "x"})
    for _ in range(info): F.append({"sev": "info", "title": "x"})
    return F


class TestHealthlog(unittest.TestCase):
    def test_append_writes_first_line(self):
        env = Env()
        try:
            self.assertTrue(HL.append(env.cfg, _findings(crit=1, warn=2)))
            lines = HL.read(env.cfg)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["crit"], 1)
            self.assertEqual(lines[0]["warn"], 2)
            self.assertEqual(lines[0]["info"], 0)
            self.assertIn("when", lines[0])
        finally:
            env.cleanup()

    def test_append_skips_when_unchanged_and_recent(self):
        env = Env()
        try:
            self.assertTrue(HL.append(env.cfg, _findings(crit=1)))
            self.assertFalse(HL.append(env.cfg, _findings(crit=1)))
            self.assertEqual(len(HL.read(env.cfg)), 1)
        finally:
            env.cleanup()

    def test_append_writes_even_if_unchanged_after_24h(self):
        env = Env()
        try:
            self.assertTrue(HL.append(env.cfg, _findings(crit=1)))
            later = HL._now() + __import__("datetime").timedelta(hours=25)
            self.assertTrue(HL.append(env.cfg, _findings(crit=1), now=later))
            self.assertEqual(len(HL.read(env.cfg)), 2)
        finally:
            env.cleanup()

    def test_prune_keeps_newest_lines_via_tmp_replace(self):
        env = Env()
        try:
            from datetime import datetime, timedelta
            p = HL.path(env.cfg)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            old = (datetime.now().astimezone() - timedelta(days=200)).isoformat(timespec="seconds")
            new = datetime.now().astimezone().isoformat(timespec="seconds")
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"when": old, "crit": 9, "warn": 0, "info": 0}) + "\n")
                f.write(json.dumps({"when": new, "crit": 1, "warn": 0, "info": 0}) + "\n")
            cfg = dict(env.cfg); cfg["check"] = dict(env.cfg["check"]); cfg["check"]["history_days"] = 180
            real_replace = os.replace
            with mock.patch.object(HL.os, "replace", side_effect=real_replace) as m:
                HL._prune(p, cfg["check"]["history_days"])
                m.assert_called_once()
            lines = HL.read(cfg)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["crit"], 1)
        finally:
            env.cleanup()

    def test_read_skips_malformed_lines(self):
        env = Env()
        try:
            p = HL.path(env.cfg)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("not json at all\n")
                f.write(json.dumps({"when": "2026-08-01T00:00:00-06:00", "crit": 0, "warn": 0, "info": 0}) + "\n")
            lines = HL.read(env.cfg)
            self.assertEqual(len(lines), 1)
        finally:
            env.cleanup()

    def test_read_missing_file_returns_empty_list(self):
        env = Env()
        try:
            self.assertEqual(HL.read(env.cfg), [])
        finally:
            env.cleanup()

    def test_append_never_raises(self):
        env = Env()
        try:
            with mock.patch.object(HL, "_should_append", side_effect=Exception("boom")):
                self.assertFalse(HL.append(env.cfg, _findings(crit=1)))
        finally:
            env.cleanup()

    def test_cli_check_writes_a_health_line(self):
        env = Env()
        try:
            open(os.path.join(env.alpha, ".claude", "agents", "broken.md"), "w").write(
                "---\nname: broken\nmodel: sonnet\n---\nBody without a description.\n")
            from project_os import scan
            scan.save(env.cfg, scan.run(env.cfg))
            with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
                f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\n"
                        f"state_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
                cfgp = f.name
            src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
            r = subprocess.run([sys.executable, "-m", "project_os", "--config", cfgp, "check", "--json"],
                                capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, timeout=60)
            os.unlink(cfgp)
            self.assertEqual(r.returncode, 1, r.stderr)  # crit finding -> exit 1
            self.assertTrue(os.path.isfile(HL.path(env.cfg)))
            self.assertEqual(len(HL.read(env.cfg)), 1)
        finally:
            env.cleanup()

    def test_server_api_health_writes_a_health_line(self):
        env = Env()
        try:
            app = SRV.App(env.cfg)
            app.api_health()
            self.assertTrue(os.path.isfile(HL.path(env.cfg)))
            self.assertEqual(len(HL.read(env.cfg)), 1)
        finally:
            env.cleanup()

    def test_append_recovers_from_naive_when_in_last_line(self):
        # A `when` stored without a tz offset (e.g. hand-edited, or written by a future bug)
        # must not permanently wedge the log: `now - when` on an aware/naive mismatch raises
        # TypeError, and _should_append must treat that as "yes, append" rather than let the
        # exception escape to append()'s outer try/except and return False forever.
        from datetime import datetime
        env = Env()
        try:
            p = HL.path(env.cfg)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            naive_when = datetime.now().isoformat(timespec="seconds")  # no tzinfo, looks recent
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"when": naive_when, "crit": 1, "warn": 0, "info": 0}) + "\n")
            self.assertTrue(HL.append(env.cfg, _findings(crit=1)))  # same counts as the naive line
            self.assertEqual(len(HL.read(env.cfg)), 2)
        finally:
            env.cleanup()

    def test_cli_check_quick_does_not_write_a_health_line(self):
        env = Env()
        try:
            open(os.path.join(env.alpha, ".claude", "agents", "broken.md"), "w").write(
                "---\nname: broken\nmodel: sonnet\n---\nBody without a description.\n")
            from project_os import scan
            scan.save(env.cfg, scan.run(env.cfg))
            with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
                f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\n"
                        f"state_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
                cfgp = f.name
            src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
            r = subprocess.run([sys.executable, "-m", "project_os", "--config", cfgp, "check", "--quick", "--json"],
                                capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, timeout=60)
            os.unlink(cfgp)
            self.assertEqual(r.returncode, 1, r.stderr)  # still a crit finding -> exit 1
            self.assertEqual(HL.read(env.cfg), [])  # quick run: no trend line written
        finally:
            env.cleanup()


class TestHealthlogIdentities(unittest.TestCase):
    """F2 "since last check": health.jsonl lines now carry an "ids" map (identity string ->
    title) alongside the counts, so a later run can diff what appeared/resolved. A finding
    carrying `projects` expands to one identity per project ("<id>@<project>"); a finding
    without one keeps the bare id; a finding lacking "id" entirely (defensive: an older or
    foreign caller) is skipped rather than crashing the log."""

    def test_identities_bare_id_without_projects(self):
        findings = [{"sev": "warn", "title": "no scan cache", "id": "check.no_scan"}]
        self.assertEqual(HL.identities(findings), {"check.no_scan": "no scan cache"})

    def test_identities_expands_per_project(self):
        findings = [{"sev": "warn", "title": "dead hooks", "id": "check.dead_hooks", "projects": ["alpha", "beta"]}]
        self.assertEqual(HL.identities(findings), {"check.dead_hooks@alpha": "dead hooks", "check.dead_hooks@beta": "dead hooks"})

    def test_identities_skips_findings_without_id(self):
        findings = [{"sev": "warn", "title": "no id here"}]
        self.assertEqual(HL.identities(findings), {})

    def test_should_append_true_on_composition_change_with_equal_counts(self):
        # Two runs with the SAME (crit, warn, info) totals but a different finding underneath
        # must not collapse into a no-op -- the old counts-only dedup would have missed this.
        env = Env()
        try:
            f1 = [{"sev": "warn", "title": "A", "id": "check.dead_hooks"}]
            f2 = [{"sev": "warn", "title": "B", "id": "check.twins"}]
            self.assertTrue(HL.append(env.cfg, f1))
            self.assertTrue(HL.append(env.cfg, f2))
            self.assertEqual(len(HL.read(env.cfg)), 2)
        finally:
            env.cleanup()

    def test_old_format_last_line_forces_append_and_changes_is_none(self):
        # A last line written before "ids" existed must not be compared for composition (there
        # is nothing to compare) -- append once as a baseline migration, but `changes()` must
        # report "unknown", never a false "nothing changed".
        env = Env()
        try:
            p = HL.path(env.cfg)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"when": HL._now().isoformat(timespec="seconds"), "crit": 0, "warn": 0, "info": 0}) + "\n")
            findings = [{"sev": "warn", "title": "A", "id": "check.dead_hooks"}]
            self.assertIsNone(HL.changes(env.cfg, findings))
            self.assertTrue(HL.append(env.cfg, findings))
            self.assertEqual(len(HL.read(env.cfg)), 2)
        finally:
            env.cleanup()

    def test_appended_line_carries_ids(self):
        env = Env()
        try:
            HL.append(env.cfg, [{"sev": "warn", "title": "dead hooks", "id": "check.dead_hooks", "projects": ["alpha"]}])
            lines = HL.read(env.cfg)
            self.assertEqual(lines[0]["ids"], {"check.dead_hooks@alpha": "dead hooks"})
        finally:
            env.cleanup()


class TestHealthlogDiff(unittest.TestCase):
    """`diff()` is the pure comparison; `changes()` reads the last stored line off disk and
    calls it. Both must treat "no baseline yet" the same as "baseline predates ids": unknown,
    never a false "nothing changed" (same doctrine as tokens.thinking_lines == 0 elsewhere)."""

    def test_diff_none_when_no_last_line(self):
        self.assertIsNone(HL.diff(None, []))

    def test_diff_none_when_last_has_no_ids(self):
        last = {"when": "2026-01-01T00:00:00-06:00", "crit": 0, "warn": 0, "info": 0}
        self.assertIsNone(HL.diff(last, []))

    def test_diff_new_and_resolved(self):
        last = {"when": "2026-01-01T00:00:00-06:00",
                "ids": {"check.dead_hooks": "old dead hooks", "check.no_scan": "no scan cache"}}
        findings = [{"sev": "warn", "title": "still dead hooks", "id": "check.dead_hooks"},
                    {"sev": "crit", "title": "brand new twins", "id": "check.twins"}]
        d = HL.diff(last, findings)
        self.assertEqual(d["prev_when"], "2026-01-01T00:00:00-06:00")
        self.assertEqual(d["new"], [["check.twins", "brand new twins"]])
        self.assertEqual(d["resolved"], [["check.no_scan", "no scan cache"]])

    def test_diff_empty_when_identical(self):
        last = {"when": "2026-01-01T00:00:00-06:00", "ids": {"check.dead_hooks": "t"}}
        findings = [{"sev": "warn", "title": "t", "id": "check.dead_hooks"}]
        d = HL.diff(last, findings)
        self.assertEqual(d["new"], [])
        self.assertEqual(d["resolved"], [])

    def test_changes_reads_last_line_from_disk(self):
        env = Env()
        try:
            HL.append(env.cfg, [{"sev": "warn", "title": "old", "id": "check.no_scan"}])
            findings = [{"sev": "warn", "title": "new", "id": "check.dead_hooks"}]
            ch = HL.changes(env.cfg, findings)
            self.assertIsNotNone(ch)
            self.assertEqual(ch["new"], [["check.dead_hooks", "new"]])
            self.assertEqual(ch["resolved"], [["check.no_scan", "old"]])
        finally:
            env.cleanup()

    def test_changes_none_when_no_last_line(self):
        env = Env()
        try:
            self.assertIsNone(HL.changes(env.cfg, [{"sev": "warn", "title": "x", "id": "check.no_scan"}]))
        finally:
            env.cleanup()

    def test_diff_none_when_when_is_unparseable(self):
        # A last line can carry "ids" but an unparseable "when" (hand-edited, or truncated by a
        # crash mid-write) -- rendering that as "no changes since None" would be a lie: there is
        # no reliable baseline to compare against, same doctrine as a missing "ids" field.
        last = {"when": "not-a-date", "ids": {"check.dead_hooks": "t"}}
        findings = [{"sev": "warn", "title": "t", "id": "check.dead_hooks"}]
        self.assertIsNone(HL.diff(last, findings))

    def test_diff_none_when_when_is_missing(self):
        last = {"ids": {"check.dead_hooks": "t"}}
        findings = [{"sev": "warn", "title": "t", "id": "check.dead_hooks"}]
        self.assertIsNone(HL.diff(last, findings))


if __name__ == "__main__":
    unittest.main()
