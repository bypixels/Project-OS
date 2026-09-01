"""Cross-platform behaviour, simulated (real Windows/macOS/Linux runs happen in CI)."""
import os, sys, tempfile, tomllib, unittest, shutil
from unittest import mock
import _helpers  # noqa

def _can_symlink():
    import os, tempfile
    try:
        with tempfile.TemporaryDirectory() as d:
            os.symlink(d, os.path.join(d, "l")); return True
    except (OSError, NotImplementedError):
        return False
from project_os import host, config as CFG, roster as R_, scan as SC, skills as SK

class TestPaths(unittest.TestCase):
    def test_windows_defaults(self):
        with mock.patch.object(host.sys, "platform", "win32"), mock.patch.object(host.os, "name", "nt"), \
             mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\d\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\d\AppData\Local"}):
            d = host.default_dirs()
            self.assertTrue(d["config"].endswith(os.path.join("Roaming", "project-os")))
            self.assertTrue(d["state"].endswith(os.path.join("Local", "project-os")))
    def test_mac_defaults(self):
        with mock.patch.object(host.sys, "platform", "darwin"), mock.patch.object(host.os, "name", "posix"), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_CONFIG_HOME", None); os.environ.pop("XDG_DATA_HOME", None)
            d = host.default_dirs()
            self.assertTrue(d["config"].endswith(os.path.join(".config", "project-os")))
            self.assertTrue(d["state"].endswith(os.path.join(".local", "share", "project-os")))
    def test_xdg_respected(self):
        with mock.patch.object(host.sys, "platform", "linux"), mock.patch.object(host.os, "name", "posix"), \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x/cfg", "XDG_DATA_HOME": "/x/data"}):
            d = host.default_dirs()
            self.assertEqual(d["config"], os.path.join("/x/cfg", "project-os")); self.assertEqual(d["state"], os.path.join("/x/data", "project-os"))
    def test_tool_homes_are_home_relative_everywhere(self):
        d = host.default_dirs()
        self.assertEqual(d["claude_home"], os.path.join(os.path.expanduser("~"), ".claude"))
        self.assertEqual(d["codex_home"], os.path.join(os.path.expanduser("~"), ".codex"))
    def test_config_uses_platform_state_dir(self):
        cfg = CFG.load("/nonexistent")
        self.assertEqual(cfg["state_dir"], host.default_dirs()["state"])

class TestExampleTomlCoversDefaults(unittest.TestCase):
    """project-os config --example must show every key a user could override, not a stale subset."""
    def _leaf_paths(self, d, prefix=()):
        for k, v in d.items():
            path = prefix + (k,)
            if isinstance(v, dict):
                yield from self._leaf_paths(v, path)
            else:
                yield path

    def test_every_default_leaf_key_appears_in_the_example(self):
        example = tomllib.loads(CFG.example_toml())
        missing = []
        for path in self._leaf_paths(CFG.DEFAULTS):
            node = example
            for part in path:
                if not isinstance(node, dict) or part not in node:
                    missing.append(".".join(path))
                    break
                node = node[part]
        self.assertEqual(missing, [], f"keys missing from example_toml(): {missing}")

    def test_state_dir_is_not_a_hardcoded_unix_path(self):
        example_text = CFG.example_toml()
        self.assertNotIn("$PROJECT_OS_CONFIG", example_text,
                          "state_dir has no $PROJECT_OS_CONFIG override mechanism; the comment must not claim one")
        parsed = tomllib.loads(example_text)
        self.assertEqual(os.path.expanduser(parsed["state_dir"]), CFG.DEFAULTS["state_dir"],
                          "the example's state_dir must be THIS platform's actual default, not a hardcoded Unix path")

class TestNoGrep(unittest.TestCase):
    """Windows has no grep/du: every caller must fall back to Python, never fail open.

    D-F2: usage.py's grep/no-grep fallback (`_lines`/`extract`/`extract_agents`/
    `extract_skills`) was removed entirely — the Tarea 43 offset-based `_scan_file` is now the
    ONLY reader, plain `open()`, identical on every OS, no grep/shutil branch left to test.
    `test_usage_extract_without_grep` (formerly here) is gone rather than adapted: there is no
    "without grep" behavior left to distinguish for usage.py. roster.py's `references()` (grep
    over agent/skill mentions) and scan.py's `du`-based `_dir_mb` are unrelated subsystems that
    still branch on tool presence — the two tests below keep covering those."""
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
        args, kw = calls[0]; self.assertNotIn(self.EVIL, " ".join(args)); self.assertEqual(kw["env"]["PROJECT_OS_BODY"], self.EVIL)
    def test_windows_text_goes_out_of_band(self):
        calls = self._capture("win32", "nt"); self.assertEqual(len(calls), 1)
        args, kw = calls[0]; self.assertNotIn(self.EVIL, " ".join(args)); self.assertIn("$env:PROJECT_OS_TITLE", " ".join(args)); self.assertEqual(kw["env"]["PROJECT_OS_TITLE"], self.EVIL)

class TestFleetWithoutCurses(unittest.TestCase):
    def test_fleet_degrades(self):
        with mock.patch.dict(sys.modules, {"curses": None}):
            from project_os import fleet
            import importlib; importlib.reload(fleet)
            self.assertFalse(fleet.available())
            self.assertEqual(fleet.run({}), 2)


class TestOpenTerminal(unittest.TestCase):
    """host.open_terminal(path): opens a terminal emulator AT path, never types/runs a command,
    always picks the binary itself from a per-OS allowlist, never via shell=True."""
    def _capture(self, platform, name, which_map, isdir=True):
        calls = []
        def fake_popen(args, **kw): calls.append((args, kw)); return mock.Mock()
        with mock.patch.object(host.sys, "platform", platform), mock.patch.object(host.os, "name", name), \
             mock.patch.object(host.subprocess, "Popen", fake_popen), \
             mock.patch.object(host.shutil, "which", lambda n: which_map.get(n)), \
             mock.patch.object(host.os.path, "isdir", return_value=isdir):
            ok, msg = host.open_terminal("/some/dir")
        return ok, msg, calls

    def test_refuses_non_directory_without_launching_anything(self):
        ok, msg, calls = self._capture("darwin", "posix", {}, isdir=False)
        self.assertFalse(ok)
        self.assertEqual(calls, [])

    def test_macos_opens_terminal_app(self):
        ok, msg, calls = self._capture("darwin", "posix", {})
        self.assertTrue(ok, msg)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["open", "-a", "Terminal", "/some/dir"])

    def test_windows_uses_windows_terminal_when_present(self):
        ok, msg, calls = self._capture("win32", "nt", {"wt": r"C:\wt.exe"})
        self.assertTrue(ok, msg)
        self.assertEqual(calls[0][0], ["wt", "-d", "/some/dir"])

    def test_windows_falls_back_to_powershell_without_wt(self):
        # Follow-up fix: cmd.exe is a real shell that re-parses text (%VAR%, &, ^, () survive
        # double quotes) -- routing the path through `cmd /c start powershell ...` contradicted
        # the "never a path a shell would re-parse" guarantee. Launch powershell directly instead,
        # in a new console window, with -LiteralPath so no wildcard/escape interpretation happens.
        ok, msg, calls = self._capture("win32", "nt", {})
        self.assertTrue(ok, msg)
        self.assertEqual(calls[0][0], ["powershell", "-NoExit", "-Command", "Set-Location", "-LiteralPath", "/some/dir"])
        self.assertNotIn("cmd", calls[0][0])
        # creationflags must be looked up via getattr with a safe fallback, so importing/running
        # this on non-Windows (where CREATE_NEW_CONSOLE does not exist) never breaks
        self.assertIn("creationflags", calls[0][1])
        self.assertEqual(calls[0][1]["creationflags"], getattr(host.subprocess, "CREATE_NEW_CONSOLE", 0))

    def test_windows_fallback_never_uses_cmd_exe(self):
        import inspect
        src = inspect.getsource(host.open_terminal)
        self.assertNotIn('"cmd"', src)

    def test_linux_prefers_x_terminal_emulator(self):
        ok, msg, calls = self._capture("linux", "posix", {"x-terminal-emulator": "/usr/bin/x-terminal-emulator", "gnome-terminal": "/usr/bin/gnome-terminal", "konsole": "/usr/bin/konsole", "xterm": "/usr/bin/xterm"})
        self.assertTrue(ok, msg)
        self.assertEqual(calls[0][0], ["x-terminal-emulator", "--working-directory=/some/dir"])

    def test_linux_falls_back_to_gnome_terminal(self):
        ok, msg, calls = self._capture("linux", "posix", {"gnome-terminal": "/usr/bin/gnome-terminal", "konsole": "/usr/bin/konsole", "xterm": "/usr/bin/xterm"})
        self.assertEqual(calls[0][0], ["gnome-terminal", "--working-directory=/some/dir"])

    def test_linux_falls_back_to_konsole(self):
        ok, msg, calls = self._capture("linux", "posix", {"konsole": "/usr/bin/konsole", "xterm": "/usr/bin/xterm"})
        self.assertEqual(calls[0][0], ["konsole", "--workdir", "/some/dir"])

    def test_linux_falls_back_to_xterm_with_cwd_not_argv(self):
        ok, msg, calls = self._capture("linux", "posix", {"xterm": "/usr/bin/xterm"})
        self.assertEqual(calls[0][0], ["xterm"])
        self.assertEqual(calls[0][1].get("cwd"), "/some/dir")

    def test_linux_none_found(self):
        ok, msg, calls = self._capture("linux", "posix", {})
        self.assertFalse(ok)
        self.assertIn("no terminal emulator", msg)
        self.assertEqual(calls, [])

    def test_never_uses_shell_true(self):
        for platform, name, which_map in (("darwin", "posix", {}), ("win32", "nt", {}),
                                           ("win32", "nt", {"wt": "x"}), ("linux", "posix", {"xterm": "x"})):
            _, _, calls = self._capture(platform, name, which_map)
            for args, kw in calls:
                self.assertNotEqual(kw.get("shell"), True)
                self.assertIsInstance(args, list)


if __name__ == "__main__": unittest.main()
