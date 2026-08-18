import os, json, tempfile, unittest
import _helpers  # noqa
from cabina.contract import Contract, parse_agent_file
from cabina import drift as DR, usage as U

TOML = 'name = "code-reviewer"\ndescription = "Reviews code"\ndeveloper_instructions = """\nYou review code.\n"""\n'
MD = "---\nname: code-reviewer\ndescription: Reviews code\nmodel: sonnet\ntools: Read\n---\nYou review code.\n"

class TestTomlAgents(unittest.TestCase):
    def test_parse_toml(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "code-reviewer.toml"); open(p, "w").write(TOML)
            f, body, has, fmt = parse_agent_file(p)
            self.assertEqual((f["name"], fmt, has), ("code-reviewer", "toml", True)); self.assertIn("You review", body)
    def test_codex_contract_defaults(self):
        c = Contract(tool="codex")
        r = c.validate_text(TOML, "code-reviewer", fmt="toml")
        self.assertEqual((r.category, r.critical, r.warnings), ("valid", [], []))
    def test_codex_name_mismatch_is_critical(self):
        r = Contract(tool="codex").validate_text(TOML, "reviewer", fmt="toml")
        self.assertEqual(r.category, "invalid")
    def test_codex_missing_description(self):
        r = Contract(tool="codex").validate_text('name = "x"\ndeveloper_instructions = "y"\n', "x", fmt="toml")
        self.assertEqual(r.category, "invalid")
    def test_bad_toml_is_error(self):
        r = Contract(tool="codex").validate_text('name = "x\n', "x", fmt="toml")
        self.assertEqual(r.category, "error")
    def test_validate_dir_mixed(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.toml"), "w").write(TOML.replace("code-reviewer", "a"))
            open(os.path.join(d, "b.md"), "w").write(MD.replace("code-reviewer", "b"))
            open(os.path.join(d, "notes.txt"), "w").write("x")
            r = Contract(tool="codex").validate_dir(d)
            self.assertEqual(sorted(x.name for x in r), ["a", "b"])

class TestDrift(unittest.TestCase):
    def test_twin_agents_identical_and_diverged(self):
        with tempfile.TemporaryDirectory() as d:
            ca = os.path.join(d, "claude", "agents"); co = os.path.join(d, "codex", "agents"); os.makedirs(ca); os.makedirs(co)
            open(os.path.join(ca, "code-reviewer.md"), "w").write(MD); open(os.path.join(co, "code-reviewer.toml"), "w").write(TOML)
            open(os.path.join(ca, "only-claude.md"), "w").write(MD.replace("code-reviewer", "only-claude"))
            open(os.path.join(ca, "planner.md"), "w").write(MD.replace("code-reviewer", "planner").replace("You review code.", "You plan.\nA lot of extra text about planning."))
            open(os.path.join(co, "planner.toml"), "w").write(TOML.replace("code-reviewer", "planner"))
            r = DR.twin_agents(ca, co)
            by = {x["name"]: x for x in r}
            self.assertEqual(by["code-reviewer"]["status"], "same")
            self.assertEqual(by["planner"]["status"], "diverged"); self.assertLess(by["planner"]["similarity"], 0.9)
            self.assertNotIn("only-claude", by)
    def test_rules_file_symlink_copy_diverged(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a"); os.makedirs(a); open(os.path.join(a, "CLAUDE.md"), "w").write("# CLAUDE.md\nrules\n")
            os.symlink("CLAUDE.md", os.path.join(a, "AGENTS.md"))
            b = os.path.join(d, "b"); os.makedirs(b); open(os.path.join(b, "CLAUDE.md"), "w").write("# CLAUDE.md\nThis file provides guidance to Claude Code.\nrules\n")
            open(os.path.join(b, "AGENTS.md"), "w").write("# AGENTS.md\nThis file provides guidance to Codex.\nrules\n")
            c = os.path.join(d, "c"); os.makedirs(c); open(os.path.join(c, "CLAUDE.md"), "w").write("# x\nrules v2\n"); open(os.path.join(c, "AGENTS.md"), "w").write("# x\nrules v1\n")
            e = os.path.join(d, "e"); os.makedirs(e); open(os.path.join(e, "CLAUDE.md"), "w").write("# x\n")
            g = os.path.join(d, "g"); os.makedirs(g); open(os.path.join(g, "CLAUDE.md"), "w").write("# full\n" + "rule\n" * 20)
            open(os.path.join(g, "AGENTS.md"), "w").write("# bridge\nThe canonical guide is `CLAUDE.md` — read it first.\n")
            self.assertEqual(DR.rules_file(a)["status"], "linked")
            self.assertEqual(DR.rules_file(b)["status"], "copy")        # only tool-name lines differ
            self.assertEqual(DR.rules_file(c)["status"], "diverged")
            self.assertEqual(DR.rules_file(e)["status"], "missing")
            self.assertEqual(DR.rules_file(g)["status"], "bridge")
    def test_skill_copies(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "agents_skills", "cf"); cp = os.path.join(d, "codex", "skills", "cf"); os.makedirs(src); os.makedirs(cp)
            open(os.path.join(src, "SKILL.md"), "w").write("v1"); open(os.path.join(cp, "SKILL.md"), "w").write("v1")
            r = DR.skill_copies(os.path.join(d, "codex", "skills"), [os.path.join(d, "agents_skills")])
            self.assertEqual(r[0]["status"], "same")
            open(os.path.join(cp, "SKILL.md"), "w").write("v2")
            self.assertEqual(DR.skill_copies(os.path.join(d, "codex", "skills"), [os.path.join(d, "agents_skills")])[0]["status"], "diverged")

class TestCodexUsage(unittest.TestCase):
    def test_codex_sessions_cwd_from_meta(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "2026", "08"); os.makedirs(p)
            open(os.path.join(p, "r.jsonl"), "w").write(
                '{"timestamp":"2026-08-01T00:00:00Z","type":"session_meta","payload":{"cwd":"/w/alpha"}}\n'
                '{"timestamp":"2026-08-01T00:01:00Z","type":"response_item","payload":{"type":"function_call","name":"exec_command"}}\n')
            s = U.codex_sessions(d, roots={"alpha": "/w/alpha"})
            self.assertEqual(s["alpha"]["sessions"], 1); self.assertEqual(s["alpha"]["last"], "2026-08-01")
if __name__ == "__main__": unittest.main()
