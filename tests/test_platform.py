"""Cross-platform behaviour, simulated (real Windows/macOS/Linux runs happen in CI)."""
import os, sys, tempfile, unittest, shutil
from unittest import mock
import _helpers  # noqa

def _can_symlink():
    import os, tempfile
    try:
        with tempfile.TemporaryDirectory() as d:
            os.symlink(d, os.path.join(d, "l")); return True
    except (OSError, NotImplementedError):
        return False
from cabina import host, config as CFG, roster as R_, usage as U, scan as SC, skills as SK

class TestPaths(unittest.TestCase):
    def test_windows_defaults(self):
        with mock.patch.object(host.sys, "platform", "win32"), mock.patch.object(host.os, "name", "nt"), \
             mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\d\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\d\AppData\Local"}):
            d = host.default_dirs()
            self.assertTrue(d["config"].endswith(os.path.join("Roaming", "cabina")))
            self.assertTrue(d["state"].endswith(os.path.join("Local", "cabina")))
    def test_mac_defaults(self):
        with mock.patch.object(host.sys, "platform", "darwin"), mock.patch.object(host.os, "name", "posix"), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_CONFIG_HOME", None); os.environ.pop("XDG_DATA_HOME", None)
            d = host.default_dirs()
            self.assertTrue(d["config"].endswith(os.path.join(".config", "cabina")))
            self.assertTrue(d["state"].endswith(os.path.join(".local", "share", "cabina")))
    def test_xdg_respected(self):
        with mock.patch.object(host.sys, "platform", "linux"), mock.patch.object(host.os, "name", "posix"), \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x/cfg", "XDG_DATA_HOME": "/x/data"}):
            d = host.default_dirs()
            self.assertEqual(d["config"], os.path.join("/x/cfg", "cabina")); self.assertEqual(d["state"], os.path.join("/x/data", "cabina"))
    def test_tool_homes_are_home_relative_everywhere(self):
        d = host.default_dirs()
        self.assertEqual(d["claude_home"], os.path.join(os.path.expanduser("~"), ".claude"))
        self.assertEqual(d["codex_home"], os.path.join(os.path.expanduser("~"), ".codex"))
    def test_config_uses_platform_state_dir(self):
        cfg = CFG.load("/nonexistent")
        self.assertEqual(cfg["state_dir"], host.default_dirs()["state"])

class TestNoGrep(unittest.TestCase):
    """Windows has no grep/du: every caller must fall back to Python, never fail open."""
    def test_usage_extract_without_grep(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "s.jsonl"), "w").write('{"timestamp":"2026-08-01T00:00:00Z","x":{"subagent_type":"a"}}\n')
            with mock.patch.object(U.shutil, "which", lambda n: None):
                self.assertEqual(U.extract_agents(d)["a"]["n"], 1)
    def test_references_without_grep_still_finds(self):
        with tempfile.TemporaryDirectory() as t:
            ch = os.path.join(t, "claude"); os.makedirs(os.path.join(ch, "agents")); os.makedirs(os.path.join(ch, "commands"))
            open(os.path.join(ch, "agents", "reviewer.md"), "w").write("---\nname: reviewer\ndescription: d\nmodel: sonnet\ntools: Read\n---\n")
            open(os.path.join(ch, "commands", "go.md"), "w").write("Use the agent `reviewer` here.\n")
            cfg = CFG._merge(CFG.DEFAULTS, {"claude_home": ch, "roots": [os.path.join(t, "none")], "state_dir": os.path.join(t, "st"), "scan": {"measure_worktrees": False}})
            data = {"projects": []}
            with mock.patch.object(R_.shutil, "which", lambda n: None):
                refs = R_.Roster(cfg, data).references("reviewer")
            self.assertEqual(len(refs), 1); self.assertTrue(refs[0].endswith("go.md"))
    def test_dir_size_without_du(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "f"), "wb").write(b"x" * 2048)
            with mock.patch.object(SC.shutil, "which", lambda n: None):
                self.assertGreaterEqual(SC._dir_mb(d), 0)

class TestSymlinkFallback(unittest.TestCase):
    @unittest.skipUnless(_can_symlink(), "symlinks not available")
    def test_archive_symlink_when_symlinks_unsupported(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as a:
            real = os.path.join(t, "origin"); os.makedirs(real); open(os.path.join(real, "SKILL.md"), "w").write("x")
            link = os.path.join(d, "link"); os.symlink(real, link)
            with mock.patch.object(SK.os, "symlink", side_effect=OSError("privilege")):
                ok, msg = SK.archive_path(link, "global", a)
            self.assertFalse(ok); self.assertTrue(os.path.lexists(link), "original link must survive a failed archive")
            self.assertTrue(os.path.exists(real))

class TestNotifyNoInjection(unittest.TestCase):
    EVIL = "x'); Remove-Item -Recurse ~ ; #\" & rm -rf ~ ; '"
    def _capture(self, platform, name):
        calls = []
        def fake_run(args, **kw): calls.append((args, kw)); return mock.Mock(returncode=0)
        with mock.patch.object(host.sys, "platform", platform), mock.patch.object(host.os, "name", name), \
             mock.patch.object(host.subprocess, "run", fake_run), mock.patch.object(host.shutil, "which", lambda n: None):
            host.notify(self.EVIL, self.EVIL, urgent=True)
        return calls
    def test_macos_text_goes_out_of_band(self):
        calls = self._capture("darwin", "posix"); self.assertEqual(len(calls), 1)
        args, kw = calls[0]; self.assertNotIn(self.EVIL, " ".join(args)); self.assertEqual(kw["env"]["CABINA_BODY"], self.EVIL)
    def test_windows_text_goes_out_of_band(self):
        calls = self._capture("win32", "nt"); self.assertEqual(len(calls), 1)
        args, kw = calls[0]; self.assertNotIn(self.EVIL, " ".join(args)); self.assertIn("$env:CABINA_TITLE", " ".join(args)); self.assertEqual(kw["env"]["CABINA_TITLE"], self.EVIL)

class TestFleetWithoutCurses(unittest.TestCase):
    def test_fleet_degrades(self):
        with mock.patch.dict(sys.modules, {"curses": None}):
            from cabina import fleet
            import importlib; importlib.reload(fleet)
            self.assertFalse(fleet.available())
            self.assertEqual(fleet.run({}), 2)

if __name__ == "__main__": unittest.main()
