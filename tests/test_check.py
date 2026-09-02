import os
import shutil
import time
import unittest
from unittest import mock
import _helpers  # noqa
from _env import Env, AGENT
from project_os import scan, check, usage


class TestCheckUpstream(unittest.TestCase):
    """`project-os check --upstream` (opt-in only -- `check.run` never touches the network
    unless `upstream=True` is passed explicitly) compares contract.known_fields against
    Claude Code's own sub-agents documentation. The fetch is mocked in every test here: no
    real network call is ever made by the suite."""

    def test_doc_with_extra_field_is_a_warning(self):
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            doc = "| Field | Type |\n|---|---|\n| `name` | s |\n| `description` | s |\n| `model` | s |\n| `tools` | s |\n| `brand-new-field` | s |\n"
            with mock.patch("project_os.upstream.fetch_doc", return_value=(doc, None)):
                findings = check.run(env.cfg, quick=True, upstream=True)
            f = next((x for x in findings if "brand-new-field" in x["detail"]), None)
            self.assertIsNotNone(f, f"no finding mentions brand-new-field: {findings}")
            self.assertNotEqual(f["sev"], "crit")   # --upstream must never be able to fail the run
        finally:
            env.cleanup()

    def test_fetch_failure_is_a_neutral_info_and_exit_code_is_untouched(self):
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            with mock.patch("project_os.upstream.fetch_doc", side_effect=Exception("boom")):
                findings_upstream = check.run(env.cfg, quick=True, upstream=True)
                findings_plain = check.run(env.cfg, quick=True, upstream=False)
            crit_upstream = sum(1 for x in findings_upstream if x["sev"] == "crit")
            crit_plain = sum(1 for x in findings_plain if x["sev"] == "crit")
            self.assertEqual(crit_upstream, crit_plain)   # a fetch exception never adds a critical
            unavailable = next((x for x in findings_upstream if x["sev"] == "info" and "upstream" in x["title"].lower()
                                 or "documentation" in x["title"].lower() or "documentación" in x["title"].lower()), None)
            self.assertIsNotNone(unavailable, f"no neutral unavailable finding: {findings_upstream}")
        finally:
            env.cleanup()

    def test_ssl_failure_gets_its_own_message_with_the_fix_command(self):
        """A stock python.org install on macOS has no CA bundle, so fetch_doc reports
        reason="ssl" (see test_upstream.py) -- check must surface a DIFFERENT, specific message
        here, with the exact command to fix it, instead of the generic "no network, or the doc's
        format changed" (which would be a false diagnostic: the doc IS reachable)."""
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            with mock.patch("project_os.upstream.fetch_doc", return_value=(None, "ssl")):
                findings = check.run(env.cfg, quick=True, upstream=True)
            f = next((x for x in findings if x["sev"] == "info" and "certifi" in (x["fix"] or "")), None)
            self.assertIsNotNone(f, f"no ssl-specific finding carrying the certifi fix command: {findings}")
            self.assertNotEqual(f["sev"], "crit")
        finally:
            env.cleanup()


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


class TestCheckFindingIdentity(unittest.TestCase):
    """F2 "since last check": healthlog diffs runs by a stable per-finding identity (the i18n
    KEY of the finding, e.g. "check.dead_hooks"), stored as "id" on every finding `add()`
    produces. Every finding, from every detector, must carry a non-empty one -- a finding
    silently missing "id" would vanish from the diff instead of raising."""
    def test_every_finding_carries_a_non_empty_id(self):
        env = Env()
        try:
            open(os.path.join(env.alpha, ".claude", "agents", "broken.md"), "w").write(
                "---\nname: broken\nmodel: sonnet\n---\nBody without a description.\n")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=False)
            self.assertTrue(findings)
            for f in findings:
                self.assertIn("id", f, f"finding missing id: {f}")
                self.assertTrue(f["id"], f"finding has an empty id: {f}")
        finally:
            env.cleanup()

    def test_stale_worktrees_id_is_stable_across_measured_and_unmeasured_variants(self):
        # The title text differs (".nogb" vs the GB-bearing variant), but the identity used to
        # diff runs must not -- otherwise a worktree finding that merely gained/lost a size
        # measurement would read as "resolved" + "new" instead of "unchanged".
        env = Env()
        try:
            data = scan.run(env.cfg)
            alpha = next(p for p in data["projects"] if p["name"] == "alpha")
            alpha["git"] = {"branch": "main", "commit": "abc1234", "dirty": 0,
                             "worktrees": [{"path": "/wt/clean-wt", "name": "clean-wt", "mb": None,
                                            "mtime": "2025-07-14", "dirty": 0, "branch": "feature", "prunable": False}],
                             "worktree_mb": 0, "worktree_mb_measured": False, "last": "2026-08-01"}
            scan.save(env.cfg, data)
            findings_nogb = check.run(env.cfg, quick=True)
            stale_nogb = next(f for f in findings_nogb if "worktree" in f["title"].lower() and f["sev"] == "warn")

            data2 = scan.run(env.cfg)
            alpha2 = next(p for p in data2["projects"] if p["name"] == "alpha")
            alpha2["git"] = {"branch": "main", "commit": "abc1234", "dirty": 0,
                              "worktrees": [{"path": "/wt/clean-wt", "name": "clean-wt", "mb": 2048,
                                             "mtime": "2025-07-14", "dirty": 0, "branch": "feature", "prunable": False}],
                              "worktree_mb": 2048, "worktree_mb_measured": True, "last": "2026-08-01"}
            scan.save(env.cfg, data2)
            findings_gb = check.run(env.cfg, quick=True)
            stale_gb = next(f for f in findings_gb if "worktree" in f["title"].lower() and f["sev"] == "warn")

            self.assertNotEqual(stale_nogb["title"], stale_gb["title"])
            self.assertEqual(stale_nogb["id"], stale_gb["id"])
            self.assertEqual(stale_nogb["id"], "check.stale_worktrees")
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


class TestCheckUnusedSkills(unittest.TestCase):
    """Family #10 clone for skills (never-invoked agents already exists): a defined, valid,
    claude-tool skill that usage-skills.json never credits with an invocation is reported as an
    info finding. Codex is excluded structurally (skills.load only reads claude_home + project
    .claude dirs, never codex_home) -- Codex transcripts carry no skill invocations at all
    (see usage.py's codex_sessions docstring), so "never used" for a Codex skill would be a
    measurement lie, not a finding."""
    def test_never_invoked_claude_skill_is_reported_info(self):
        env = Env()
        try:
            os.makedirs(os.path.join(env.claude, "skills", "ghost-skill"))
            open(os.path.join(env.claude, "skills", "ghost-skill", "SKILL.md"), "w").write(
                "---\nname: ghost-skill\ndescription: never invoked\n---\n")
            data = scan.run(env.cfg)
            scan.save(env.cfg, data)
            roots = {k: v for k, v in scan.project_roots(env.cfg, data).items() if k != "global"}
            usage_path = os.path.join(env.cfg["state_dir"], "usage-skills.json")
            usage.refresh(usage_path, os.path.join(env.claude, "projects"), "skills", roots)
            findings = check.run(env.cfg, quick=False)
            f = next(x for x in findings if "ghost-skill" in (x["detail"] or ""))
            self.assertEqual(f["sev"], "info")
            self.assertNotIn("deploy", f["detail"])  # deploy WAS invoked in the fixture -- must not appear
        finally:
            env.cleanup()


class TestCheckUnusedAgentsShadowing(unittest.TestCase):
    """A homonym check (same name defined both globally and by a project) used to compare by
    NAME alone: any recorded use of the name at all -- no matter which project's cwd it came
    from -- suppressed the finding for EVERY instance of that name, including a project's own
    copy that was never actually invoked. The detector must reason per INSTANCE via by_project
    with shadowing semantics: a project's own instance is unused unless by_project credits that
    project; the global instance is unused only when n_total==0 or every recorded use is
    attributed to a project that defines its own homonym (i.e. could never have been the
    global copy)."""
    def test_project_homonym_never_used_reported_even_when_global_was_used_elsewhere(self):
        env = Env()
        try:
            # isolate: remove the fixture's own "reviewer" (global + alpha) so it can't leak
            # into the finding's `projects` list and confuse the assertion below.
            os.remove(os.path.join(env.claude, "agents", "reviewer.md"))
            os.remove(os.path.join(env.alpha, ".claude", "agents", "reviewer.md"))
            open(os.path.join(env.claude, "agents", "shared-agent.md"), "w").write(AGENT.format(n="shared-agent"))
            open(os.path.join(env.alpha, ".claude", "agents", "shared-agent.md"), "w").write(AGENT.format(n="shared-agent"))
            scan.save(env.cfg, scan.run(env.cfg))
            usage_path = os.path.join(env.cfg["state_dir"], "usage-agents.json")
            # every recorded use is attributed to "other-project", which does NOT define its own
            # "shared-agent" -- so those uses can only have been the global copy: global is used.
            usage.save(usage_path, {"shared-agent": {"n_total": 5, "last": "2026-08-05",
                                                       "by_project": {"other-project": 5}}})
            findings = check.run(env.cfg, quick=False)
            f = next(x for x in findings if "shared-agent" in (x["detail"] or ""))
            self.assertIn("alpha", f.get("projects", []))
            self.assertNotIn("global", f.get("projects", []))
        finally:
            env.cleanup()

    def test_desynced_by_project_data_does_not_falsely_flag_global(self):
        """Residual case (Codex): n_total=5, by_project={"alpha":5,"beta":1}, and only "alpha"
        defines its own homonym. Summing JUST the homonym-defining projects' counts (5) happens
        to equal n_total (5) -- but "beta", which is NOT a homonym-defining project, also has a
        recorded use that isn't accounted for anywhere (desynced data, e.g. after transcript
        rotation). That leftover use could have been the global instance -- ambiguous, so the
        detector must stay silent about the global instance, not accuse it. (alpha's own
        instance is genuinely used here too -- by_project["alpha"]==5 -- so nothing about
        "shared-agent" should be reported at all.)"""
        env = Env()
        try:
            os.remove(os.path.join(env.claude, "agents", "reviewer.md"))
            os.remove(os.path.join(env.alpha, ".claude", "agents", "reviewer.md"))
            open(os.path.join(env.claude, "agents", "shared-agent.md"), "w").write(AGENT.format(n="shared-agent"))
            open(os.path.join(env.alpha, ".claude", "agents", "shared-agent.md"), "w").write(AGENT.format(n="shared-agent"))
            scan.save(env.cfg, scan.run(env.cfg))
            usage_path = os.path.join(env.cfg["state_dir"], "usage-agents.json")
            usage.save(usage_path, {"shared-agent": {"n_total": 5, "last": "2026-08-05",
                                                       "by_project": {"alpha": 5, "beta": 1}}})
            findings = check.run(env.cfg, quick=False)
            f = next((x for x in findings if "shared-agent" in (x["detail"] or "")), None)
            self.assertIsNone(f, f)
        finally:
            env.cleanup()


class TestCheckUnusedSkillsShadowing(unittest.TestCase):
    """Same fix as TestCheckUnusedAgentsShadowing, for the skills detector (8b)."""
    def test_project_homonym_never_used_reported_even_when_global_was_used_elsewhere(self):
        env = Env()
        try:
            # isolate: remove the fixture's own "gsk" (global) and "deploy" (alpha) skills so
            # they can't leak into the finding's `projects` list.
            shutil.rmtree(os.path.join(env.claude, "skills", "gsk"))
            shutil.rmtree(os.path.join(env.alpha, ".claude", "skills", "deploy"))
            os.makedirs(os.path.join(env.claude, "skills", "shared-skill"))
            open(os.path.join(env.claude, "skills", "shared-skill", "SKILL.md"), "w").write(
                "---\nname: shared-skill\ndescription: global copy\n---\n")
            os.makedirs(os.path.join(env.alpha, ".claude", "skills", "shared-skill"))
            open(os.path.join(env.alpha, ".claude", "skills", "shared-skill", "SKILL.md"), "w").write(
                "---\nname: shared-skill\ndescription: alpha copy, never invoked\n---\n")
            scan.save(env.cfg, scan.run(env.cfg))
            usage_path = os.path.join(env.cfg["state_dir"], "usage-skills.json")
            usage.save(usage_path, {"shared-skill": {"n_total": 5, "last": "2026-08-05",
                                                       "by_project": {"other-project": 5}}})
            findings = check.run(env.cfg, quick=False)
            f = next(x for x in findings if "shared-skill" in (x["detail"] or ""))
            self.assertIn("alpha", f.get("projects", []))
            self.assertNotIn("global", f.get("projects", []))
        finally:
            env.cleanup()

    def test_desynced_by_project_data_does_not_falsely_flag_global(self):
        """Skills mirror of TestCheckUnusedAgentsShadowing's residual-case test above."""
        env = Env()
        try:
            shutil.rmtree(os.path.join(env.claude, "skills", "gsk"))
            shutil.rmtree(os.path.join(env.alpha, ".claude", "skills", "deploy"))
            os.makedirs(os.path.join(env.claude, "skills", "shared-skill"))
            open(os.path.join(env.claude, "skills", "shared-skill", "SKILL.md"), "w").write(
                "---\nname: shared-skill\ndescription: global copy\n---\n")
            os.makedirs(os.path.join(env.alpha, ".claude", "skills", "shared-skill"))
            open(os.path.join(env.alpha, ".claude", "skills", "shared-skill", "SKILL.md"), "w").write(
                "---\nname: shared-skill\ndescription: alpha copy\n---\n")
            scan.save(env.cfg, scan.run(env.cfg))
            usage_path = os.path.join(env.cfg["state_dir"], "usage-skills.json")
            usage.save(usage_path, {"shared-skill": {"n_total": 5, "last": "2026-08-05",
                                                       "by_project": {"alpha": 5, "beta": 1}}})
            findings = check.run(env.cfg, quick=False)
            f = next((x for x in findings if "shared-skill" in (x["detail"] or "")), None)
            self.assertIsNone(f, f)
        finally:
            env.cleanup()


class TestCheckUnusedProjectInstanceRequiresFullAttribution(unittest.TestCase):
    """Symmetric fix, in the PROJECT branch of both detectors: `bp.get(p, 0) == 0` accused an
    instance without checking that n_total is fully accounted for in by_project. A cwd that
    never resolved to any project root leaves usage wholly unattributed (by_project={}) even
    though n_total > 0 -- that used to read as "0 uses here", a false 'never invoked'. Fix also
    requires sum(bp.values()) == n_total, so a leftover unattributed use keeps the project
    instance silent too (same 'ambiguous -> stay silent' rule as the global branch)."""
    def test_agents_project_instance_unattributed_totals(self):
        env = Env()
        try:
            os.remove(os.path.join(env.claude, "agents", "reviewer.md"))
            os.remove(os.path.join(env.alpha, ".claude", "agents", "reviewer.md"))
            open(os.path.join(env.alpha, ".claude", "agents", "solo-agent.md"), "w").write(AGENT.format(n="solo-agent"))
            scan.save(env.cfg, scan.run(env.cfg))
            usage_path = os.path.join(env.cfg["state_dir"], "usage-agents.json")

            # (a) n_total=2, by_project={} -- 2 recorded but wholly unattributed uses. Must NOT
            # accuse alpha's instance: the leftover could be exactly this instance.
            usage.save(usage_path, {"solo-agent": {"n_total": 2, "last": "2026-08-05", "by_project": {}}})
            findings = check.run(env.cfg, quick=False)
            self.assertIsNone(next((f for f in findings if "solo-agent" in (f["detail"] or "")), None))

            # (b) n_total=0, by_project={} -- genuinely never invoked: accuse it.
            usage.save(usage_path, {"solo-agent": {"n_total": 0, "last": None, "by_project": {}}})
            findings = check.run(env.cfg, quick=False)
            f = next(x for x in findings if "solo-agent" in (x["detail"] or ""))
            self.assertIn("alpha", f["projects"])

            # (c) n_total=3, by_project={"B": 3} -- fully attributed, but to a DIFFERENT project.
            # alpha's own instance really is unused: accuse it.
            usage.save(usage_path, {"solo-agent": {"n_total": 3, "last": "2026-08-05", "by_project": {"B": 3}}})
            findings = check.run(env.cfg, quick=False)
            f = next(x for x in findings if "solo-agent" in (x["detail"] or ""))
            self.assertIn("alpha", f["projects"])
        finally:
            env.cleanup()

    def test_skills_project_instance_unattributed_totals(self):
        env = Env()
        try:
            shutil.rmtree(os.path.join(env.claude, "skills", "gsk"))
            shutil.rmtree(os.path.join(env.alpha, ".claude", "skills", "deploy"))
            os.makedirs(os.path.join(env.alpha, ".claude", "skills", "solo-skill"))
            open(os.path.join(env.alpha, ".claude", "skills", "solo-skill", "SKILL.md"), "w").write(
                "---\nname: solo-skill\ndescription: alpha only\n---\n")
            scan.save(env.cfg, scan.run(env.cfg))
            usage_path = os.path.join(env.cfg["state_dir"], "usage-skills.json")

            usage.save(usage_path, {"solo-skill": {"n_total": 2, "last": "2026-08-05", "by_project": {}}})
            findings = check.run(env.cfg, quick=False)
            self.assertIsNone(next((f for f in findings if "solo-skill" in (f["detail"] or "")), None))

            usage.save(usage_path, {"solo-skill": {"n_total": 0, "last": None, "by_project": {}}})
            findings = check.run(env.cfg, quick=False)
            f = next(x for x in findings if "solo-skill" in (x["detail"] or ""))
            self.assertIn("alpha", f["projects"])

            usage.save(usage_path, {"solo-skill": {"n_total": 3, "last": "2026-08-05", "by_project": {"B": 3}}})
            findings = check.run(env.cfg, quick=False)
            f = next(x for x in findings if "solo-skill" in (x["detail"] or ""))
            self.assertIn("alpha", f["projects"])
        finally:
            env.cleanup()


class TestCheckDesiredState(unittest.TestCase):
    """A project can declare in its own `.project-os.toml` ([desired] table) what its agent
    environment SHOULD have; `check` compares that against the scan and reports gaps as ONE
    warn finding per project. Read-only: it never creates the missing asset itself."""

    def _write(self, root, text):
        open(os.path.join(root, ".project-os.toml"), "w").write(text)

    def test_no_desired_table_is_silent(self):
        env = Env()
        try:
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            self.assertFalse(any("alpha" in (f.get("projects") or []) and "desired" in f["title"].lower() for f in findings))
        finally:
            env.cleanup()

    def test_missing_agent_and_skill_are_reported_not_the_satisfied_ones(self):
        env = Env()
        try:
            # "reviewer" and "deploy" already exist in alpha's own .claude/ (see _env.py);
            # "ghost-agent"/"ghost-skill" do not exist anywhere.
            self._write(env.alpha, '[desired.agents]\nrequired = ["reviewer", "ghost-agent"]\n'
                                    '[desired.skills]\nrequired = ["deploy", "ghost-skill"]\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = next(x for x in findings if x.get("projects") == ["alpha"] and "ghost-agent" in (x["detail"] or ""))
            self.assertEqual(f["sev"], "warn")
            self.assertIn("ghost-skill", f["detail"])
            self.assertNotIn("`reviewer`", f["detail"])
            self.assertNotIn("`deploy`", f["detail"])
        finally:
            env.cleanup()

    def test_agent_satisfied_by_global_copy_when_project_has_none_of_its_own(self):
        env = Env()
        try:
            os.remove(os.path.join(env.alpha, ".claude", "agents", "reviewer.md"))  # only the global one remains
            self._write(env.alpha, '[desired.agents]\nrequired = ["reviewer"]\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            self.assertIsNone(next((x for x in findings if x.get("projects") == ["alpha"] and "reviewer" in (x["detail"] or "")), None))
        finally:
            env.cleanup()

    def test_mcp_not_checked_is_unverifiable_not_a_missing_accusation(self):
        env = Env()   # env.cfg has scan.check_mcp = False -> data["mcp"]["checked"] is False
        try:
            self._write(env.alpha, '[desired.mcp]\nrequired = ["postgres"]\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = next(x for x in findings if x.get("projects") == ["alpha"] and "postgres" in (x["detail"] or ""))
            self.assertIn("scan --mcp", f["detail"])
            self.assertNotIn("not found", f["detail"].lower())
        finally:
            env.cleanup()

    def test_mcp_checked_and_missing_server_is_flagged(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.mcp]\nrequired = ["postgres"]\n')
            data = scan.run(env.cfg)
            data["mcp"] = {"checked": True, "servers": [{"name": "other", "target": "x", "status": "ok", "detail": ""}]}
            scan.save(env.cfg, data)
            findings = check.run(env.cfg, quick=True)
            f = next(x for x in findings if x.get("projects") == ["alpha"] and "postgres" in (x["detail"] or ""))
            self.assertNotIn("scan --mcp", f["detail"])
        finally:
            env.cleanup()

    def _desired_finding(self, findings):
        """alpha's fixture already carries an unrelated contract-warning finding with
        projects==["alpha"] (the shadowing `reviewer` agent) -- select ours by title."""
        return next((x for x in findings if x.get("projects") == ["alpha"] and "desired" in x["title"].lower()), None)

    def test_memory_missing_is_a_gap(self):
        env = Env()
        try:
            os.remove(os.path.join(env.alpha, ".claude", "MEMORY.md"))
            self._write(env.alpha, '[desired.memory]\nmax_age_days = 14\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("MEMORY.md", f["detail"])
        finally:
            env.cleanup()

    def test_memory_older_than_max_age_reports_actual_age(self):
        env = Env()
        try:
            mem = os.path.join(env.alpha, ".claude", "MEMORY.md")
            old = time.time() - 20 * 86400
            os.utime(mem, (old, old))
            self._write(env.alpha, '[desired.memory]\nmax_age_days = 14\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("20", f["detail"])
        finally:
            env.cleanup()

    def test_memory_within_max_age_is_silent(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.memory]\nmax_age_days = 14\n')   # MEMORY.md is fresh by default
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            self.assertIsNone(self._desired_finding(findings))
        finally:
            env.cleanup()

    def test_docs_status_mismatch_reports_expected_and_actual(self):
        env = Env()   # alpha's AGENTS.md is a real copy that diverged from CLAUDE.md (see _env.py)
        try:
            self._write(env.alpha, '[desired.docs]\nagents_md = "linked"\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("linked", f["detail"])
            self.assertIn("diverged", f["detail"])
        finally:
            env.cleanup()

    def test_docs_invalid_configured_value_is_a_gap(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.docs]\nagents_md = "not-a-real-status"\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("not-a-real-status", f["detail"])
        finally:
            env.cleanup()

    def test_unknown_desired_key_is_a_gap(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.typo]\nrequired = ["x"]\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("typo", f["detail"])
        finally:
            env.cleanup()

    def test_malformed_toml_does_not_crash_and_is_reported(self):
        env = Env()
        try:
            self._write(env.alpha, "this is not [ valid toml at all\n===")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)   # must not raise
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertEqual(f["sev"], "warn")
        finally:
            env.cleanup()

    # -- type confusion: valid TOML, wrong types must never crash check.run --------------------

    def test_top_level_desired_scalar_does_not_crash(self):
        env = Env()
        try:
            self._write(env.alpha, "desired = 1\n")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)   # must not raise
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertEqual(f["sev"], "warn")
        finally:
            env.cleanup()

    def test_memory_max_age_days_string_is_bad_value_not_crash(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.memory]\nmax_age_days = "14"\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)   # must not raise
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("memory.max_age_days", f["detail"])
        finally:
            env.cleanup()

    def test_memory_max_age_days_bool_is_bad_value(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired.memory]\nmax_age_days = true\n")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("memory.max_age_days", f["detail"])
        finally:
            env.cleanup()

    def test_memory_max_age_days_negative_is_bad_value(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired.memory]\nmax_age_days = -5\n")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("memory.max_age_days", f["detail"])
        finally:
            env.cleanup()

    def test_memory_max_age_fractional_days_are_not_truncated_before_comparing(self):
        env = Env()
        try:
            mem = os.path.join(env.alpha, ".claude", "MEMORY.md")
            old = time.time() - 14.9 * 86400   # int-truncates to 14 -- must still trip max=14
            os.utime(mem, (old, old))
            self._write(env.alpha, "[desired.memory]\nmax_age_days = 14\n")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
        finally:
            env.cleanup()

    def test_docs_agents_md_list_is_bad_value_not_unhashable_crash(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.docs]\nagents_md = ["linked"]\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)   # must not raise (unhashable list in set)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("docs.agents_md", f["detail"])
        finally:
            env.cleanup()

    def test_agents_required_int_is_bad_value_not_crash(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired.agents]\nrequired = 7\n")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)   # must not raise (not iterable)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("agents.required", f["detail"])
        finally:
            env.cleanup()

    def test_agents_required_string_is_bad_value_not_iterated_as_chars(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.agents]\nrequired = "reviewer"\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("agents.required", f["detail"])
            self.assertNotIn("missing agent: `r`", f["detail"])
        finally:
            env.cleanup()

    def test_agents_required_list_with_non_str_elements_is_bad_value(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired.agents]\nrequired = [1, 2]\n")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("agents.required", f["detail"])
        finally:
            env.cleanup()

    def test_agents_subtable_wrong_type_is_bad_value(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired]\nagents = 7\n")
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)   # must not raise (AttributeError today)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)
            self.assertIn("agents", f["detail"])
        finally:
            env.cleanup()

    def test_typo_inside_known_subtable_is_reported_not_silently_dropped(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.agents]\nrequiered = ["ghost-agent"]\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=True)
            f = self._desired_finding(findings)
            self.assertIsNotNone(f, findings)   # today: gaps() == [] -> silently "all good"
            self.assertIn("agents.requiered", f["detail"])
        finally:
            env.cleanup()

    def test_wrong_typed_desired_table_does_not_suppress_other_findings(self):
        """A crash in desired.gaps() for one project must not take down check.run() for
        everyone else -- other detectors (e.g. alpha's shadowing `reviewer` contract warning)
        must still be reported."""
        env = Env()
        try:
            self._write(env.alpha, '[desired.memory]\nmax_age_days = "14"\n')
            scan.save(env.cfg, scan.run(env.cfg))
            findings = check.run(env.cfg, quick=False)   # must not raise
            self.assertTrue(any(x.get("projects") == ["alpha"] and "desired" not in x["title"].lower() for x in findings), findings)
        finally:
            env.cleanup()


if __name__ == "__main__":
    unittest.main()
