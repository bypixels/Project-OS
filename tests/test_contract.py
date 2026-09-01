import os, tempfile, unittest
import _helpers  # noqa
from project_os.contract import Contract, categorize

def fm(**kv):
    return "\n".join(["---"] + [f"{k}: {v}" for k, v in kv.items()] + ["---", "", "Body."])

VALID = dict(name="my-agent", description="Does something useful", model="sonnet", tools="Read, Grep")
C = Contract()

class TestContract(unittest.TestCase):
    def test_valid(self):
        r = C.validate_text(fm(**VALID), "my-agent")
        self.assertEqual((r.category, r.critical, r.warnings), ("valid", [], []))

    def test_missing_description_is_critical(self):
        d = dict(VALID); del d["description"]
        r = C.validate_text(fm(**d), "my-agent")
        self.assertEqual(r.category, "invalid"); self.assertTrue(any("description" in c for c in r.critical))

    def test_missing_model_is_warning(self):
        d = dict(VALID); del d["model"]
        r = C.validate_text(fm(**d), "my-agent")
        self.assertEqual((r.category, r.critical), ("warnings", []))

    def test_missing_tools_is_warning(self):
        d = dict(VALID); del d["tools"]
        self.assertEqual(C.validate_text(fm(**d), "my-agent").category, "warnings")

    def test_name_with_spaces_is_critical(self):
        r = C.validate_text(fm(**dict(VALID, name="AVISA Code Reviewer")), "code-reviewer")
        self.assertEqual(r.category, "invalid"); self.assertTrue(any("kebab" in c for c in r.critical))

    def test_name_differs_from_file_is_critical(self):
        r = C.validate_text(fm(**dict(VALID, name="other")), "my-agent")
        self.assertEqual(r.category, "invalid"); self.assertTrue(any("match" in c for c in r.critical))

    def test_kebab_with_digits_ok(self):
        self.assertEqual(C.validate_text(fm(**dict(VALID, name="agent-v2-beta")), "agent-v2-beta").category, "valid")

    def test_unknown_model_is_warning(self):
        r = C.validate_text(fm(**dict(VALID, model="gpt-4")), "my-agent")
        self.assertEqual(r.category, "warnings"); self.assertTrue(any("gpt-4" in w for w in r.warnings))

    def test_models_come_from_config(self):
        c = Contract({"contract": {"models": ["sonnet", "fable"]}})
        self.assertEqual(c.validate_text(fm(**dict(VALID, model="fable")), "my-agent").category, "valid")
        self.assertEqual(c.validate_text(fm(**dict(VALID, model="opus")), "my-agent").category, "warnings")

    def test_severity_comes_from_config(self):
        c = Contract({"contract": {"critical": ["name", "description", "model"], "warn": ["tools"]}})
        d = dict(VALID); del d["model"]
        self.assertEqual(c.validate_text(fm(**d), "my-agent").category, "invalid")

    def test_tools_star_valid_empty_not(self):
        self.assertEqual(C.validate_text(fm(**dict(VALID, tools='"*"')), "my-agent").category, "valid")
        self.assertEqual(C.validate_text(fm(**dict(VALID, tools="*")), "my-agent").category, "valid")
        self.assertEqual(C.validate_text(fm(**dict(VALID, tools="")), "my-agent").category, "warnings")

    def test_no_frontmatter_is_document(self):
        r = C.validate_text("# API Developer\n\nGuide.\n", "api-developer")
        self.assertEqual((r.category, r.critical, r.warnings), ("document", [], []))

    def test_unclosed_frontmatter_is_document(self):
        self.assertEqual(C.validate_text("---\nname: x\nno close", "x").category, "document")

    def test_empty_frontmatter_is_invalid_not_document(self):
        self.assertEqual(C.validate_text("---\n---\nbody", "x").category, "invalid")

    def test_shadow_undeclared_is_warning(self):
        r = C.validate_text(fm(**VALID), "my-agent", shadows_global=True)
        self.assertEqual(r.category, "warnings"); self.assertTrue(any("overrides" in w for w in r.warnings))

    def test_shadow_declared_is_valid(self):
        self.assertEqual(C.validate_text(fm(**dict(VALID, overrides="global")), "my-agent", shadows_global=True).category, "valid")

    def test_overrides_without_shadow_is_warning(self):
        r = C.validate_text(fm(**dict(VALID, overrides="global")), "my-agent", shadows_global=False)
        self.assertTrue(any("shadows no" in w for w in r.warnings))

    def test_invalid_that_shadows_gets_no_overrides_noise(self):
        r = C.validate_text(fm(**dict(VALID, name="Bad Name")), "bad-name", shadows_global=True)
        self.assertEqual(r.category, "invalid"); self.assertFalse(any("overrides" in w for w in r.warnings))

    def test_maxturns_is_known(self):
        self.assertEqual(C.validate_text(fm(**dict(VALID, maxTurns="10")), "my-agent").category, "valid")

    def test_made_up_field_is_foreign(self):
        r = C.validate_text(fm(**dict(VALID, colour="red")), "my-agent")
        self.assertEqual(r.category, "warnings"); self.assertTrue(any("colour" in w for w in r.warnings))

    def test_permissions_format_is_invalid_and_flagged(self):
        txt = "---\nname: AVISA Code Reviewer\ndescription: Reviews\npermissions:\n  allow:\n    - \"Read(**)\"\n---\nbody"
        r = C.validate_text(txt, "code-reviewer")
        self.assertEqual(r.category, "invalid"); self.assertTrue(any("permissions" in x for x in r.warnings + r.critical))

    def test_validate_file_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "my-agent.md"); open(p, "w").write(fm(**VALID))
            self.assertEqual(C.validate_file(p).category, "valid")
        self.assertEqual(C.validate_file("/no/x.md").category, "error")

    def test_categorize(self):
        self.assertEqual(categorize([], [], True), "document")
        self.assertEqual(categorize(["x"], [], False), "invalid")
        self.assertEqual(categorize([], ["x"], False), "warnings")
        self.assertEqual(categorize([], [], False), "valid")

if __name__ == "__main__":
    unittest.main()
