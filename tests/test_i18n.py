"""Guards for src/cabina/i18n.py: no duplicate keys within a STRINGS dict literal,
and exact key parity between the "en" and "es" tables.

Also guards the SEPARATE embedded I18N table in static/index.html (the web UI has
its own string table and does not read from i18n.py, per CLAUDE.md) against the
same class of bug: a duplicate key silently shadows the first definition in a JS
object literal, so `T("checking")` at one call site can end up showing the text
meant for a different call site (see the `checking` / `checking references…`
collision this test was written to catch)."""
import ast
import os
import re
import unittest

import _helpers  # noqa: F401  (adds src/ to sys.path)

from cabina import i18n

_I18N_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "cabina", "i18n.py"
)

_INDEX_HTML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "cabina",
    "static",
    "index.html",
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


# ---------------------------------------------------------------------------
# static/index.html's embedded I18N table: a small tolerant JS-object-literal
# parser (brace-depth + string-skipping, no dependency on line numbers or exact
# formatting) so this stays robust if the table is reformatted or reordered.
# ---------------------------------------------------------------------------


def _skip_js_string(text, i):
    """text[i] == '"'; return the index just past the matching unescaped closing quote."""
    i += 1
    while text[i] != '"':
        if text[i] == "\\":
            i += 1
        i += 1
    return i + 1


def _find_matching_brace(text, i):
    """text[i] == '{'; return the index of the matching '}', skipping over string literals
    so braces/colons inside quoted values (e.g. "last run: {t}") are never miscounted."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i = _skip_js_string(text, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError("unbalanced braces while scanning index.html's I18N table")


_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _top_level_keys(body):
    """`body` is the text strictly between an object literal's outer '{' and '}'.
    Return the keys defined at body's own top level only — nested object values
    (e.g. `tabs:{...}`) are skipped whole so keys inside them are not counted."""
    keys = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c.isspace() or c == ",":
            i += 1
            continue
        if c == '"':
            i = _skip_js_string(body, i)
            continue
        if c == "{":
            i = _find_matching_brace(body, i) + 1
            continue
        m = _KEY_RE.match(body, i)
        if m:
            j = m.end()
            while j < n and body[j].isspace():
                j += 1
            if j < n and body[j] == ":":
                keys.append(m.group(0))
                i = j + 1
                continue
        i += 1
    return keys


def _ui_lang_dict_body(lang):
    """Return the source text inside `const I18N={ ... }`'s `<lang>:{ ... }` entry."""
    with open(_INDEX_HTML, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"const\s+I18N\s*=\s*\{", text)
    assert m, "could not find `const I18N={` in static/index.html"
    i18n_open = m.end() - 1
    i18n_close = _find_matching_brace(text, i18n_open)
    i18n_body = text[i18n_open + 1 : i18n_close]

    lm = re.search(r"\b" + re.escape(lang) + r"\s*:\s*\{", i18n_body)
    assert lm, f"could not find {lang!r} entry in index.html's I18N table"
    lang_open = lm.end() - 1
    lang_close = _find_matching_brace(i18n_body, lang_open)
    return i18n_body[lang_open + 1 : lang_close]


class TestUiI18nTableNoDuplicateKeys(unittest.TestCase):
    def test_en_dict_has_no_duplicate_keys(self):
        keys = _top_level_keys(_ui_lang_dict_body("en"))
        dupes = {k for k in keys if keys.count(k) > 1}
        self.assertEqual(dupes, set(), f"duplicate keys in index.html I18N.en: {sorted(dupes)}")

    def test_es_dict_has_no_duplicate_keys(self):
        keys = _top_level_keys(_ui_lang_dict_body("es"))
        dupes = {k for k in keys if keys.count(k) > 1}
        self.assertEqual(dupes, set(), f"duplicate keys in index.html I18N.es: {sorted(dupes)}")


class TestUiI18nTableKeyParity(unittest.TestCase):
    def test_en_and_es_have_exactly_the_same_keys(self):
        en_keys = set(_top_level_keys(_ui_lang_dict_body("en")))
        es_keys = set(_top_level_keys(_ui_lang_dict_body("es")))
        only_en = en_keys - es_keys
        only_es = es_keys - en_keys
        self.assertEqual(only_en, set(), f"keys only in index.html I18N.en: {sorted(only_en)}")
        self.assertEqual(only_es, set(), f"keys only in index.html I18N.es: {sorted(only_es)}")


if __name__ == "__main__":
    unittest.main()
