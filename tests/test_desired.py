"""Tests for src/project_os/desired.py's `[desired.verification]` subtable: CI/tests/gates
presence checks. Calls desired.gaps() directly (not check.run()) to isolate desired.py's own
logic from check.py's aggregation -- same rationale as test_check.py's MEMORY.md TOCTOU test."""
import os
import unittest
from unittest import mock
import _helpers  # noqa
from _env import Env
from project_os import scan, desired


class TestDesiredVerification(unittest.TestCase):
    def _write(self, root, text):
        open(os.path.join(root, ".project-os.toml"), "w").write(text)

    def _workflow(self, env, name, text):
        wf_dir = os.path.join(env.alpha, ".github", "workflows")
        os.makedirs(wf_dir, exist_ok=True)
        open(os.path.join(wf_dir, name), "w").write(text)

    def _scan_project(self, env):
        data = scan.run(env.cfg)
        scan.save(env.cfg, data)
        p = next(pr for pr in data["projects"] if pr["name"] == "alpha")
        return p, data

    def _gaps(self, env):
        p, data = self._scan_project(env)
        return desired.gaps(env.cfg, p, data)

    # --- silence ----------------------------------------------------------

    def test_no_verification_table_is_silent(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired]\n")
            self.assertEqual(self._gaps(env), [])
        finally:
            env.cleanup()

    def test_ci_false_is_silent_even_without_workflows(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired.verification]\nci = false\n")
            self.assertEqual(self._gaps(env), [])
        finally:
            env.cleanup()

    # --- ci -----------------------------------------------------------------

    def test_ci_true_with_no_workflows_dir_is_ci_absent(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired.verification]\nci = true\n")
            self.assertIn({"kind": "ci_absent"}, self._gaps(env))
        finally:
            env.cleanup()

    def test_ci_true_with_only_a_txt_file_is_ci_absent(self):
        env = Env()
        try:
            self._workflow(env, "notes.txt", "not a workflow")
            self._write(env.alpha, "[desired.verification]\nci = true\n")
            self.assertIn({"kind": "ci_absent"}, self._gaps(env))
        finally:
            env.cleanup()

    def test_ci_true_with_a_real_yml_is_silent(self):
        env = Env()
        try:
            self._workflow(env, "ci.yml", "name: CI\non: [push]\n")
            self._write(env.alpha, "[desired.verification]\nci = true\n")
            self.assertEqual(self._gaps(env), [])
        finally:
            env.cleanup()

    def test_ci_true_with_a_yaml_extension_workflow_is_silent(self):
        # _workflow_texts matches both *.yml AND *.yaml -- a mutant that dropped the second
        # extension would only be caught by a test that actually exercises a .yaml file.
        env = Env()
        try:
            self._workflow(env, "ci.yaml", "name: CI\non: [push]\n")
            self._write(env.alpha, "[desired.verification]\nci = true\n")
            self.assertEqual(self._gaps(env), [])
        finally:
            env.cleanup()

    def test_ci_int_is_bad_value_not_a_truthy_pass(self):
        # isinstance(True, int) is True but isinstance(1, bool) is False -- `ci = 1` must be
        # rejected as the wrong type, never silently treated as `ci = true`.
        env = Env()
        try:
            self._write(env.alpha, "[desired.verification]\nci = 1\n")
            gaps = self._gaps(env)
            self.assertIn({"kind": "bad_value", "field": "verification.ci"}, gaps)
            self.assertNotIn({"kind": "ci_absent"}, gaps)
        finally:
            env.cleanup()

    def test_ci_string_is_bad_value(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\nci = "yes"\n')
            self.assertIn({"kind": "bad_value", "field": "verification.ci"}, self._gaps(env))
        finally:
            env.cleanup()

    # --- tests ---------------------------------------------------------------

    def test_tests_path_existing_is_silent(self):
        env = Env()
        try:
            os.makedirs(os.path.join(env.alpha, "tests"), exist_ok=True)
            self._write(env.alpha, '[desired.verification]\ntests = "tests"\n')
            self.assertEqual(self._gaps(env), [])
        finally:
            env.cleanup()

    def test_tests_path_missing_reports_the_declared_path(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\ntests = "tests"\n')
            self.assertIn({"kind": "tests_absent", "path": "tests"}, self._gaps(env))
        finally:
            env.cleanup()

    def test_tests_absolute_path_is_bad_value_never_stated_outside_repo(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\ntests = "/etc"\n')
            gaps = self._gaps(env)
            self.assertIn({"kind": "bad_value", "field": "verification.tests"}, gaps)
            self.assertFalse(any(g["kind"] == "tests_absent" for g in gaps), gaps)
        finally:
            env.cleanup()

    def test_tests_path_escaping_repo_root_is_bad_value(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\ntests = "../../.."\n')
            gaps = self._gaps(env)
            self.assertIn({"kind": "bad_value", "field": "verification.tests"}, gaps)
            self.assertFalse(any(g["kind"] == "tests_absent" for g in gaps), gaps)
        finally:
            env.cleanup()

    def test_tests_wrong_type_is_bad_value(self):
        env = Env()
        try:
            self._write(env.alpha, "[desired.verification]\ntests = 5\n")
            self.assertIn({"kind": "bad_value", "field": "verification.tests"}, self._gaps(env))
        finally:
            env.cleanup()

    def test_tests_empty_string_is_bad_value(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\ntests = ""\n')
            self.assertIn({"kind": "bad_value", "field": "verification.tests"}, self._gaps(env))
        finally:
            env.cleanup()

    def test_tests_path_with_embedded_nul_is_bad_value_not_a_crash(self):
        # `tests` containing a TOML \u0000 escape is a perfectly valid scalar -- tomllib
        # decodes it to a string with an embedded NUL byte, and os.path.realpath() raises
        # ValueError on that, a different exception type than the OSError _confined_path
        # already guarded against. Must not raise, and must never be misreported as
        # tests_absent (that would claim the path was actually stat-able, which it never was).
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\ntests = "a\\u0000b"\n')
            gaps = self._gaps(env)   # must not raise
            self.assertIn({"kind": "bad_value", "field": "verification.tests"}, gaps)
            self.assertFalse(any(g["kind"] == "tests_absent" for g in gaps), gaps)
        finally:
            env.cleanup()

    # --- gates -----------------------------------------------------------------

    def test_gate_found_in_a_workflow_is_silent(self):
        env = Env()
        try:
            self._workflow(env, "ci.yml", "steps:\n  - run: python -m unittest discover -s tests\n")
            self._write(env.alpha, '[desired.verification]\ngates = ["python -m unittest discover -s tests"]\n')
            self.assertEqual(self._gaps(env), [])
        finally:
            env.cleanup()

    def test_gate_not_found_in_any_workflow_is_gate_absent(self):
        env = Env()
        try:
            self._workflow(env, "ci.yml", "steps:\n  - run: echo hi\n")
            self._write(env.alpha, '[desired.verification]\ngates = ["python -m unittest discover -s tests"]\n')
            gaps = self._gaps(env)
            self.assertIn({"kind": "gate_absent", "gate": "python -m unittest discover -s tests"}, gaps)
        finally:
            env.cleanup()

    def test_gates_bare_string_is_one_bad_value_not_one_gap_per_character(self):
        # A bare string is iterable in Python -- without a type check this would silently
        # iterate its characters and report each one as a missing gate.
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\ngates = "make test"\n')
            self.assertEqual(self._gaps(env), [{"kind": "bad_value", "field": "verification.gates"}])
        finally:
            env.cleanup()

    def test_gates_blank_entry_is_bad_value_not_silence(self):
        # "" is a substring of every string in Python -- without a blank check, a blank gate
        # would silently match any workflow (a false "found"), the same defect class `tests = ""`
        # is already guarded against for the sibling key.
        env = Env()
        try:
            self._workflow(env, "ci.yml", "steps:\n  - run: echo hi\n")
            self._write(env.alpha, '[desired.verification]\ngates = ["   "]\n')
            self.assertEqual(self._gaps(env), [{"kind": "bad_value", "field": "verification.gates"}])
        finally:
            env.cleanup()

    def test_gates_with_no_workflows_dir_are_all_gate_absent(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\ngates = ["make test", "make lint"]\n')
            gaps = self._gaps(env)
            self.assertIn({"kind": "gate_absent", "gate": "make test"}, gaps)
            self.assertIn({"kind": "gate_absent", "gate": "make lint"}, gaps)
        finally:
            env.cleanup()

    def test_unreadable_workflow_file_does_not_crash_gaps(self):
        env = Env()
        try:
            self._workflow(env, "broken.yml", "steps: [ok]\n")
            self._write(env.alpha, '[desired.verification]\ngates = ["ok"]\n')
            p, data = self._scan_project(env)
            broken_path = os.path.join(env.alpha, ".github", "workflows", "broken.yml")
            real_open = open

            def fake_open(path, *a, **kw):
                if path == broken_path:
                    raise OSError("permission denied")
                return real_open(path, *a, **kw)

            with mock.patch("builtins.open", side_effect=fake_open):
                gaps = desired.gaps(env.cfg, p, data)   # must not raise
            self.assertIn({"kind": "gate_absent", "gate": "ok"}, gaps)
        finally:
            env.cleanup()

    def test_binary_garbage_workflow_file_does_not_crash_gaps(self):
        env = Env()
        try:
            wf_dir = os.path.join(env.alpha, ".github", "workflows")
            os.makedirs(wf_dir, exist_ok=True)
            with open(os.path.join(wf_dir, "garbage.yml"), "wb") as f:
                f.write(b"\xff\xfe\x00\x01\x80\x81\x82binary garbage, not utf-8")
            self._write(env.alpha, '[desired.verification]\ngates = ["python -m unittest"]\n')
            gaps = self._gaps(env)   # must not raise
            self.assertIn({"kind": "gate_absent", "gate": "python -m unittest"}, gaps)
        finally:
            env.cleanup()

    # --- unknown key ------------------------------------------------------

    def test_typo_key_inside_verification_is_unknown_key(self):
        env = Env()
        try:
            self._write(env.alpha, '[desired.verification]\ngaates = ["x"]\n')
            gaps = self._gaps(env)
            f = next((g for g in gaps if g["kind"] == "unknown_key"), None)
            self.assertIsNotNone(f, gaps)
            self.assertIn("verification.gaates", f["keys"])
        finally:
            env.cleanup()


if __name__ == "__main__":
    unittest.main()
