import io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock
import _helpers  # noqa
from _env import Env
from cabina import scan

class TestActivityCommand(unittest.TestCase):
    def test_activity_json_lists_sessions(self):
        env = Env(); scan.save(env.cfg, scan.run(env.cfg))
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
            cfgp = f.name
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        r = subprocess.run([sys.executable, "-m", "cabina", "--config", cfgp, "activity", "--json"],
                            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        items = json.loads(r.stdout)
        self.assertTrue(any(s["project"] == "alpha" for s in items))
        os.unlink(cfgp); env.cleanup()

class TestExportActivity(unittest.TestCase):
    def test_export_activity_flag_and_project_filter(self):
        env = Env(); scan.save(env.cfg, scan.run(env.cfg)); env.refresh_sessions()
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
            cfgp = f.name
        outdir = tempfile.mkdtemp(); outp = os.path.join(outdir, "export.json")
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        r = subprocess.run([sys.executable, "-m", "cabina", "--config", cfgp, "export", "--activity", "--detail", "--project", "alpha", "-o", outp],
                            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.load(open(outp))
        self.assertIn("activity", data)
        self.assertTrue(data["activity"]["sessions"])
        self.assertTrue(all(s["project"] == "alpha" for s in data["activity"]["sessions"]))
        os.unlink(cfgp); env.cleanup()

class TestHubCommand(unittest.TestCase):
    def test_hub_command_calls_serve_hub_with_dir_and_port(self):
        from cabina import cli as CLI
        called = {}
        def fake(dir_, cfg, port=None, open_browser=True):
            called.update(dir=dir_, port=port, open_browser=open_browser)
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("cabina.hub.serve_hub", fake):
                CLI.main(["hub", d, "--port", "9999", "--no-open"])
        self.assertEqual(called["dir"], d); self.assertEqual(called["port"], 9999); self.assertFalse(called["open_browser"])

class TestCompareCommand(unittest.TestCase):
    """M3: a missing or unreadable export file used to blow up with a raw FileNotFoundError /
    JSONDecodeError traceback instead of the clean `error: ...` + exit 2 pattern used elsewhere
    in main() (see the `export --activity` ValueError branch just above it)."""
    def test_compare_missing_file_prints_clean_error(self):
        from cabina import cli as CLI
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.json"); b = os.path.join(d, "missing.json")
            json.dump({"agents": [], "skills": [], "projects": []}, open(a, "w"))
            buf = io.StringIO()
            with mock.patch("sys.stderr", buf):
                rc = CLI.main(["compare", a, b])
            self.assertEqual(rc, 2)
            self.assertIn("error:", buf.getvalue())
            self.assertIn(b, buf.getvalue())

    def test_compare_invalid_json_prints_clean_error(self):
        from cabina import cli as CLI
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.json"); b = os.path.join(d, "bad.json")
            json.dump({"agents": [], "skills": [], "projects": []}, open(a, "w"))
            open(b, "w").write("{not valid json")
            buf = io.StringIO()
            with mock.patch("sys.stderr", buf):
                rc = CLI.main(["compare", a, b])
            self.assertEqual(rc, 2)
            self.assertIn("error:", buf.getvalue())


class TestAgentsRosterDetailColumn(unittest.TestCase):
    """M0 (ii): the roster's 'detail' column was truncated with a flat [:38] slice, which
    cuts mid-word whenever the 38th character lands inside a word. The alpha fixture's
    shadowing `reviewer` agent carries the warning "shadows a global agent with the same
    name without declaring `overrides: global`" -- [:38] of that lands on "...the same n"
    (a bare trailing "n" off of "name"). textwrap.shorten(width=38) breaks on a word
    boundary and appends a placeholder ("…") instead."""
    def test_long_detail_is_shortened_on_a_word_boundary(self):
        import argparse
        from cabina import cli as CLI
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            a = argparse.Namespace(action="list", name=None, project=None, force=False,
                                    invalid=False, unused=False, json=False, tool=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                CLI._agents(env.cfg, a)
            out = buf.getvalue()
            line = next(l for l in out.splitlines() if l.startswith("reviewer") and "alpha" in l)
            self.assertNotRegex(line.rstrip(), r"\bthe same n$")
            self.assertIn("…", line)
        finally:
            env.cleanup()


class _FakeStderr(io.StringIO):
    def __init__(self, tty): super().__init__(); self._tty = tty
    def isatty(self): return self._tty


class TestAgentsUsageScanHint(unittest.TestCase):
    """H2 (CLI part): `cabina agents` refreshes usage history (a grep over every transcript
    under ~/.claude/projects) with zero feedback, which can take ~10s and looks hung. When
    stderr is a tty, print a one-line heads-up before R.load() kicks that off; stay silent
    when stderr is redirected/piped (scripts, tests, CI)."""
    def _run(self, tty):
        import argparse
        from cabina import cli as CLI
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            a = argparse.Namespace(action="list", name=None, project=None, force=False,
                                    invalid=False, unused=False, json=True, tool=None)
            err = _FakeStderr(tty)
            with mock.patch("sys.stderr", err), redirect_stdout(io.StringIO()):
                CLI._agents(env.cfg, a)
            return err.getvalue()
        finally:
            env.cleanup()

    def test_prints_hint_on_a_tty(self):
        self.assertIn("scanning usage history", self._run(tty=True))

    def test_silent_when_not_a_tty(self):
        self.assertNotIn("scanning usage history", self._run(tty=False))


class TestHooksCommand(unittest.TestCase):
    """H1: `--cmd` on the hooks subparser used to share argparse's own `dest="cmd"` with the
    top-level subcommand selector, so `a.cmd` got overwritten and `cabina hooks` fell through
    to the final `server.serve(...)` branch instead of running the hooks branch at all."""
    def test_hooks_prints_snippet_and_never_starts_the_server(self):
        from cabina import cli as CLI
        buf = io.StringIO()
        with mock.patch("cabina.server.serve") as srv:
            with redirect_stdout(buf):
                rc = CLI.main(["hooks"])
        self.assertEqual(rc, 0)
        srv.assert_not_called()
        self.assertIn("PreToolUse", buf.getvalue())
        self.assertIn("SessionStart", buf.getvalue())

    def test_hooks_cmd_flag_is_reflected_in_the_snippet(self):
        from cabina import cli as CLI
        buf = io.StringIO()
        with mock.patch("cabina.server.serve") as srv:
            with redirect_stdout(buf):
                CLI.main(["hooks", "--cmd", "mycab"])
        srv.assert_not_called()
        self.assertIn("mycab guard", buf.getvalue())

    def test_hooks_write_writes_the_settings_file(self):
        from cabina import cli as CLI
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "settings.json")
            buf = io.StringIO()
            with mock.patch("cabina.server.serve") as srv:
                with redirect_stdout(buf):
                    rc = CLI.main(["hooks", "--write", "--settings", sp])
            srv.assert_not_called()
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(sp))
            written = json.load(open(sp))
            self.assertIn("PreToolUse", written["hooks"])


if __name__ == "__main__":
    unittest.main()
