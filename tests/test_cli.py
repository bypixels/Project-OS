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
