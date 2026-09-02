import argparse, io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock
import _helpers  # noqa
from _env import Env
from project_os import scan
from project_os.i18n import t

class TestActivityCommand(unittest.TestCase):
    def test_activity_json_lists_sessions(self):
        env = Env(); scan.save(env.cfg, scan.run(env.cfg))
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
            cfgp = f.name
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        r = subprocess.run([sys.executable, "-m", "project_os", "--config", cfgp, "activity", "--json"],
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
        r = subprocess.run([sys.executable, "-m", "project_os", "--config", cfgp, "export", "--activity", "--detail", "--project", "alpha", "-o", outp],
                            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.load(open(outp))
        self.assertIn("activity", data)
        self.assertTrue(data["activity"]["sessions"])
        self.assertTrue(all(s["project"] == "alpha" for s in data["activity"]["sessions"]))
        os.unlink(cfgp); env.cleanup()

class TestHubCommand(unittest.TestCase):
    def test_hub_command_calls_serve_hub_with_dir_and_port(self):
        from project_os import cli as CLI
        called = {}
        def fake(dir_, cfg, port=None, open_browser=True):
            called.update(dir=dir_, port=port, open_browser=open_browser)
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("project_os.hub.serve_hub", fake):
                CLI.main(["hub", d, "--port", "9999", "--no-open"])
        self.assertEqual(called["dir"], d); self.assertEqual(called["port"], 9999); self.assertFalse(called["open_browser"])

class TestCompareCommand(unittest.TestCase):
    """M3: a missing or unreadable export file used to blow up with a raw FileNotFoundError /
    JSONDecodeError traceback instead of the clean `error: ...` + exit 2 pattern used elsewhere
    in main() (see the `export --activity` ValueError branch just above it)."""
    def test_compare_missing_file_prints_clean_error(self):
        from project_os import cli as CLI
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
        from project_os import cli as CLI
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
        from project_os import cli as CLI
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
    """H2 (CLI part): `project-os agents` refreshes usage history (a grep over every transcript
    under ~/.claude/projects) with zero feedback, which can take ~10s and looks hung. When
    stderr is a tty, print a one-line heads-up before R.load() kicks that off; stay silent
    when stderr is redirected/piped (scripts, tests, CI)."""
    def _run(self, tty):
        import argparse
        from project_os import cli as CLI
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
        self.assertIn(t("en", "agents.scanning_usage"), self._run(tty=True))

    def test_silent_when_not_a_tty(self):
        self.assertNotIn(t("en", "agents.scanning_usage"), self._run(tty=False))


class TestHooksCommand(unittest.TestCase):
    """H1: `--cmd` on the hooks subparser used to share argparse's own `dest="cmd"` with the
    top-level subcommand selector, so `a.cmd` got overwritten and `project-os hooks` fell through
    to the final `server.serve(...)` branch instead of running the hooks branch at all."""
    def test_hooks_prints_snippet_and_never_starts_the_server(self):
        from project_os import cli as CLI
        buf = io.StringIO()
        with mock.patch("project_os.server.serve") as srv:
            with redirect_stdout(buf):
                rc = CLI.main(["hooks"])
        self.assertEqual(rc, 0)
        srv.assert_not_called()
        self.assertIn("PreToolUse", buf.getvalue())
        self.assertIn("SessionStart", buf.getvalue())

    def test_hooks_cmd_flag_is_reflected_in_the_snippet(self):
        from project_os import cli as CLI
        buf = io.StringIO()
        with mock.patch("project_os.server.serve") as srv:
            with redirect_stdout(buf):
                CLI.main(["hooks", "--cmd", "mycab"])
        srv.assert_not_called()
        self.assertIn("mycab guard", buf.getvalue())

    def test_hooks_write_writes_the_settings_file(self):
        # hooks_write refuses to wire a `cmd` that does not resolve on PATH -- mock resolution
        # so this test never depends on whether "project-os" happens to be installed on the
        # machine running the suite (it wasn't on any CI runner under the tool's previous
        # name either; it only ever passed locally by coincidence of a pre-existing install).
        from project_os import cli as CLI
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "settings.json")
            buf = io.StringIO()
            with mock.patch("project_os.server.serve") as srv, \
                 mock.patch("project_os.guard.shutil.which", return_value="/usr/local/bin/project-os"):
                with redirect_stdout(buf):
                    rc = CLI.main(["hooks", "--write", "--settings", sp])
            srv.assert_not_called()
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(sp))
            written = json.load(open(sp))
            self.assertIn("PreToolUse", written["hooks"])


class TestCliDocstringListsSubcommands(unittest.TestCase):
    """E2: cli.py's module docstring used to hand-list 6 of the 15 registered subcommands.
    Get the real list straight from argparse (spying on add_parser while main() builds the
    parser, then bailing out before it actually runs anything) so this fails the moment a new
    subcommand is added without documenting it."""

    def _registered_subcommand_names(self):
        from project_os import cli as CLI
        names = []
        orig_add_parser = argparse._SubParsersAction.add_parser

        def spy(self, name, **kwargs):
            names.append(name)
            return orig_add_parser(self, name, **kwargs)

        with mock.patch.object(argparse._SubParsersAction, "add_parser", spy), \
             mock.patch.object(argparse.ArgumentParser, "parse_args", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                CLI.main([])
        return names

    def test_docstring_mentions_every_registered_subcommand(self):
        from project_os import cli as CLI
        names = self._registered_subcommand_names()
        self.assertTrue(names, "spy did not observe any add_parser calls")
        missing = [n for n in names if n not in CLI.__doc__]
        self.assertEqual(missing, [], f"subcommands missing from cli.py's module docstring: {missing}")


class TestWorktreesCommand(unittest.TestCase):
    """W2: `project-os worktrees` is a report — it only ever prints a summary + a cleanup script for
    the user to run themselves (never executes anything). The alpha fixture in tests/_env.py is
    not a real git repo, so scan sees no worktrees at all: this exercises the "nothing to clean
    up" path end to end without needing a real git worktree setup (that belongs to
    test_worktrees.py, which drives the generator directly against synthetic scan data)."""

    def test_worktrees_command_prints_summary_and_script(self):
        from project_os import cli as CLI
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            a = argparse.Namespace(project=None, json=False)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = CLI._worktrees(env.cfg, a)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("nothing to clean up", out)
        finally:
            env.cleanup()

    def test_worktrees_command_stdout_is_entirely_paste_safe(self):
        # Full-output regression: not just script()'s own text, but the SUMMARY LINE printed
        # right before it. That line used to carry raw `backticks` around the suggested
        # command -- backticks are command substitution in zsh/bash, so pasting the whole
        # stdout block actually RAN `project-os scan --worktrees` (a real, reported defect,
        # worse than the original one: it triggers a slow scan).
        from project_os import cli as CLI
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            data = {"projects": [{"name": "alpha", "path": env.alpha, "git": {"worktrees": [
                {"path": f"{env.alpha}-wt/dirty1", "name": "dirty1", "mb": None, "mtime": "2026-08-01",
                 "dirty": 3, "branch": "b", "prunable": False},
            ]}}]}
            a = argparse.Namespace(project=None, json=False)
            buf = io.StringIO()
            with mock.patch("project_os.scan.ensure", return_value=data):
                with redirect_stdout(buf):
                    rc = CLI._worktrees(env.cfg, a)
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("unmeasured", out)     # exercises the exact branch that had backticks
            self.assertNotIn("`", out)
            for line in out.splitlines():
                if not line:
                    continue
                self.assertTrue(line.startswith("git ") or line.startswith(": '#"),
                                 f"unsafe non-command line in CLI stdout: {line!r}")
        finally:
            env.cleanup()

    def test_worktrees_command_json(self):
        from project_os import cli as CLI
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            a = argparse.Namespace(project=None, json=True)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = CLI._worktrees(env.cfg, a)
            self.assertEqual(rc, 0)
            d = json.loads(buf.getvalue())
            self.assertIn("summary", d); self.assertIn("script", d); self.assertIn("rows", d)
            self.assertEqual(d["summary"]["total"], 0)
        finally:
            env.cleanup()


class TestAgentsInvalidDetail(unittest.TestCase):
    """`--invalid` used to only ever show the roster table, whose 'detail' column is
    textwrap.shorten()'d to 38 chars and shows only the FIRST warning/critical -- a
    non-developer user had to ask someone else what a warning meant. `--invalid` now also
    prints a detail block per problem agent: every warning/critical in FULL (no truncation),
    plus a 3-part plain-language explanation (what it means / does the agent still work /
    what to do) for messages project-os recognizes."""

    def test_agent_detail_explains_an_unknown_field(self):
        from project_os import cli as CLI
        from project_os.contract import Contract
        txt = "---\nname: my-agent\ndescription: Does things\nmodel: sonnet\ntools: Read\nsparkle: yes\n---\nBody.\n"
        r = Contract().validate_text(txt, "my-agent")
        lines = CLI._agent_detail("en", r)
        joined = "\n".join(lines)
        self.assertIn("fields Claude Code does not read: sparkle", joined)
        self.assertIn(t("en", "agents.explain.unknown_fields"), joined)
        self.assertIn(t("en", "agents.explain.unknown_fields.action"), joined)

    def test_invalid_flag_prints_full_warning_without_ellipsis(self):
        import argparse
        from project_os import cli as CLI
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            a = argparse.Namespace(action="list", name=None, project=None, force=False,
                                    invalid=True, unused=False, json=False, tool=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                CLI._agents(env.cfg, a)
            out = buf.getvalue()
            full_warning = "shadows a global agent with the same name without declaring `overrides: global`"
            self.assertIn(full_warning, out)
            self.assertIn(t("en", "agents.explain.shadow_undeclared"), out)
        finally:
            env.cleanup()


def _unwrap(s):
    """argparse wraps help text at the terminal width, so a translated string with an em dash
    or long clause can land split across a newline in captured stdout. Collapse all whitespace
    runs to a single space before substring-matching so wrapping doesn't fail an otherwise
    correct assertion."""
    return " ".join(s.split())


class TestHelpI18n(unittest.TestCase):
    """`--help` used to be English-only no matter what `language` said in config, because
    argparse bakes its help text in at parser-construction time and main() used to load config
    only AFTER parse_args() ran. Descriptions and help= strings now come from i18n.py, resolved
    from config BEFORE the parser is built (README's known limitation shrinks accordingly:
    the translated chrome is the subcommand/flag help text, not argparse's own "usage:" /
    "positional arguments:" / "options:" wording, which stays English on purpose)."""

    def _run_help(self, extra_argv, config_env=None):
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        env = {**os.environ, "PYTHONPATH": src}
        if config_env is not None:
            env["PROJECT_OS_CONFIG"] = config_env
        return subprocess.run([sys.executable, "-m", "project_os", *extra_argv],
                               capture_output=True, text=True, env=env, timeout=30)

    def test_help_is_spanish_when_config_says_es(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write('language = "es"\n')
            cfgp = f.name
        try:
            r = self._run_help(["--config", cfgp, "--help"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(_unwrap(t("es", "cli.help.description")), _unwrap(r.stdout))
        finally:
            os.unlink(cfgp)

    def test_help_is_english_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            # No real config file at this path: exercises the actual default (English).
            r = self._run_help(["--help"], config_env=os.path.join(d, "missing.toml"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(_unwrap(t("en", "cli.help.description")), _unwrap(r.stdout))

    def test_help_falls_back_to_english_on_corrupt_config(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("not valid toml {{{")
            cfgp = f.name
        try:
            r = self._run_help(["--config", cfgp, "--help"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(_unwrap(t("en", "cli.help.description")), _unwrap(r.stdout))
        finally:
            os.unlink(cfgp)

    def test_subcommand_help_is_translated_too(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write('language = "es"\n')
            cfgp = f.name
        try:
            r = self._run_help(["--config", cfgp, "check", "--help"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(t("es", "cli.help.check_quick"), r.stdout)
        finally:
            os.unlink(cfgp)


class TestCheckUpstreamHealthlogExclusion(unittest.TestCase):
    """--upstream's own findings (`extra` ALWAYS includes `overrides`/`version` by design, since
    those are project-os's own conventions, never in Claude Code's doc) must never pollute the
    30-day health trend in health.jsonl -- otherwise every networked run adds an info finding
    that has nothing to do with the environment's health, and the trend measures the flag
    instead. health.jsonl must log the SAME counts whether or not --upstream was passed."""

    def _cfg_file(self, env):
        f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
        f.close()
        return f.name

    def test_healthlog_append_ignores_upstream_findings(self):
        from project_os import cli as CLI
        env = Env()
        cfgp = self._cfg_file(env)
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            doc = "| Field | Required |\n| :--- | :--- |\n| `name` | Yes |\n| `description` | Yes |\n| `model` | No |\n| `tools` | No |\n"
            calls = []
            def fake_append(cfg, findings, **kw):
                calls.append(list(findings)); return True
            with mock.patch("project_os.upstream.fetch_doc", return_value=(doc, None)), \
                 mock.patch("project_os.healthlog.append", side_effect=fake_append):
                with redirect_stdout(io.StringIO()):
                    CLI.main(["--config", cfgp, "check", "--upstream"])
                    CLI.main(["--config", cfgp, "check"])
            self.assertEqual(len(calls), 2, "healthlog.append should run once per check call")
            self.assertEqual(calls[0], calls[1], "the --upstream run appended different findings than the plain run")
        finally:
            os.unlink(cfgp); env.cleanup()


class TestCheckRepoRejectsUpstream(unittest.TestCase):
    """`--upstream` needs the network; `check --repo` is the CI mode that runs offline, on its
    own, with no home and no cache. Silently accepting and ignoring the flag there used to hide
    that the two are incompatible -- reject it with a clear message instead."""

    def test_repo_mode_rejects_upstream_with_a_clear_message(self):
        from project_os import cli as CLI
        with tempfile.TemporaryDirectory() as d:
            buf_err = io.StringIO()
            with mock.patch("sys.stderr", buf_err), redirect_stdout(io.StringIO()):
                rc = CLI.main(["check", "--repo", d, "--upstream"])
            self.assertEqual(rc, 2)
            self.assertIn(t("en", "cli.error.upstream_repo"), buf_err.getvalue())


class TestCheckSinceLastCheckProjectQualifier(unittest.TestCase):
    """A multi-project finding's identities are "<id>@<project1>", "<id>@<project2>" (same title
    for both -- healthlog.identities()). Without a project qualifier in the rendered "since last
    check" line, both would print the IDENTICAL title with no way to tell which project appeared
    or resolved. cli.py's check branch must render "+ <title> — <project>" for a qualified
    identity, and the bare "+ <title>" for one without an "@"."""

    def _cfg_file(self, env):
        f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
        f.close()
        return f.name

    def test_new_multi_project_finding_renders_distinct_lines_per_project(self):
        from project_os import cli as CLI, check as CHECK
        env = Env()
        cfgp = self._cfg_file(env)
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            with mock.patch.object(CHECK, "run", return_value=[]):
                with redirect_stdout(io.StringIO()):
                    CLI.main(["--config", cfgp, "check"])
            multi = {"id": "check.invalid_agents", "sev": "crit", "title": "3 invalid agents",
                     "detail": "", "fix": "", "projects": ["alpha", "beta"]}
            with mock.patch.object(CHECK, "run", return_value=[multi]):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    CLI.main(["--config", cfgp, "check"])
            out = buf.getvalue()
            self.assertIn("  + 3 invalid agents — alpha", out)
            self.assertIn("  + 3 invalid agents — beta", out)
        finally:
            os.unlink(cfgp); env.cleanup()

    def test_resolved_multi_project_finding_renders_distinct_lines_per_project(self):
        """Same "@"-qualified identity split as the `new` path above, but for `since["resolved"]`
        (cli.py's second `_changes_line` call, ~line 155): a multi-project finding that
        disappears must render one "resolved: ... — <project>" line per project, not a single
        unqualified line that can't say which project resolved."""
        from project_os import cli as CLI, check as CHECK
        env = Env()
        cfgp = self._cfg_file(env)
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            with mock.patch.object(CHECK, "run", return_value=[]):
                with redirect_stdout(io.StringIO()):
                    CLI.main(["--config", cfgp, "check"])
            multi = {"id": "check.invalid_agents", "sev": "crit", "title": "3 invalid agents",
                     "detail": "", "fix": "", "projects": ["alpha", "beta"]}
            with mock.patch.object(CHECK, "run", return_value=[multi]):
                with redirect_stdout(io.StringIO()):
                    CLI.main(["--config", cfgp, "check"])
            with mock.patch.object(CHECK, "run", return_value=[]):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    CLI.main(["--config", cfgp, "check"])
            out = buf.getvalue()
            self.assertIn("resolved: 3 invalid agents — alpha", out)
            self.assertIn("resolved: 3 invalid agents — beta", out)
        finally:
            os.unlink(cfgp); env.cleanup()


class TestCheckSinceLastCheckOrdering(unittest.TestCase):
    """healthlog.changes(cfg, findings) must run BEFORE healthlog.append(cfg, findings) in cli.py's
    check branch (per cli.py's own comment). Swapping the two makes changes() diff a run's
    findings against the line it JUST wrote -- itself -- which is always empty and prints "no
    changes" even though the finding set actually changed between the two runs."""

    def _cfg_file(self, env):
        f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
        f.close()
        return f.name

    def test_second_run_reports_the_new_finding_not_no_changes(self):
        from project_os import cli as CLI, check as CHECK
        env = Env()
        cfgp = self._cfg_file(env)
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            alpha = {"id": "check.no_scan", "sev": "warn", "title": "Alpha finding", "detail": "", "fix": ""}
            beta = {"id": "check.stale_scan", "sev": "warn", "title": "Beta finding", "detail": "", "fix": ""}
            with mock.patch.object(CHECK, "run", return_value=[alpha]):
                with redirect_stdout(io.StringIO()):
                    CLI.main(["--config", cfgp, "check"])
            with mock.patch.object(CHECK, "run", return_value=[beta]):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    CLI.main(["--config", cfgp, "check"])
            out = buf.getvalue()
            self.assertIn("Since last check (", out)
            self.assertIn("  + Beta finding", out)
            self.assertNotIn("no changes since", out.lower())
        finally:
            os.unlink(cfgp); env.cleanup()


class TestCheckSinceLastCheckUpstreamFilter(unittest.TestCase):
    """`healthlog.changes(cfg, upstream_filtered)` must diff the SAME filtered list that
    `healthlog.append` writes -- an --upstream finding (check.py's `add(..., upstream=True)`) is
    about project-os itself, not the environment, and must never show up as a "new"/"resolved"
    entry in the "since last check" block (companion to TestCheckUpstreamHealthlogExclusion,
    which covers the append side of this same rule)."""

    def _cfg_file(self, env):
        f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
        f.close()
        return f.name

    def test_upstream_finding_never_appears_as_a_change(self):
        from project_os import cli as CLI, check as CHECK
        env = Env()
        cfgp = self._cfg_file(env)
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            normal = {"id": "check.no_scan", "sev": "warn", "title": "Normal finding", "detail": "", "fix": ""}
            up = {"id": "check.upstream_extra", "sev": "info", "title": "Upstream finding", "detail": "", "fix": "", "upstream": True}
            with mock.patch.object(CHECK, "run", return_value=[normal]):
                with redirect_stdout(io.StringIO()):
                    CLI.main(["--config", cfgp, "check"])
            with mock.patch.object(CHECK, "run", return_value=[normal, up]):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    CLI.main(["--config", cfgp, "check"])
            out = buf.getvalue()
            self.assertNotIn("+ Upstream finding", out)
            self.assertIn("no changes since", out.lower())
        finally:
            os.unlink(cfgp); env.cleanup()


if __name__ == "__main__":
    unittest.main()
