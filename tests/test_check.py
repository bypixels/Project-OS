import unittest
import _helpers  # noqa
from _env import Env
from cabina import scan, check


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


if __name__ == "__main__":
    unittest.main()
