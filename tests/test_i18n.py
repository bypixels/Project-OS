"""Guards for src/cabina/i18n.py: no duplicate keys within a STRINGS dict literal,
and exact key parity between the "en" and "es" tables."""
import ast
import os
import unittest

import _helpers  # noqa: F401  (adds src/ to sys.path)

from cabina import i18n

_I18N_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "cabina", "i18n.py"
)


def _dict_literal_for_lang(lang):
    """Parse i18n.py's source and return the ast.Dict node for STRINGS[lang]."""
    with open(_I18N_SRC, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=_I18N_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "STRINGS" for t in node.targets
        ):
            strings_dict = node.value
            assert isinstance(strings_dict, ast.Dict)
            for key_node, val_node in zip(strings_dict.keys, strings_dict.values):
                if isinstance(key_node, ast.Constant) and key_node.value == lang:
                    assert isinstance(val_node, ast.Dict)
                    return val_node
    raise AssertionError(f"could not find STRINGS[{lang!r}] literal in {_I18N_SRC}")


def _literal_keys(dict_node):
    return [k.value for k in dict_node.keys if isinstance(k, ast.Constant)]


class TestI18nNoDuplicateKeys(unittest.TestCase):
    def test_en_dict_literal_has_no_duplicate_keys(self):
        keys = _literal_keys(_dict_literal_for_lang("en"))
        dupes = {k for k in keys if keys.count(k) > 1}
        self.assertEqual(dupes, set(), f"duplicate keys in STRINGS['en']: {sorted(dupes)}")

    def test_es_dict_literal_has_no_duplicate_keys(self):
        keys = _literal_keys(_dict_literal_for_lang("es"))
        dupes = {k for k in keys if keys.count(k) > 1}
        self.assertEqual(dupes, set(), f"duplicate keys in STRINGS['es']: {sorted(dupes)}")


class TestI18nKeyParity(unittest.TestCase):
    def test_en_and_es_have_exactly_the_same_keys(self):
        en_keys = set(i18n.STRINGS["en"].keys())
        es_keys = set(i18n.STRINGS["es"].keys())
        only_en = en_keys - es_keys
        only_es = es_keys - en_keys
        self.assertEqual(only_en, set(), f"keys only in 'en': {sorted(only_en)}")
        self.assertEqual(only_es, set(), f"keys only in 'es': {sorted(only_es)}")


if __name__ == "__main__":
    unittest.main()
