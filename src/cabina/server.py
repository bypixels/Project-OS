"""`cabina` (UI) — local HTTP server on 127.0.0.1 with a per-session CSRF token.
Reads through the modules; writes only via: create/archive agent, archive skill,
save doc (guarded), open path, rescan cache, install hooks (guarded)."""
import os, sys, json, copy, re, secrets, threading, webbrowser, time, difflib, ipaddress
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import scan, skills as SK, projects as PROJ, harness as HAR, usage, live as LIVE, host, drift as DR, gitops as GO, sessions as SESS, check as CHECK, guard as GUARD, snapshot as SNAP, healthlog as HEALTHLOG, worktrees as WT
from .roster import Roster
from .docs import Docs
from .i18n import STRINGS

STATIC = os.path.join(os.path.dirname(__file__), "static")
_activity_refresh_lock = threading.Lock()   # non-blocking: skip a refresh already in flight, never queue one behind the request thread
MAX_POST_BODY = 5 * 1024 * 1024   # S3-C: /api/compare accepts an arbitrary export from another machine
_LOOPBACK_HOSTS = {"localhost"}


def _loopback_only(hostname):
    """Return True only for localhost or an IP address marked loopback by ipaddress."""
    if not isinstance(hostname, str):
        return False
    value = hostname.strip().lower().rstrip(".")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _header_hostname(value):
    """Extract a Host header hostname without ever treating a non-IP as trusted."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.startswith("["):
        end = raw.find("]")
        if end < 0:
            return None
        raw = raw[1:end]
    else:
        try:
            ipaddress.ip_address(raw)
        except ValueError:
            raw = raw.split(":", 1)[0]
    raw = raw.strip().lower()
    return raw or None


def host_allowed(host_header, bind_host):
    """Anti-DNS-rebinding guard: True only if `host_header` (the raw `Host:` request header,
    possibly with a port, possibly an IPv6 literal in brackets) names loopback or the exact
    configured bind host. Without this, an attacker's DNS name resolving to 127.0.0.1 could
    serve a page that reads the token off `/` and POSTs with it -- the browser sends that
    page's own Host header, which this rejects. Any error extracting a hostname is a refusal."""
    if not host_header or not isinstance(host_header, str):
        return False
    return _loopback_only(_header_hostname(host_header))


def _origin_hostname(origin):
    """Hostname from an `Origin:` header value (a URL like `http://evil.example` or
    `http://127.0.0.1:8930`), lowercased. None on anything unparsable."""
    try:
        h = urlparse(origin).hostname
    except Exception:
        return None
    return h.lower() if h else None


def origin_allowed(origin, bind_host):
    """POST-only CSRF guard: True only when `origin` names localhost or a loopback IP.
    The configured bind host is intentionally not an additional trust source."""
    oh = _origin_hostname(origin)
    if not oh:
        return False
    return _loopback_only(oh)


def _open_allowed(path, allowed_roots):
    """U3: True if the realpath of `path` is inside (or equal to) one of `allowed_roots`
    (each realpath'd too, so a symlinked root still confines correctly). Isolated as its own
    function -- not inlined into api_open -- so a break-test can disable it without touching
    os.path.realpath itself. Any error resolving a candidate root is skipped, never trusted."""
    try:
        real = os.path.realpath(path)
    except Exception:
        return False
    for root in allowed_roots or []:
        if not root:
            continue
        try:
            r = os.path.realpath(root)
        except Exception:
            continue
        if real == r or real.startswith(r + os.sep):
            return True
    return False


def _terminal_target_ok(path, allowed_roots):
    """W3: like `_open_allowed`, plus the target must be a directory -- a terminal opens AT a
    place, opening it "on" a file makes no sense and would be confusing if silently accepted.
    Isolated from `_open_allowed` (composed, not inlined) so a break-test can disable just this
    extra check, or `_open_allowed` itself, independently."""
    if not _open_allowed(path, allowed_roots):
        return False
    try:
        return os.path.isdir(os.path.realpath(path))
    except Exception:
        return False


def _health_totals(findings):
    """R13: the tiles header's global {crit,warn,info} -- every finding counted exactly ONCE
    by severity, including ones with no `projects` key (global findings) and without
    double-counting one attributed to more than one project. Kept separate from the per-tile
    sums in api_tiles(), which intentionally count a multi-project finding once per tile."""
    tot = {"crit": 0, "warn": 0, "info": 0}
    for f in findings:
        if f.get("sev") in tot:
            tot[f["sev"]] += 1
    return tot


def _order_tiles(tiles):
    """R13: active projects first, then by last_session descending (missing/None last), then
    by name -- deterministic regardless of dict/set iteration order. Three stable sorts applied
    least-significant-key first (Python's sort is stable, so each pass only breaks ties left by
    the previous one)."""
    out = list(tiles)
    out.sort(key=lambda t: t["project"])
    out.sort(key=lambda t: t["last_session"] or "", reverse=True)
    out.sort(key=lambda t: not t["active"])
    return out


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.data = scan.ensure(cfg)
        self.live = LIVE.get(cfg)
        self._roster = None; self._rows = None; self._items = None; self._t = 0
        self._skills = None; self._skills_t = 0
        self._scan_lock = threading.Lock()          # non-blocking: a second POST /api/rescan while one runs is refused, not queued
        self._scanning = False
        self._scan_started = None; self._scan_finished = None; self._scan_error = None

    # ---- helpers ----
    def roster(self, fresh=False):
        with self.lock:
            if fresh or self._roster is None or time.time() - self._t > 30:
                self._roster = Roster(self.cfg, self.data)
                self._rows, self._items = self._roster.load(refresh_usage=fresh or self._rows is None)
                self._t = time.time()
            return self._roster, self._rows, self._items

    def skills(self, fresh=False):
        """Same TTL-cached pattern as roster(): usage.refresh() greps every transcript under
        ~/.claude/projects, so a request thread must not pay that cost on every GET."""
        with self.lock:
            if fresh or self._skills is None or time.time() - self._skills_t > 30:
                rows = self._skill_catalog()
                p = os.path.join(self.cfg["state_dir"], "usage-skills.json")
                items, meta = usage.refresh(p, os.path.join(self.cfg["claude_home"], "projects"), "skills",
                                            {k: v for k, v in self.roots().items() if k != "global"})
                for r in rows:
                    u = usage.for_agent(items, r["name"], r["project"]); r["uses"] = u["total"]; r["last"] = u["last"]; r["uses_here"] = u["here"]
                self._skills = (rows, meta); self._skills_t = time.time()
            return self._skills

    def _skill_catalog(self):
        """Read the current filesystem catalog without refreshing usage metrics."""
        rows = SK.load(self.cfg, self.data)
        for r in rows:
            r["tool"] = "claude"
        cx = self.data.get("codex", {})
        if cx.get("present"):
            for r in SK.scan_dir(os.path.join(cx["home"], "skills"), "global"):
                r["tool"] = "codex"
                rows.append(r)
        return rows

    def roots(self):
        return scan.project_roots(self.cfg, self.data)

    def docs(self):
        d = self.cfg["docs"]
        return Docs(self.roots(), os.path.join(self.cfg["state_dir"], "doc-backups"), d["backup_retention_days"], d["max_per_dir"])

    def working(self):
        base = set(LIVE.working_projects(self.live, self.roots()))
        try:
            base |= LIVE.TranscriptProvider(self.cfg).active_projects(self.roots())
        except Exception:
            pass                                                 # never let this signal break the guard itself
        return sorted(base)

    # ---- GET ----
    def api_agents(self):
        R, rows, items = self.roster()
        hom = Roster.homonyms(rows)
        out = []
        for proj, r, path, tool in rows:
            u = usage.for_agent(items, r.name, proj) if tool == "claude" else {"last": None, "total": 0, "here": None, "attributed": True}
            out.append({"name": r.name, "project": proj, "tool": tool, "category": r.category, "model": r.fields.get("model", ""),
                        "tools": r.fields.get("tools", ""), "description": r.fields.get("description", ""),
                        "critical": r.critical, "warnings": r.warnings, "last": u["last"], "uses": u["total"],
                        "uses_here": u["here"], "attributed": u["attributed"], "homonyms": hom.get(r.name, 0) if tool == "claude" else 0,
                        "path": path, "is_agent": r.is_agent})
        meta = {}
        try:
            meta = json.load(open(R.usage_path)).get("meta", {})
        except Exception:
            pass
        return {"agents": out, "projects": sorted(self.roots().keys()), "window": meta.get("history_window_from"),
                "codex_present": bool(self.data.get("codex", {}).get("present"))}

    def api_skills(self):
        rows, meta = self.skills()
        return {"skills": rows, "window": meta.get("history_window_from")}

    def api_projects(self): return {"projects": PROJ.load(self.data)}
    def api_harness(self): return {"states": HAR.states(self.data), "runlogs": HAR.runlogs(self.data), "drift": DR.report(self.cfg, self.data)}
    def api_live(self): return self.live.list() | {"provider": self.live.name}
    def api_docs(self): return {"docs": self.docs().list_all(), "working": self.working()}
    def api_doc(self, q):
        proj = q.get("project", [""])[0]; rel = q.get("rel", [""])[0]
        r = self.docs().read(proj, rel)
        if r.get("ok"):
            r["blocked"] = proj in self.working()
        return r
    def api_doc_versions(self, q):
        """Read-only: newest-first backup history for one doc. Empty list on anything
        unresolvable -- see Docs.versions()."""
        proj = q.get("project", [""])[0]; rel = q.get("rel", [""])[0]
        return {"versions": self.docs().versions(proj, rel)}
    def api_doc_version(self, q):
        """Read-only: one backed-up version's text (Docs.version_text -- validates the stamp
        and confines the file), plus a unified diff to the CURRENT on-disk content (read through
        Docs.read(), so the same allowlist applies) and a `command` the user could paste to
        restore it -- generated, never run, same discipline as worktrees.py's script(). `command`
        is null with a `command_reason` when either path is unsafe to embed in a shell argument
        (WT._is_unsafe, reused rather than reimplemented)."""
        proj = q.get("project", [""])[0]; rel = q.get("rel", [""])[0]; stamp = q.get("stamp", [""])[0]
        docs = self.docs()
        r = docs.version_text(proj, rel, stamp)
        if not r.get("ok"):
            return r
        cur = docs.read(proj, rel)
        current_text = cur.get("content", "") if cur.get("ok") else ""
        r["diff"] = "".join(difflib.unified_diff(
            r["content"].splitlines(keepends=True), current_text.splitlines(keepends=True),
            fromfile=f"{rel}@{stamp}", tofile=f"{rel} (current)"))
        doc_path = cur.get("path") if cur.get("ok") else None
        bd, base, err = docs._backup_loc(proj, rel)
        if err or not doc_path:
            r["command"] = None; r["command_reason"] = "document path unavailable"
            return r
        backup_path = os.path.join(bd, f"{base}.{stamp}.md")
        if WT._is_unsafe(backup_path) or WT._is_unsafe(doc_path):
            r["command"] = None; r["command_reason"] = "path has characters unsafe to paste into a shell"
            return r
        r["command"] = (f'copy /Y "{backup_path}" "{doc_path}"' if os.name == "nt" else f'cp "{backup_path}" "{doc_path}"')
        return r
    def api_references(self, q):
        R, _, _ = self.roster()
        return {"references": R.references(q.get("name", [""])[0])}
    def api_health(self):
        """S1: the same findings `cabina check` prints, for the Health tab. Never lets the
        tab render blank — any exception from check.run() becomes an empty findings list plus
        an `error` string, still 200."""
        try:
            findings = CHECK.run(self.cfg, quick=False)
        except Exception as e:
            return {"findings": [], "error": str(e)}
        HEALTHLOG.append(self.cfg, findings)
        return {"findings": findings, "ran_at": datetime.now().isoformat(timespec="seconds"), "quick": False}

    def api_health_history(self, q):
        """R12/Fase 3: the health.jsonl series for the Health tab's sparkline."""
        try:
            days = int((q.get("days") or ["30"])[0])
        except Exception:
            days = 30
        days = max(1, min(days, 365))
        return {"series": HEALTHLOG.read(self.cfg, days)}

    def api_tiles(self):
        """R13: read-only "project dashboard" -- one tile per project with last_session,
        active/idle, health (crit/warn/info attributed by check.py's `projects` key) and
        open_findings_count. Deliberately NOTHING task-like (no status/assignee/free text).
        Runs the SAME check.run(quick=False) the Health tab uses, so the two never disagree.
        Never lets the tab render blank: an exception from CHECK.run() still returns tiles
        with zero health, plus an `error` string."""
        try:
            findings = CHECK.run(self.cfg, quick=False)
            error = None
        except Exception as e:
            findings, error = [], str(e)
        names = [p["name"] for p in PROJ.load(self.data)]
        g = self.data.get("global") or {}
        if g.get("agents") or g.get("skills"):
            names = ["global"] + names
        last_by_project = {}
        for s in SESS.load(self.cfg):
            proj = s.get("project")
            when = s.get("ended") or s.get("started")
            if not proj or not when:
                continue
            if proj not in last_by_project or when > last_by_project[proj]:
                last_by_project[proj] = when
        working = set(self.working())
        tiles = []
        for name in names:
            h = {"crit": 0, "warn": 0, "info": 0}
            for f in findings:
                if name in (f.get("projects") or ()) and f["sev"] in h:
                    h[f["sev"]] += 1
            tiles.append({"project": name, "last_session": last_by_project.get(name), "active": name in working,
                          "health": h, "open_findings_count": h["crit"] + h["warn"] + h["info"]})
        out = {"tiles": _order_tiles(tiles), "health": _health_totals(findings), "ran_at": datetime.now().isoformat(timespec="seconds")}
        if error:
            out["error"] = error
        return out

    def api_mcp(self):
        """MCP tab: reads ONLY the cached scan data -- never triggers a scan or shells out to
        the `claude` CLI (that only happens in scan.py's mcp_servers(), gated behind --mcp)."""
        m = self.data.get("mcp") or {}
        servers = list(m.get("servers") or [])
        order = {"failed": 0, "auth": 1, "unverified": 2, "ok": 3}
        servers.sort(key=lambda s: (order.get(s.get("status"), 9), s.get("name", "")))
        counts = {"ok": 0, "auth": 0, "unverified": 0, "failed": 0, "total": len(servers)}
        for s in servers:
            if s.get("status") in counts: counts[s["status"]] += 1
        return {"checked": bool(m.get("checked")), "servers": servers, "counts": counts}

    def api_worktrees(self, q):
        """W3: worktree cleanup summary/rows/script for the Projects tab panel, optionally
        scoped to one project. Reads the cached scan data via worktrees.py -- never re-scans."""
        project = (q.get("project") or [None])[0] or None
        return {"summary": WT.summary(self.cfg, data=self.data, project=project),
                "rows": WT.rows(self.cfg, data=self.data, project=project),
                "script": WT.script(self.cfg, data=self.data, project=project)}

    def _hooks_settings_path(self):
        return os.path.join(self.cfg["claude_home"], "settings.json")

    @staticmethod
    def _sane_cmd(cmd):
        """Only ever fed to shutil.which/shlex.split — never executed. Reject anything that
        isn't a short, single-line string; fall back to the default rather than guessing."""
        if not isinstance(cmd, str) or not cmd.strip() or len(cmd) > 200 or "\n" in cmd or "\r" in cmd:
            return "cabina"
        return cmd.strip()

    def api_hooks(self, q):
        cmd = self._sane_cmd((q.get("cmd") or ["cabina"])[0])
        return GUARD.hooks_status(self._hooks_settings_path(), cmd)

    # ---- POST ----
    def api_archive(self, b):
        R, _, _ = self.roster()
        ok, msg, refs = R.archive(b["name"], b["project"], bool(b.get("force")), tool=b.get("tool", "claude"))
        if ok: self.roster(fresh=True)
        return {"ok": ok, "message": msg, "references": refs}
    def api_create(self, b):
        R, _, _ = self.roster()
        ok, msg, path = R.create(b["project"], b["name"], b["description"], b["model"], b["tools"], b.get("body", ""))
        if ok: self.roster(fresh=True)
        return {"ok": ok, "message": msg, "path": path}
    def _find_skill(self, q):
        """Resolve one skill row from query params through the same catalog api_skills reads --
        NEVER accept a filesystem path directly from the client."""
        tool = (q.get("tool") or ["claude"])[0]
        project = (q.get("project") or [""])[0]
        name = (q.get("name") or [""])[0]
        rows, _ = self.skills()
        matches = [r for r in rows if (r.get("tool") or "claude") == tool and r.get("project") == project and r.get("name") == name]
        return matches[0] if len(matches) == 1 else None

    def api_skill_body(self, q):
        """Read-only: the skill's SKILL.md body plus a listing of its own directory."""
        row = self._find_skill(q)
        if not row or not isinstance(row.get("path"), str) or not row["path"]:
            return {"ok": False, "message": "unknown or ambiguous skill identity"}
        r = SK.read_body(row["path"])
        if not r.get("ok"):
            return r
        return {**r, "name": row["name"], "project": row["project"], "tool": row.get("tool") or "claude", "path": row["path"]}

    def api_skill_file(self, q):
        """Read-only preview of one attachment inside a skill's own directory."""
        row = self._find_skill(q)
        if not row or not isinstance(row.get("path"), str) or not row["path"]:
            return {"ok": False, "message": "unknown or ambiguous skill identity"}
        rel = (q.get("path") or [""])[0]
        r = SK.read_file(row["path"], rel)
        if not r.get("ok"):
            return r
        return {**r, "name": row["name"], "project": row["project"], "tool": row.get("tool") or "claude", "path": row["path"]}

    def api_archive_skill(self, b):
        # References only need the roster's filesystem roots; avoid loading agent usage here.
        R = self._roster or Roster(self.cfg, self.data)
        refs = R.references(b["name"])
        if refs and not b.get("force"):
            return {"ok": False, "message": f"{len(refs)} file(s) reference {b['name']!r}", "references": refs}
        rows = self._skill_catalog()
        matches = [r for r in rows if r.get("name") == b["name"] and r.get("project") == b["project"]]
        if len(matches) != 1:
            return {"ok": False, "message": "unknown or ambiguous skill identity", "references": refs}
        canonical = matches[0].get("path")
        if not isinstance(canonical, str) or not canonical:
            return {"ok": False, "message": "skill path unavailable", "references": refs}
        ok, msg = SK.archive_path(canonical, b["project"], os.path.join(self.cfg["claude_home"], "_archive"),
                                  allowed_root=os.path.dirname(canonical))
        if ok: self.skills(fresh=True)
        return {"ok": ok, "message": msg, "references": refs}
    def api_save_doc(self, b):
        return self.docs().save(b["project"], b["rel"], b["content"], b["hash"], working=self.working())
    def api_open(self, b):
        """U3: confined to cabina's own roots -- project roots (incl. global -> claude_home),
        codex_home and state_dir -- so a POST here can never be used to open an arbitrary path
        on the machine (and, on Windows, os.startfile an arbitrary file)."""
        p = os.path.realpath(os.path.expanduser(b["path"]))
        roots = list(self.roots().values()) + [self.cfg["claude_home"], self.cfg["codex_home"], self.cfg["state_dir"]]
        if not _open_allowed(p, roots):
            return {"ok": False, "message": "path outside cabina roots"}
        ok, msg = host.open_path(p); return {"ok": ok, "message": msg}
    def api_open_terminal(self, b):
        """W3: opens a terminal emulator AT a path -- confined to cabina's own roots (same list
        as api_open) AND the target must be a directory. The terminal binary itself is picked by
        host.open_terminal from a fixed per-OS allowlist, never from this request's body."""
        p = os.path.realpath(os.path.expanduser(b["path"]))
        roots = list(self.roots().values()) + [self.cfg["claude_home"], self.cfg["codex_home"], self.cfg["state_dir"]]
        if not _terminal_target_ok(p, roots):
            return {"ok": False, "message": "path outside cabina roots, or not a directory"}
        ok, msg = host.open_terminal(p); return {"ok": ok, "message": msg}
    def api_focus(self, b):
        ok, msg = self.live.focus(b["pane"]); return {"ok": ok, "message": msg}
    def api_commit(self, b):
        """Commit ONE path cabina just changed. Only on explicit request from the UI checkbox."""
        path = os.path.expanduser(b["path"]); msg = (b.get("message") or "cabina: change")[:200]
        ok, out = GO.commit_path(path, msg)
        return {"ok": ok, "message": out, "in_repo": GO.repo_root(path) is not None}
    def api_in_repo(self, q):
        p = os.path.expanduser(q.get("path", [""])[0]); root = GO.repo_root(p)
        return {"in_repo": root is not None, "root": root}
    def api_activity(self, q):
        days = int((q.get("days") or ["30"])[0])
        proj = (q.get("project") or [""])[0]
        def go():
            if not _activity_refresh_lock.acquire(blocking=False):
                return                                    # a refresh is already running; this GET serves the cache as-is
            try:
                SESS.refresh(self.cfg, days=days)
            finally:
                _activity_refresh_lock.release()
        threading.Thread(target=go, daemon=True).start()   # never parse on the request thread
        items = SESS.load(self.cfg)
        if proj:
            items = [s for s in items if s.get("project") == proj]
        cutoff = time.time() - days * 86400
        def _recent(s):
            started = s.get("started")
            if not started:
                return False
            try:
                from datetime import datetime
                return datetime.fromisoformat(started).timestamp() >= cutoff
            except Exception:
                return False
        items = [s for s in items if _recent(s)]
        return {"sessions": items, "days": days, "active_seconds": (self.cfg.get("live") or {}).get("active_seconds", 600)}

    def api_hooks_install(self, b):
        cmd = self._sane_cmd(b.get("cmd") or "cabina")
        sp = self._hooks_settings_path()
        ok, msg = GUARD.hooks_write(sp, cmd, force=bool(b.get("force")))
        return {"ok": ok, "message": msg, "status": GUARD.hooks_status(sp, cmd)}

    def api_rescan(self, b):
        """S3-A: `mcp`/`worktrees` in the body opt into the slow scan passes, same as `cabina scan
        --mcp --worktrees`, but gated on a COPY of self.cfg — self.cfg is never mutated, so a
        one-off slow rescan does not silently turn the option on for every future rescan. The
        lock is acquired here, synchronously, on the request thread: a second POST while one is
        in flight must be refused regardless of how fast the background thread gets scheduled."""
        if not self._scan_lock.acquire(blocking=False):
            return {"ok": False, "message": "a scan is already running"}
        self._scanning = True
        self._scan_started = datetime.now().isoformat(timespec="seconds")
        self._scan_finished = None
        self._scan_error = None
        body = b or {}
        def go():
            d = None
            try:
                try:
                    cfg = copy.deepcopy(self.cfg)
                    cfg["scan"]["check_mcp"] = cfg["scan"].get("check_mcp") or bool(body.get("mcp"))
                    cfg["scan"]["measure_worktrees"] = cfg["scan"].get("measure_worktrees") or bool(body.get("worktrees"))
                    d = scan.run(cfg)
                    scan.save(self.cfg, d)
                except Exception as e:
                    self._scan_error = str(e)
                # Publish self.data/_roster/_skills BEFORE flipping _scanning False, and flip
                # _scanning False BEFORE releasing the lock: a GET /api/scan-status poller that
                # observes scanning=False must already see the new self.data (never a stale
                # reload), and a POST /api/rescan that observes scanning=False before the lock
                # is actually free must still be refused with "a scan is already running"
                # rather than starting a second scan concurrently with this one's cleanup.
                if d is not None:
                    with self.lock:
                        self.data = d; self._roster = None; self._skills = None
                self._scan_finished = datetime.now().isoformat(timespec="seconds")
                self._scanning = False
            finally:
                self._scan_lock.release()   # always last, even if the above raised
        threading.Thread(target=go, daemon=True).start()
        return {"ok": True, "message": "rescanning in the background"}

    def api_scan_status(self):
        scanned_at = None
        try:
            scanned_at = datetime.fromtimestamp(os.path.getmtime(scan.cache_path(self.cfg))).isoformat(timespec="seconds")
        except OSError:
            pass
        return {"scanning": self._scanning, "started": self._scan_started, "finished": self._scan_finished,
                "error": self._scan_error, "scanned_at": scanned_at}

    def api_export(self, q):
        """S3-B: `cabina export [--activity [--detail]]` from the browser. `--titles` is
        deliberately NOT exposed here — session titles can echo prompt content, and this path is
        for handing the file to a teammate or another machine, unlike the CLI flag which is a
        conscious opt-in on your own box."""
        want_activity = (q.get("activity", ["0"])[0]) == "1"
        want_detail = (q.get("detail", ["0"])[0]) == "1"
        activity = SNAP.export_activity(self.cfg, detail=want_detail) if want_activity else None
        return SNAP.export(self.cfg, activity=activity)

    def api_compare(self, b):
        other = b.get("other")
        if not isinstance(other, dict) or "agents" not in other:
            return {"ok": False, "message": "not a cabina export"}
        # P4 (snapshot.compare): only pull local activity into A when B's export carries it too —
        # otherwise A vs B would compare a real activity aggregate against nothing, a false delta.
        activity = SNAP.export_activity(self.cfg) if isinstance(other.get("activity"), dict) else None
        a = SNAP.export(self.cfg, activity=activity)
        delta = SNAP.compare(a, other)
        text = SNAP.render_compare(delta, a.get("machine"), other.get("machine"))
        return {"ok": True, "text": text, "delta": delta}


def make_handler(app):
    GETS = {"/api/agents": lambda q: app.api_agents(), "/api/skills": lambda q: app.api_skills(),
            "/api/projects": lambda q: app.api_projects(), "/api/harness": lambda q: app.api_harness(),
            "/api/live": lambda q: app.api_live(), "/api/docs": lambda q: app.api_docs(),
            "/api/doc": app.api_doc, "/api/doc-versions": app.api_doc_versions, "/api/doc-version": app.api_doc_version,
            "/api/references": app.api_references, "/api/in-repo": app.api_in_repo,
            "/api/activity": app.api_activity, "/api/health": lambda q: app.api_health(), "/api/hooks": app.api_hooks,
            "/api/scan-status": lambda q: app.api_scan_status(), "/api/health-history": app.api_health_history,
            "/api/tiles": lambda q: app.api_tiles(), "/api/worktrees": app.api_worktrees,
            "/api/mcp": lambda q: app.api_mcp(), "/api/skill-body": app.api_skill_body, "/api/skill-file": app.api_skill_file}
    POSTS = {"/api/archive": app.api_archive, "/api/create": app.api_create, "/api/archive-skill": app.api_archive_skill,
             "/api/save-doc": app.api_save_doc, "/api/open": app.api_open, "/api/open-terminal": app.api_open_terminal, "/api/focus": app.api_focus, "/api/rescan": app.api_rescan, "/api/commit": app.api_commit,
             "/api/hooks-install": app.api_hooks_install, "/api/compare": app.api_compare}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _json(self, obj, code=200, extra_headers=None):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
            for k, v in (extra_headers or {}).items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            if not host_allowed(self.headers.get("Host"), app.cfg["server"]["host"]):
                return self._json({"ok": False, "message": "bad host"}, 421)
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
                lang = app.cfg["language"] if app.cfg["language"] in STRINGS else "en"
                html = html.replace("__TOKEN__", app.token).replace("__LANG__", lang).replace("__HUB__", "0")
                b = html.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b); return
            if u.path == "/api/export":
                try:
                    obj = app.api_export(parse_qs(u.query))
                except Exception as e:
                    return self._json({"ok": False, "message": str(e)}, 500)
                machine = re.sub(r"[^A-Za-z0-9_.-]", "-", str(obj.get("machine") or "unknown"))
                fname = f"cabina-{machine}-{datetime.now().strftime('%Y%m%d')}.json"
                return self._json(obj, extra_headers={"Content-Disposition": f'attachment; filename="{fname}"'})
            fn = GETS.get(u.path)
            if not fn: return self._json({"error": "not found"}, 404)
            try: return self._json(fn(parse_qs(u.query)))
            except Exception as e: return self._json({"ok": False, "message": str(e)}, 500)
        def do_POST(self):
            if not host_allowed(self.headers.get("Host"), app.cfg["server"]["host"]):
                return self._json({"ok": False, "message": "bad host"}, 421)
            origin = self.headers.get("Origin")
            if origin and not origin_allowed(origin, app.cfg["server"]["host"]):
                return self._json({"ok": False, "message": "bad origin"}, 403)
            if self.headers.get("X-Cabina-Token") != app.token:
                return self._json({"ok": False, "message": "invalid token"}, 403)
            n = int(self.headers.get("Content-Length", 0))
            if n > MAX_POST_BODY:
                # drain the socket in chunks (never buffer the oversized body) so the client's
                # sendall() completes cleanly instead of a BrokenPipeError from an early close
                remaining = n
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk: break
                    remaining -= len(chunk)
                return self._json({"ok": False, "message": "request body too large"}, 400)
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except Exception: return self._json({"ok": False, "message": "invalid JSON"}, 400)
            fn = POSTS.get(urlparse(self.path).path)
            if not fn: return self._json({"error": "not found"}, 404)
            try: return self._json(fn(body))
            except KeyError as e: return self._json({"ok": False, "message": f"missing field {e}"}, 400)
            except Exception as e: return self._json({"ok": False, "message": str(e)}, 500)
    return H


def serve(cfg, port=None, open_browser=True):
    host_ = cfg["server"]["host"]; port = port or cfg["server"]["port"]
    if not _loopback_only(host_):
        raise ValueError("cabina server is local-only: server.host must be localhost or a loopback IP")
    app = App(cfg)
    srv = ThreadingHTTPServer((host_, port), make_handler(app))
    url = f"http://{host_}:{srv.server_address[1]}/"
    print(f"cabina at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return srv
