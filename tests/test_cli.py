import json, os, subprocess, sys, tempfile, unittest
import _helpers  # noqa
from _env import Env
from cabina import scan

class TestActivityCommand(unittest.TestCase):
    def test_activity_json_lists_sessions(self):
        env = Env(); scan.save(env.cfg, scan.run(env.cfg))
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(f"claude_home = '{env.claude}'\ncodex_home = '{env.codex}'\nroots = ['{env.projects}']\nstate_dir = '{env.state}'\n[live]\nprovider = \"none\"\n[scan]\nmeasure_worktrees = false\ncheck_mcp = false\n")
            cfgp = f.name
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        r = subprocess.run([sys.executable, "-m", "cabina", "--config", cfgp, "activity", "--json"],
                            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        items = json.loads(r.stdout)
        self.assertTrue(any(s["project"] == "alpha" for s in items))
        os.unlink(cfgp); env.cleanup()

if __name__ == "__main__":
    unittest.main()
