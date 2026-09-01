"""Optional, opt-in drift check between `contract.known_fields` and Claude Code's own
sub-agents documentation. Writes nothing, ever. Touches the network ONLY when `check.run(cfg,
upstream=True)` is called (never on a plain `project-os check`) -- a failed fetch or a doc whose
format no longer parses is reported neutrally by the caller, never as a critical finding and
never as a non-zero exit code."""
import re
import ssl
import urllib.request

from . import __version__

DOC_URL = "https://code.claude.com/docs/en/sub-agents.md"
TIMEOUT = 5
# The doc's CDN returns HTTP 403 for Python's default User-Agent ("Python-urllib/x.y") even
# though curl -- a different UA, otherwise the same request -- gets a real 200 for the same URL
# (verified empirically). An identifiable, non-default UA is required on every attempt, or the
# fetch looks like a network failure that is actually a UA-based block.
_USER_AGENT = f"project-os/{__version__} (+https://github.com/dsandimolina/project-os)"

def parse_fields(markdown):
    """Frontmatter field names (backtick-quoted, first column) from the ONE markdown table in
    `markdown` whose header's first cell is exactly "Field".

    The doc is NOT "one table of fields, then tables of values" -- it has tables both before
    and after the field reference. As of this writing, the doc's actual FIRST table is
    Location/Scope/Priority (where a subagent file can live), and later tables (e.g.
    Mode/Behavior for `permissionMode`, Scope/Location for `memory`) list VALUES a field can
    take (`default`, `acceptEdits`, `user`, `project`...) -- neither is the field reference, and
    "just take the first table" silently returns zero fields on the real doc (a defect this
    replaced: it made `check --upstream` report "unavailable" forever, even with working
    certificates). The one table that IS the field reference is identifiable regardless of
    surrounding structure by its own header: first cell "Field". If no table has that header,
    returns [] -- exactly like a fetch failure, never a false alarm."""
    lines = markdown.splitlines()
    n = len(lines)
    header = None
    for i in range(n - 1):
        line = lines[i]
        if not line.lstrip().startswith("|"):
            continue
        cells = line.split("|")
        first_cell = cells[1].strip() if len(cells) > 1 else ""
        if first_cell == "Field" and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            header = i
            break
    if header is None:
        return []
    fields = []
    j = header + 2
    while j < n and lines[j].lstrip().startswith("|"):
        # Search the FIRST CELL only, not the whole row -- the real doc's own `name` row has a
        # backtick (`agent_type`) inside its Description cell, and a plain re.search over the
        # full line would grab that instead when a row's first cell carries no backtick.
        row_cells = lines[j].split("|")
        first_cell = row_cells[1] if len(row_cells) > 1 else ""
        m = re.search(r"`([A-Za-z][A-Za-z0-9_-]*)`", first_cell)
        if m:
            fields.append(m.group(1))
        j += 1
    return fields


def _is_cert_error(e):
    return isinstance(getattr(e, "reason", e), ssl.SSLCertVerificationError)


def fetch_doc(url=DOC_URL, timeout=TIMEOUT):
    """(text, error): text is None on ANY failure; error is None on success, "ssl" for an
    unverifiable TLS certificate chain, "network" for everything else (DNS, timeout, HTTP
    status, decode...). Never raises -- the caller must treat a None text as 'could not
    verify', never as a finding about the environment. Worst-case wall time is 2 * `timeout`
    (10s at the TIMEOUT default): a cert failure triggers one full second attempt before the
    certifi retry gets its own full `timeout` budget, not `timeout` overall.

    A stock python.org install on macOS ships with NO CA bundle at all, so urlopen fails with
    URLError(SSLCertVerificationError) even though the doc is perfectly reachable (curl works
    there because it uses the system keychain, not Python's). Lumping that into the same
    "network" bucket as a real DNS/timeout failure is a false diagnostic. On that specific
    failure only, retry once with certifi's CA bundle if it's importable -- this still verifies
    the real certificate chain against a real trust store; it NEVER falls back to
    ssl._create_unverified_context() or otherwise disables verification, which would trade a
    true "could not verify" for a false "verified". The retry's OWN outcome is classified on its
    own merits, not blanket-labeled "ssl": certifi missing, or the retry hitting a real cert
    error of its own (e.g. a corporate proxy CA outside certifi's bundle), still reports "ssl";
    but the retry failing for an UNRELATED reason (timeout, DNS) reports "network" -- otherwise a
    real network outage during the retry would misreport as a certificate problem. Every
    attempt -- first AND retry -- sends an identifiable User-Agent (see _USER_AGENT above): the
    doc's CDN 403s Python's default UA, which would otherwise look identical to a real network
    failure."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except Exception as e:
        if not _is_cert_error(e):
            return None, "network"
        try:
            import certifi
        except ImportError:
            return None, "ssl"   # certifi isn't installed -- the original cert diagnosis stands
        try:
            ctx = ssl.create_default_context(cafile=certifi.where())
            retry_req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(retry_req, timeout=timeout, context=ctx) as resp:
                return resp.read().decode("utf-8", errors="replace"), None
        except Exception as e2:
            # The retry's OWN failure gets classified on its own merits -- a real cert error
            # here (e.g. a corporate proxy CA outside certifi's bundle) is still "ssl", but an
            # unrelated failure (timeout, DNS) must read as "network", or a real network outage
            # during the retry would misreport as a certificate problem.
            return None, ("ssl" if _is_cert_error(e2) else "network")


def compare(cfg):
    """Compare Contract(cfg, tool="claude").known against the fields the live doc documents.
    Returns {"unavailable": True, "reason": "ssl"|"network"} when the fetch failed or parsed to
    zero fields (an unparseable doc looks identical to no doc, deliberately -- never a false
    alarm; that case reports "network", the generic reason -- only a real cert failure reports
    "ssl"). Otherwise: {"unavailable": False, "missing": [...], "extra": [...]} --
      missing = documented by Claude Code but NOT known to project-os (the known_fields list
                is stale; every one of these would wrongly warn "fields Claude Code does not
                read" on a real agent using it).
      extra   = known to project-os but NOT in today's doc (informational only: could be a
                project-os convention, a partial/outdated doc, or a retired field -- never an
                error by itself). Includes project-os's own conventions (`overrides`, `version`)
                on purpose -- they are never in Claude Code's doc by design, and this bucket is
                exactly where "known but undocumented, and that's fine" belongs; the message
                in check.py, not a silent filter here, is what keeps that from reading as drift.
    Calls the module-level `fetch_doc` by name (not a bound default argument) so tests can
    `mock.patch("project_os.upstream.fetch_doc", ...)` and have it actually take effect. The
    module docstring promises a failure here is NEVER a critical finding and never a crash --
    that covers the fetch AND the parse/comparison that follows it, so the whole body after the
    fetch is guarded too (a doc shape parse_fields doesn't expect, a broken Contract config...
    must still report "unavailable", not blow up `check`)."""
    from .contract import Contract
    try:
        text, reason = fetch_doc()
    except Exception:
        text, reason = None, "network"
    if not text:
        return {"unavailable": True, "reason": reason or "network", "missing": [], "extra": []}
    try:
        doc_fields = parse_fields(text)
        if not doc_fields:
            return {"unavailable": True, "reason": "network", "missing": [], "extra": []}
        C = Contract(cfg, tool="claude")
        doc_set = set(doc_fields)
        known_extra = C.known - set(C.required)   # the config's own known_fields, not the 4 required ones
        missing = sorted(doc_set - C.known)
        extra = sorted(known_extra - doc_set)
        return {"unavailable": False, "missing": missing, "extra": extra}
    except Exception:
        return {"unavailable": True, "reason": "network", "missing": [], "extra": []}
