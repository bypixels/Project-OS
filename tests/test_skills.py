import os, tempfile, unittest
import _helpers  # noqa

def _can_symlink():
    import os, tempfile
    try:
        with tempfile.TemporaryDirectory() as d:
            os.symlink(d, os.path.join(d, "l")); return True
    except (OSError, NotImplementedError):
        return False
from cabina import skills as SK

def mk(d, name, fm=True, link_to=None):
    p = os.path.join(d, name)
    if link_to: os.symlink(link_to, p); return p
    os.makedirs(p); open(os.path.join(p, "SKILL.md"), "w").write(f"---\nname: {name}\ndescription: x\n---\nbody\n" if fm else "# doc\n"); return p

class TestSkills(unittest.TestCase):
    def test_ok(self):
        with tempfile.TemporaryDirectory() as d:
            mk(d, "a"); mk(d, "b"); r = SK.scan_dir(d, "global")
            self.assertEqual(sorted(x["name"] for x in r), ["a", "b"]); self.assertTrue(all(x["state"] == "ok" for x in r))
    @unittest.skipUnless(_can_symlink(), "symlinks not available")
    def test_states(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(d, "empty")); mk(d, "raw", fm=False); mk(d, "broken", link_to="/no/x")
            real = mk(t, "origin"); mk(d, "link", link_to=real); open(os.path.join(d, "README.md"), "w").write("x")
            st = {x["name"]: x["state"] for x in SK.scan_dir(d, "g")}
            self.assertEqual(st, {"empty": "no-skill-md", "raw": "no-frontmatter", "broken": "broken-link", "link": "ok"})
    def test_archive_dir(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as a:
            p = mk(d, "go"); ok, _ = SK.archive_path(p, "global", a)
            self.assertTrue(ok); self.assertFalse(os.path.exists(p))
    @unittest.skipUnless(_can_symlink(), "symlinks not available")
    def test_archive_symlink_keeps_target(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as a:
            real = mk(t, "origin"); p = mk(d, "link", link_to=real)
            ok, _ = SK.archive_path(p, "global", a)
            self.assertTrue(ok); self.assertTrue(os.path.exists(real)); self.assertFalse(os.path.lexists(p))

    def test_archive_rejects_path_outside_allowed_skill_root(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other, tempfile.TemporaryDirectory() as a:
            p = mk(other, "outside")
            ok, msg = SK.archive_path(p, "global", a, allowed_root=d)
            self.assertFalse(ok)
            self.assertIn("outside", msg)


class TestSkillReadBody(unittest.TestCase):
    def test_read_body_returns_content_and_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            open(os.path.join(p, "notes.txt"), "w").write("hi")
            os.makedirs(os.path.join(p, "sub"))
            open(os.path.join(p, "sub", "b.txt"), "w").write("bb")
            r = SK.read_body(p)
            self.assertTrue(r["ok"], r)
            self.assertIn("name: s", r["content"])
            self.assertFalse(r["truncated"])
            paths = sorted(f["path"] for f in r["files"])
            self.assertEqual(paths, ["SKILL.md", "notes.txt", os.path.join("sub", "b.txt")])

    def test_read_body_missing_skill_md(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "empty"))
            r = SK.read_body(os.path.join(d, "empty"))
            self.assertFalse(r["ok"])

    def test_read_body_truncates_over_cap(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            open(os.path.join(p, "SKILL.md"), "w").write("x" * 20)
            r = SK.read_body(p, max_bytes=10)
            self.assertTrue(r["ok"], r)
            self.assertTrue(r["truncated"])
            self.assertEqual(r["bytes"], 10)

    def test_read_body_max_files_caps_listing(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            for i in range(5):
                open(os.path.join(p, f"f{i}.txt"), "w").write("x")
            r = SK.read_body(p, max_files=3)
            self.assertTrue(r["ok"], r)
            self.assertEqual(len(r["files"]), 3)

    def test_read_body_max_depth_excludes_deepest(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            deep = p
            for i in range(8):
                deep = os.path.join(deep, f"d{i}")
                os.makedirs(deep)
            open(os.path.join(deep, "buried.txt"), "w").write("x")
            r = SK.read_body(p, max_depth=1)
            self.assertTrue(r["ok"], r)
            self.assertFalse(any(f["path"].endswith("buried.txt") for f in r["files"]))


class TestSkillReadFile(unittest.TestCase):
    def test_read_file_ok(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            open(os.path.join(p, "notes.txt"), "w").write("hello")
            r = SK.read_file(p, "notes.txt")
            self.assertTrue(r["ok"], r)
            self.assertFalse(r["binary"])
            self.assertEqual(r["content"], "hello")

    def test_read_file_rejects_dotdot(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            open(os.path.join(d, "outside.txt"), "w").write("secret")
            r = SK.read_file(p, "../outside.txt")
            self.assertFalse(r["ok"])

    def test_read_file_rejects_null_byte(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            r = SK.read_file(p, "\x00")
            self.assertFalse(r["ok"])

    def test_read_file_rejects_absolute(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            abs_target = os.path.join(d, "abs.txt")
            open(abs_target, "w").write("secret")
            r = SK.read_file(p, abs_target)
            self.assertFalse(r["ok"])

    @unittest.skipUnless(_can_symlink(), "symlinks not available")
    def test_read_file_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            p = mk(d, "s")
            secret = os.path.join(other, "secret.txt"); open(secret, "w").write("nope")
            os.symlink(secret, os.path.join(p, "link.txt"))
            r = SK.read_file(p, "link.txt")
            self.assertFalse(r["ok"])

    def test_read_file_binary_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            open(os.path.join(p, "bin.dat"), "wb").write(b"\x00\x01binarydata")
            r = SK.read_file(p, "bin.dat")
            self.assertTrue(r["ok"], r)
            self.assertTrue(r["binary"])
            self.assertIsNone(r["content"])

    def test_read_file_rejects_over_cap(self):
        with tempfile.TemporaryDirectory() as d:
            p = mk(d, "s")
            open(os.path.join(p, "big.txt"), "wb").write(b"x" * (1024 * 1024 + 1))
            r = SK.read_file(p, "big.txt")
            self.assertFalse(r["ok"])

if __name__ == "__main__": unittest.main()
