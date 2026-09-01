import os, stat, tempfile, unittest
from unittest import mock
import _helpers  # noqa
import project_os.docs as D
from project_os.docs import Docs

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

    def test_atomic_save_does_not_follow_preplanted_tmp_symlink(self):
        victim = os.path.join(self.tmp.name, "victim.txt")
        open(victim, "w").write("external")
        link = os.path.join(self.root, "CLAUDE.md.tmp")
        os.symlink(victim, link)
        r = self.D.read("p", "CLAUDE.md")
        out = self.D.save("p", "CLAUDE.md", "# safe\n", r["hash"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(open(os.path.join(self.root, "CLAUDE.md")).read(), "# safe\n")
        self.assertEqual(open(victim).read(), "external")
        self.assertTrue(os.path.lexists(link))

    @unittest.skipUnless(hasattr(os, "chmod"), "chmod unavailable")
    def test_atomic_save_preserves_existing_mode(self):
        path = os.path.join(self.root, "CLAUDE.md")
        os.chmod(path, 0o644)
        r = self.D.read("p", "CLAUDE.md")
        out = self.D.save("p", "CLAUDE.md", "# mode-safe\n", r["hash"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)

    # -- backup versioning: mirrored subdirectories, versions(), version_text() --

    def test_backup_mirrors_subdir_no_collision(self):
        # regression test for the actual bug: two docs sharing a basename in different
        # subdirectories must keep separate histories, not overwrite each other's backup.
        os.makedirs(os.path.join(self.root, "dirA")); os.makedirs(os.path.join(self.root, "dirB"))
        open(os.path.join(self.root, "dirA/X.md"), "w").write("a1")
        open(os.path.join(self.root, "dirB/X.md"), "w").write("b1")
        ra = self.D.read("p", "dirA/X.md"); self.assertTrue(self.D.save("p", "dirA/X.md", "a2", ra["hash"])["ok"])
        rb = self.D.read("p", "dirB/X.md"); self.assertTrue(self.D.save("p", "dirB/X.md", "b2", rb["hash"])["ok"])
        bks = sorted(os.path.relpath(os.path.join(dp, f), self.bk.name) for dp, dn, fn in os.walk(self.bk.name) for f in fn)
        self.assertEqual(len(bks), 2)
        self.assertEqual(sorted(os.path.dirname(b) for b in bks), [os.path.join("p", "dirA"), os.path.join("p", "dirB")])
        va = self.D.versions("p", "dirA/X.md"); vb = self.D.versions("p", "dirB/X.md")
        self.assertEqual(len(va), 1); self.assertEqual(len(vb), 1)
        self.assertEqual(self.D.version_text("p", "dirA/X.md", va[0]["stamp"])["content"], "a1")
        self.assertEqual(self.D.version_text("p", "dirB/X.md", vb[0]["stamp"])["content"], "b1")

    def test_versions_newest_first(self):
        real = D.time.strftime
        seq = iter(["20260101-000000", "20260102-000000"])
        def fake(fmt, *a):
            return next(seq) if fmt == "%Y%m%d-%H%M%S" else (real(fmt, *a) if a else real(fmt))
        r = self.D.read("p", "CLAUDE.md")
        with mock.patch.object(D.time, "strftime", side_effect=fake):
            self.assertTrue(self.D.save("p", "CLAUDE.md", "v2\n", r["hash"])["ok"])
            r2 = self.D.read("p", "CLAUDE.md")
            self.assertTrue(self.D.save("p", "CLAUDE.md", "v3longer\n", r2["hash"])["ok"])
        vs = self.D.versions("p", "CLAUDE.md")
        self.assertEqual([v["stamp"] for v in vs], ["20260102-000000", "20260101-000000"])   # newest first
        self.assertEqual(vs[1]["size"], len("# C\n"))       # oldest backup = the original content
        self.assertEqual(vs[0]["size"], len("v2\n"))        # second backup = the content saved over first
        self.assertTrue(vs[0]["iso"].startswith("2026-01-02"))

    def test_ambiguous_flat_backups_root_only(self):
        # a pre-existing flat backup, as the old (pre-fix) code would have written for a
        # root-level doc, sits directly in <backups>/<project>/.
        bp = os.path.join(self.bk.name, "p"); os.makedirs(bp, exist_ok=True)
        open(os.path.join(bp, "CLAUDE.20250101-000000.md"), "w").write("old root")
        os.makedirs(os.path.join(self.root, "sub"), exist_ok=True)
        open(os.path.join(self.root, "sub/CLAUDE.md"), "w").write("sub doc")
        vs_root = self.D.versions("p", "CLAUDE.md")
        self.assertEqual(len(vs_root), 1)
        self.assertTrue(vs_root[0]["ambiguous"])
        self.assertEqual(vs_root[0]["stamp"], "20250101-000000")
        vs_sub = self.D.versions("p", "sub/CLAUDE.md")
        self.assertEqual(vs_sub, [])   # ambiguous flat leftovers never attributed to a subdirectory doc

    def test_version_text_and_bad_stamp(self):
        r = self.D.read("p", "CLAUDE.md")
        self.assertTrue(self.D.save("p", "CLAUDE.md", "v2\n", r["hash"])["ok"])
        vs = self.D.versions("p", "CLAUDE.md")
        got = self.D.version_text("p", "CLAUDE.md", vs[0]["stamp"])
        self.assertTrue(got["ok"]); self.assertEqual(got["content"], "# C\n")
        for bad in ("../../etc/passwd", "2026", "abc", "20260101-000000/../x"):
            self.assertFalse(self.D.version_text("p", "CLAUDE.md", bad)["ok"])
        with mock.patch.object(Docs, "_backup_loc") as m:
            self.D.version_text("p", "CLAUDE.md", "not-a-stamp")
            m.assert_not_called()   # bad stamp rejected before any path resolution

    def test_versions_empty(self):
        self.assertEqual(self.D.versions("p", "PROGRESS.md"), [])
        self.assertEqual(self.D.versions("nope", "CLAUDE.md"), [])

if __name__ == "__main__": unittest.main()
