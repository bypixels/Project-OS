import os, tempfile, unittest
import _helpers  # noqa
from cabina.docs import Docs

class TestDocs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = self.tmp.name; self.bk = tempfile.TemporaryDirectory()
        for rel, txt in [("CLAUDE.md", "# C\n"), ("PROGRESS.md", "# P\n"), (".claude/MEMORY.md", "# M\n"), (".claude/HARNESS.md", "# H\n"),
                         ("docs/adr/0001-x.md", "# ADR\n"), ("apps/web/CLAUDE.md", "# sub\n"), ("apps/web/index.ts", "code"), (".claude/settings.json", "{}")]:
            os.makedirs(os.path.dirname(os.path.join(self.root, rel)), exist_ok=True); open(os.path.join(self.root, rel), "w").write(txt)
        self.D = Docs({"p": self.root}, self.bk.name, retention_days=30)
    def tearDown(self): self.tmp.cleanup(); self.bk.cleanup()
    def test_list(self):
        self.assertEqual(sorted(x["rel"] for x in self.D.list_project("p", self.root)), [".claude/HARNESS.md", ".claude/MEMORY.md", "CLAUDE.md", "PROGRESS.md", "apps/web/CLAUDE.md", "docs/adr/0001-x.md"])
    def test_read(self):
        r = self.D.read("p", "CLAUDE.md"); self.assertTrue(r["ok"]); self.assertEqual(r["content"], "# C\n"); self.assertEqual(len(r["hash"]), 16)
    def test_allowlist(self):
        self.assertFalse(self.D.read("p", "../x.md")["ok"]); self.assertIn("outside", self.D.read("p", "../x.md")["message"])
        self.assertFalse(self.D.read("p", "/etc/hosts.md")["ok"]); self.assertFalse(self.D.read("p", "apps/web/index.ts")["ok"])
        self.assertFalse(self.D.read("p", ".claude/settings.json")["ok"]); self.assertFalse(self.D.read("nope", "CLAUDE.md")["ok"])
    def test_save_ok_and_backup(self):
        r = self.D.read("p", ".claude/MEMORY.md"); g = self.D.save("p", ".claude/MEMORY.md", "# M2\n", r["hash"])
        self.assertTrue(g["ok"]); self.assertEqual(open(os.path.join(self.root, ".claude/MEMORY.md")).read(), "# M2\n")
        bks = [os.path.join(dp, f) for dp, dn, fn in os.walk(self.bk.name) for f in fn]; self.assertEqual(len(bks), 1); self.assertEqual(open(bks[0]).read(), "# M\n")
    def test_save_conflict(self):
        r = self.D.read("p", "CLAUDE.md"); open(os.path.join(self.root, "CLAUDE.md"), "w").write("# other\n")
        g = self.D.save("p", "CLAUDE.md", "# mine\n", r["hash"]); self.assertFalse(g["ok"]); self.assertTrue(g.get("conflict"))
        self.assertEqual(open(os.path.join(self.root, "CLAUDE.md")).read(), "# other\n")
    def test_save_never_creates(self):
        self.assertFalse(self.D.save("p", "NEW.md", "x", "0" * 16)["ok"]); self.assertFalse(os.path.exists(os.path.join(self.root, "NEW.md")))
    def test_save_blocked_when_working(self):
        r = self.D.read("p", "CLAUDE.md")
        self.assertFalse(self.D.save("p", "CLAUDE.md", "# x\n", r["hash"], working=["p"])["ok"])
        self.assertTrue(self.D.save("p", "CLAUDE.md", "# x\n", r["hash"], working=["other"])["ok"])
    def test_atomic_no_tmp(self):
        r = self.D.read("p", "CLAUDE.md"); self.D.save("p", "CLAUDE.md", "# z\n", r["hash"])
        self.assertEqual([f for f in os.listdir(self.root) if f.endswith(".tmp")], [])
if __name__ == "__main__": unittest.main()
