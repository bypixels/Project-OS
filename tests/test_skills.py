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
if __name__ == "__main__": unittest.main()
