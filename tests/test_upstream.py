import ssl
import types
import unittest
import urllib.error
import urllib.request
from unittest import mock
import _helpers  # noqa
from project_os import upstream


def _cert_error():
    return urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))


SAMPLE_DOC = """# Sub-agents

Some prose before the tables. The doc's FIRST table (as of this writing) is not the field
reference at all -- it's where subagent files can live:

| Location          | Scope              | Priority    |
|--------------------|--------------------|-------------|
| Managed settings   | Organization-wide  | 1 (highest) |
| Current project    | Current project    | 3           |

Some prose between the location table and the field table.

| Field | Required | Description |
| :---- | :------- | :----------- |
| `name` | Yes | Unique identifier |
| `description` | Yes | When to invoke this agent |
| `model` | No | Model alias |
| `effort` | No | Reasoning effort |

Some prose between the field table and a later values table.

| Mode | Behavior |
|------|----------|
| `default` | Inherit the session's model |
| `acceptEdits` | Auto-accept edits |
| `user` | User-scoped |
| `project` | Project-scoped |

More prose after.
"""


class TestParseFields(unittest.TestCase):
    """`upstream.parse_fields` must anchor to the table whose header's FIRST cell is exactly
    "Field" -- NOT "the first table in the doc". The doc's real first table (Location/Scope/
    Priority) documents where a subagent file can live, not its frontmatter fields; a later
    table (Mode/Behavior) lists VALUES a field can take (`default`, `acceptEdits`, `user`,
    `project`...), not field names. Only the "Field" table's own backtick-quoted first column
    is the frontmatter reference."""

    def test_parses_the_field_table_not_the_first_table(self):
        fields = upstream.parse_fields(SAMPLE_DOC)
        self.assertEqual(fields, ["name", "description", "model", "effort"])
        for leak in ("default", "acceptEdits", "user", "project", "Location", "Priority"):
            self.assertNotIn(leak, fields)

    def test_no_field_table_returns_empty_list(self):
        self.assertEqual(upstream.parse_fields("# Just prose, no table here.\n"), [])
        no_field_header = "| Location | Scope |\n|---|---|\n| Managed | Org |\n"
        self.assertEqual(upstream.parse_fields(no_field_header), [])

    def test_backtick_in_a_later_cell_is_not_mistaken_for_the_field_name(self):
        """`re.search` over the whole row would grab the FIRST backtick anywhere on the line --
        the real doc's own `name` row already has a backtick (`agent_type`) inside its
        Description cell. A row whose first cell carries no backtick, but whose description
        does, must be skipped entirely, not read as a field named after the description's
        backtick token."""
        doc = ("| Field | Description |\n"
               "| :---- | :----------- |\n"
               "| `name` | Unique identifier |\n"
               "| plain | Uses `agent_type` internally |\n"
               "| `model` | Model alias |\n")
        fields = upstream.parse_fields(doc)
        self.assertEqual(fields, ["name", "model"])
        self.assertNotIn("agent_type", fields)


class TestCompareOwnConventions(unittest.TestCase):
    """`overrides` and `version` are project-os's own frontmatter conventions -- they are known
    to the inspector but never appear in Claude Code's own doc. That is exactly what the
    informational "extra" bucket is for (the check.py message already frames it as "could be a
    project-os convention, an outdated doc, or a retired field" -- not an alarm), so they must
    show up in `extra`, not be silently dropped from it."""

    def test_project_os_conventions_are_reported_as_informational_extra(self):
        from project_os import config as CFG
        doc = "| Field | Required |\n| :--- | :--- |\n| `name` | Yes |\n| `description` | Yes |\n| `model` | No |\n| `tools` | No |\n"
        cfg = CFG.load("/nonexistent")
        with mock.patch("project_os.upstream.fetch_doc", return_value=(doc, None)):
            result = upstream.compare(cfg)
        self.assertFalse(result["unavailable"])
        self.assertEqual(result["missing"], [])
        self.assertIn("overrides", result["extra"])
        self.assertIn("version", result["extra"])


class TestCompareNeverRaises(unittest.TestCase):
    """The module docstring promises a failed analysis is reported neutrally, never a critical
    finding and never a crash -- but `compare()` only guarded the fetch, not `parse_fields` or
    `Contract` themselves. A parser/contract exception (a doc shape project-os doesn't expect,
    a broken config...) must still come back as {"unavailable": True, ...}, never propagate."""

    def test_parse_fields_exception_is_reported_neutrally_not_raised(self):
        from project_os import config as CFG
        cfg = CFG.load("/nonexistent")
        with mock.patch("project_os.upstream.fetch_doc", return_value=("some text", None)), \
             mock.patch("project_os.upstream.parse_fields", side_effect=ValueError("boom")):
            result = upstream.compare(cfg)
        self.assertTrue(result["unavailable"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["extra"], [])


class TestFetchDocRetryClassification(unittest.TestCase):
    """The certifi retry's OWN outcome must be classified on its own merits, not blanket-labeled
    "ssl" just because the FIRST attempt was a cert failure. Three cases: certifi isn't
    installed at all (the original cert diagnosis still stands -- "ssl"); the retry itself hits
    a real cert error, e.g. a corporate proxy CA outside certifi's bundle ("ssl"); the retry
    fails for an UNRELATED reason -- timeout, DNS ("network", NOT "ssl", or a real network
    outage during the retry would misreport as a certificate problem)."""

    def _cert_error(self):
        return urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))

    def test_certifi_not_installed_keeps_the_ssl_diagnosis(self):
        with mock.patch("project_os.upstream.urllib.request.urlopen", side_effect=self._cert_error()), \
             mock.patch.dict("sys.modules", {"certifi": None}):
            text, error = upstream.fetch_doc()
        self.assertIsNone(text)
        self.assertEqual(error, "ssl")

    def test_retry_generic_failure_is_network_not_ssl(self):
        fake_certifi = types.ModuleType("certifi")
        fake_certifi.where = lambda: "/fake/cafile"
        with mock.patch("project_os.upstream.urllib.request.urlopen",
                         side_effect=[self._cert_error(), urllib.error.URLError("timed out")]), \
             mock.patch.dict("sys.modules", {"certifi": fake_certifi}), \
             mock.patch("project_os.upstream.ssl.create_default_context", return_value=mock.MagicMock()):
            text, error = upstream.fetch_doc()
        self.assertIsNone(text)
        self.assertEqual(error, "network")

    def test_retry_cert_failure_is_still_ssl(self):
        fake_certifi = types.ModuleType("certifi")
        fake_certifi.where = lambda: "/fake/cafile"
        with mock.patch("project_os.upstream.urllib.request.urlopen",
                         side_effect=[self._cert_error(), self._cert_error()]), \
             mock.patch.dict("sys.modules", {"certifi": fake_certifi}), \
             mock.patch("project_os.upstream.ssl.create_default_context", return_value=mock.MagicMock()):
            text, error = upstream.fetch_doc()
        self.assertIsNone(text)
        self.assertEqual(error, "ssl")


class TestFetchDocSendsUserAgent(unittest.TestCase):
    """The doc's CDN returns HTTP 403 for Python's default User-Agent ("Python-urllib/x.y") even
    though curl (a different UA) gets a real 200 for the same URL -- verified empirically.
    fetch_doc must send an identifiable, non-default User-Agent on BOTH the first attempt and
    the certifi retry, or every fetch on a stock Python looks like a network failure that is
    actually a UA-based block."""

    def test_first_attempt_sends_a_non_default_user_agent(self):
        captured = {}
        def fake_urlopen(req, timeout=None, **kw):
            captured["req"] = req
            raise OSError("stop after capturing the request")
        with mock.patch("project_os.upstream.urllib.request.urlopen", side_effect=fake_urlopen):
            upstream.fetch_doc()
        req = captured.get("req")
        self.assertIsInstance(req, urllib.request.Request)
        ua = req.get_header("User-agent")
        self.assertIsNotNone(ua)
        self.assertNotIn("Python-urllib", ua)

    def test_certifi_retry_sends_the_same_user_agent(self):
        fake_certifi = types.ModuleType("certifi")
        fake_certifi.where = lambda: "/fake/cafile"
        captured = []
        def fake_urlopen(req, timeout=None, context=None, **kw):
            captured.append(req)
            if len(captured) == 1:
                raise _cert_error()
            raise OSError("stop after capturing the retry request")
        with mock.patch("project_os.upstream.urllib.request.urlopen", side_effect=fake_urlopen), \
             mock.patch.dict("sys.modules", {"certifi": fake_certifi}), \
             mock.patch("project_os.upstream.ssl.create_default_context", return_value=mock.MagicMock()):
            upstream.fetch_doc()
        self.assertEqual(len(captured), 2)
        retry_req = captured[1]
        self.assertIsInstance(retry_req, urllib.request.Request)
        ua = retry_req.get_header("User-agent")
        self.assertIsNotNone(ua)
        self.assertNotIn("Python-urllib", ua)


class TestFetchDocDistinguishesSSL(unittest.TestCase):
    """A stock python.org install on macOS ships with no CA bundle at all -- urlopen fails
    with URLError(SSLCertVerificationError), while curl works fine (it uses the system
    keychain). Swallowing that into the same "network" bucket as a real DNS/timeout failure
    produces a FALSE diagnostic ("no network, or the doc's format changed") when the doc was
    reachable the whole time. fetch_doc must tell the two apart, and NEVER work around the
    SSL failure by disabling certificate verification -- only an opportunistic retry with
    certifi's CA bundle, still verifying the real chain."""

    def test_ssl_cert_failure_is_reported_as_ssl_not_network(self):
        cert_err = ssl.SSLCertVerificationError("unable to get local issuer certificate")
        with mock.patch("project_os.upstream.urllib.request.urlopen", side_effect=urllib.error.URLError(cert_err)):
            text, error = upstream.fetch_doc()
        self.assertIsNone(text)
        self.assertEqual(error, "ssl")

    def test_generic_failure_is_still_reported_as_network(self):
        with mock.patch("project_os.upstream.urllib.request.urlopen", side_effect=OSError("boom")):
            text, error = upstream.fetch_doc()
        self.assertIsNone(text)
        self.assertEqual(error, "network")


if __name__ == "__main__":
    unittest.main()
