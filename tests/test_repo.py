import os, json, subprocess, tempfile, unittest
import _helpers  # noqa
from cabina import repo as RP, snapshot as SN, gitops as GO

AGENT = "---\nname: {n}\ndescription: Reviews things carefully\nmodel: {m}\ntools: Read\n---\nBody.\n"

def mkrepo(d, agents, cabina_toml=None, agents_md=None):
    c = os.path.join(d, ".claude", "agents"); os.makedirs(c)
    for n, m in agents: open(os.path.join(c, f"{n}.md"), "w").write(AGENT.format(n=n, m=m))
    open(os.path.join(d, "CLAUDE.md"), "w").write("# rules\n")
    if agents_md is not None: open(os.path.join(d, "AGENTS.md"), "w").write(agents_md)
    if cabina_toml is not None: open(os.path.join(d, ".cabina.toml"), "w").write(cabina_toml)
    return d

class TestRepoCheck(unittest.TestCase):
    def test_repo_check_uses_repo_contract(self):
        with tempfile.TemporaryDirectory() as d:
            mkrepo(d, [("a", "sonnet"), ("b", "fable")], cabina_toml='[contract]\nmodels = ["sonnet", "opus", "haiku", "fable"]\n')
            r = RP.check_repo(d)
            self.assertEqual(r["invalid"], []); self.assertEqual(r["warnings"], [])
            self.assertEqual(r["exit"], 0)
    def test_repo_check_without_toml_uses_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            mkrepo(d, [("a", "sonnet"), ("b", "fable")])
            r = RP.check_repo(d)
            self.assertEqual([x["name"] for x in r["warnings"]], ["b"])     # fable not in default models -> warning
            self.assertEqual(r["exit"], 0)
    def test_repo_check_invalid_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            mkrepo(d, [("a", "sonnet")]); open(os.path.join(d, ".claude", "agents", "bad.md"), "w").write("---\nname: Bad\nmodel: sonnet\ntools: x\n---\n")
            r = RP.check_repo(d); self.assertEqual([x["name"] for x in r["invalid"]], ["bad"]); self.assertEqual(r["exit"], 1)
    def test_repo_check_strict_fails_on_warnings(self):
        with tempfile.TemporaryDirectory() as d:
            mkrepo(d, [("b", "fable")], cabina_toml='[check]\nstrict = true\n')
            self.assertEqual(RP.check_repo(d)["exit"], 1)
    def test_repo_check_reports_agents_md_state(self):
        with tempfile.TemporaryDirectory() as d:
            mkrepo(d, [("a", "sonnet")], agents_md="# other\ndifferent\n")
            self.assertEqual(RP.check_repo(d)["agents_md"], "diverged")
    def test_repo_check_no_claude_dir(self):
        with tempfile.TemporaryDirectory() as d:
            r = RP.check_repo(d); self.assertEqual(r["exit"], 0); self.assertEqual(r["agents_total"], 0)

class TestSnapshot(unittest.TestCase):
    def test_export_compare(self):
        a = {"machine": "mac", "agents": [{"name": "x", "project": "global", "category": "valid", "tool": "claude"}, {"name": "y", "project": "p", "category": "valid", "tool": "claude"}],
             "skills": [{"name": "s1", "project": "global"}], "projects": ["p"]}
        b = {"machine": "win", "agents": [{"name": "x", "project": "global", "category": "invalid", "tool": "claude"}, {"name": "z", "project": "global", "category": "valid", "tool": "claude"}],
             "skills": [{"name": "s1", "project": "global"}, {"name": "s2", "project": "global"}], "projects": ["p", "q"]}
        r = SN.compare(a, b)
        self.assertEqual(r["agents"]["only_a"], ["claude:p/y"]); self.assertEqual(r["agents"]["only_b"], ["claude:global/z"])
        self.assertEqual(r["agents"]["state_differs"], [{"agent": "claude:global/x", "a": "valid", "b": "invalid"}])
        self.assertEqual(r["skills"]["only_b"], ["claude:global/s2"]); self.assertEqual(r["projects"]["only_b"], ["q"])
    def test_compare_keeps_claude_and_codex_twins_apart(self):
        a = {"machine": "m", "agents": [{"name": "x", "project": "global", "tool": "claude", "category": "valid"}, {"name": "x", "project": "global", "tool": "codex", "category": "valid"}], "skills": [], "projects": []}
        b = {"machine": "n", "agents": [{"name": "x", "project": "global", "tool": "claude", "category": "invalid"}, {"name": "x", "project": "global", "tool": "codex", "category": "valid"}], "skills": [], "projects": []}
        r = SN.compare(a, b); self.assertEqual(r["agents"]["state_differs"], [{"agent": "claude:global/x", "a": "valid", "b": "invalid"}])
    def test_render_compare_mentions_machines(self):
        txt = SN.render_compare(SN.compare({"machine": "mac", "agents": [], "skills": [], "projects": []}, {"machine": "win", "agents": [], "skills": [], "projects": []}), "mac", "win")
        self.assertIn("mac", txt); self.assertIn("win", txt)

class TestGitOps(unittest.TestCase):
    def _repo(self, d):
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        return d
    def test_commit_only_that_path(self):
        with tempfile.TemporaryDirectory() as d:
            self._repo(d)
            open(os.path.join(d, "a.md"), "w").write("a"); open(os.path.join(d, "other.md"), "w").write("o")
            ok, msg = GO.commit_path(os.path.join(d, "a.md"), "cabina: test", author=("t", "t@t"))
            self.assertTrue(ok, msg)
            files = subprocess.run(["git", "-C", d, "show", "--name-only", "--format=", "HEAD"], capture_output=True, text=True).stdout.split()
            self.assertEqual(files, ["a.md"])                                  # other.md NOT committed
            self.assertIn("other.md", subprocess.run(["git", "-C", d, "status", "--porcelain"], capture_output=True, text=True).stdout)
    def test_commit_records_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            self._repo(d); p = os.path.join(d, "gone.md"); open(p, "w").write("x")
            subprocess.run(["git", "-C", d, "add", "gone.md"], check=True); subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add"], check=True)
            os.remove(p)
            ok, msg = GO.commit_path(p, "cabina: archived", author=("t", "t@t")); self.assertTrue(ok, msg)
            self.assertNotIn("gone.md", subprocess.run(["git", "-C", d, "ls-files"], capture_output=True, text=True).stdout)
    def test_refuses_outside_repo_and_mid_merge(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.md"), "w").write("a")
            ok, msg = GO.commit_path(os.path.join(d, "a.md"), "m"); self.assertFalse(ok); self.assertIn("not in a git", msg)
        with tempfile.TemporaryDirectory() as d:
            self._repo(d); open(os.path.join(d, ".git", "MERGE_HEAD"), "w").write("x"); open(os.path.join(d, "a.md"), "w").write("a")
            ok, msg = GO.commit_path(os.path.join(d, "a.md"), "m"); self.assertFalse(ok); self.assertIn("merge", msg.lower())
    def test_no_change_no_commit(self):
        with tempfile.TemporaryDirectory() as d:
            self._repo(d); p = os.path.join(d, "a.md"); open(p, "w").write("a")
            subprocess.run(["git", "-C", d, "add", "a.md"], check=True); subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add"], check=True)
            ok, msg = GO.commit_path(p, "m"); self.assertFalse(ok); self.assertIn("nothing", msg)
if __name__ == "__main__": unittest.main()
