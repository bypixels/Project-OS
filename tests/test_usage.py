import os, tempfile, unittest
import _helpers  # noqa
from cabina import usage as U

def hist(d, *lines):
    open(os.path.join(d, "s.jsonl"), "w").write("\n".join(lines) + "\n"); return d

class TestUsage(unittest.TestCase):
    def test_extract_count_and_last(self):
        with tempfile.TemporaryDirectory() as d:
            hist(d, '{"timestamp":"2026-08-01T10:00:00Z","x":{"subagent_type":"code-reviewer"}}',
                    '{"timestamp":"2026-08-05T10:00:00Z","x":{"subagent_type":"code-reviewer"}}',
                    '{"timestamp":"2026-08-03T10:00:00Z","x":{"subagent_type":"executor"}}')
            u = U.extract_agents(d)
            self.assertEqual((u["code-reviewer"]["n"], u["code-reviewer"]["last"], u["executor"]["n"]), (2, "2026-08-05", 1))

    def test_attribution_by_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            hist(d, '{"timestamp":"2026-08-01T10:00:00Z","cwd":"/home/u/p/alpha/apps/api","x":{"subagent_type":"code-reviewer"}}',
                    '{"timestamp":"2026-08-02T10:00:00Z","cwd":"/home/u/p/beta","x":{"subagent_type":"code-reviewer"}}',
                    '{"timestamp":"2026-08-02T10:00:00Z","cwd":"/home/u/p/alpha-two","x":{"subagent_type":"code-reviewer"}}')
            u = U.extract_agents(d, roots={"alpha": "/home/u/p/alpha", "beta": "/home/u/p/beta"})
            self.assertEqual(u["code-reviewer"]["by_project"], {"alpha": 1, "beta": 1})   # alpha-two is NOT alpha

    def test_skill_invocations_not_mentions(self):
        with tempfile.TemporaryDirectory() as d:
            hist(d, '{"timestamp":"2026-08-01T10:00:00Z","x":{"name":"Skill","input":{"skill":"orchestrate"}}}',
                    '{"timestamp":"2026-08-02T10:00:00Z","x":"skill `mention-only`"}')
            u = U.extract_skills(d)
            self.assertEqual(u["orchestrate"]["n"], 1); self.assertNotIn("mention-only", u)

    def test_line_without_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            hist(d, '{"x":{"subagent_type":"odd"}}')
            self.assertEqual(U.extract_agents(d)["odd"], {"n": 1, "last": None, "by_project": {}})

    def test_merge_keeps_old_date_after_rotation(self):
        r = U.merge({"deploy": {"last": "2026-05-03", "n_total": 4}}, {})
        self.assertEqual((r["deploy"]["last"], r["deploy"]["n_total"]), ("2026-05-03", 4))

    def test_merge_advances_never_regresses(self):
        self.assertEqual(U.merge({"a": {"last": "2026-05-03", "n_total": 4}}, {"a": {"last": "2026-08-10", "n": 2}})["a"]["last"], "2026-08-10")
        self.assertEqual(U.merge({"a": {"last": "2026-08-10", "n_total": 9}}, {"a": {"last": "2026-08-01", "n": 1}})["a"]["last"], "2026-08-10")

    def test_merge_keeps_extra_fields_and_by_project(self):
        r = U.merge({"old": {"last": "2026-04-01", "n_total": 2, "archived": "2026-08-17", "by_project": {"p": 2}}}, {"old": {"n": 1, "last": None, "by_project": {"q": 1}}})
        self.assertEqual(r["old"]["archived"], "2026-08-17"); self.assertEqual(r["old"]["by_project"], {"p": 2, "q": 1})

    def test_save_load_roundtrip_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "u.json"); U.save(p, {"a": {"last": "2026-08-01", "n_total": 1}})
            self.assertEqual(U.load(p)["a"]["last"], "2026-08-01")
        self.assertEqual(U.load("/no/x.json"), {})

    @unittest.skipIf(os.name == "nt", "symlinks need admin rights on Windows")
    def test_project_of_resolves_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "real"); os.makedirs(real)
            link = os.path.join(d, "link"); os.symlink(real, link)
            self.assertEqual(U._project_of(os.path.join(link, "sub"), {"p": real}), "p")

    def test_for_agent_view(self):
        items = {"cr": {"n_total": 10, "last": "2026-08-01", "by_project": {"alpha": 7, "beta": 3}}}
        self.assertEqual(U.for_agent(items, "cr", "alpha"), {"total": 10, "last": "2026-08-01", "here": 7, "attributed": True})
        self.assertEqual(U.for_agent(items, "nope", "alpha")["total"], 0)

if __name__ == "__main__":
    unittest.main()
