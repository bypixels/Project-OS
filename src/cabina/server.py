"""`cabina` (UI) — local HTTP server on 127.0.0.1 with a per-session CSRF token.
Reads through the modules; writes only via: create/archive agent, archive skill,
save doc (guarded), open path, rescan cache."""
import os, sys, json, secrets, threading, webbrowser, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import scan, skills as SK, projects as PROJ, harness as HAR, usage, live as LIVE, host, drift as DR, gitops as GO, sessions as SESS
from .roster import Roster
from .docs import Docs
from .i18n import STRINGS

STATIC = os.path.join(os.path.dirname(__file__), "static")
_activity_refresh_lock = threading.Lock()   # non-blocking: skip a refresh already in flight, never queue one behind the request thread


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.data = scan.ensure(cfg)
        self.live = LIVE.get(cfg)
        self._roster = None; self._rows = None; self._items = None; self._t = 0
        self._skills = None; self._skills_t = 0

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
                rows = SK.load(self.cfg, self.data)
                for r in rows: r["tool"] = "claude"
                cx = self.data.get("codex", {})
                if cx.get("present"):
                    for r in SK.scan_dir(os.path.join(cx["home"], "skills"), "global"):
                        r["tool"] = "codex"; rows.append(r)
                p = os.path.join(self.cfg["state_dir"], "usage-skills.json")
                items, meta = usage.refresh(p, os.path.join(self.cfg["claude_home"], "projects"), "skills",
                                            {k: v for k, v in self.roots().items() if k != "global"})
                for r in rows:
                    u = usage.for_agent(items, r["name"], r["project"]); r["uses"] = u["total"]; r["last"] = u["last"]; r["uses_here"] = u["here"]
                self._skills = (rows, meta); self._skills_t = time.time()
            return self._skills

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
    def api_references(self, q):
        R, _, _ = self.roster()
        return {"references": R.references(q.get("name", [""])[0])}

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
    def api_archive_skill(self, b):
        R, _, _ = self.roster()
        refs = R.references(b["name"])
        if refs and not b.get("force"):
            return {"ok": False, "message": f"{len(refs)} file(s) reference {b['name']!r}", "references": refs}
        ok, msg = SK.archive_path(b["path"], b["project"], os.path.join(self.cfg["claude_home"], "_archive"))
        if ok: self.skills(fresh=True)
        return {"ok": ok, "message": msg, "references": refs}
    def api_save_doc(self, b):
        return self.docs().save(b["project"], b["rel"], b["content"], b["hash"], working=self.working())
    def api_open(self, b):
        ok, msg = host.open_path(os.path.expanduser(b["path"])); return {"ok": ok, "message": msg}
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
        return {"sessions": items, "days": days, "active_seconds": (self.cfg.get("live") or {}).get("active_seconds", 600)}

    def api_rescan(self, b):
        def go():
            d = scan.run(self.cfg); scan.save(self.cfg, d)
            with self.lock:
                self.data = d; self._roster = None
        threading.Thread(target=go, daemon=True).start()
        return {"ok": True, "message": "rescanning in the background"}


def make_handler(app):
    GETS = {"/api/agents": lambda q: app.api_agents(), "/api/skills": lambda q: app.api_skills(),
            "/api/projects": lambda q: app.api_projects(), "/api/harness": lambda q: app.api_harness(),
            "/api/live": lambda q: app.api_live(), "/api/docs": lambda q: app.api_docs(),
            "/api/doc": app.api_doc, "/api/references": app.api_references, "/api/in-repo": app.api_in_repo,
            "/api/activity": app.api_activity}
    POSTS = {"/api/archive": app.api_archive, "/api/create": app.api_create, "/api/archive-skill": app.api_archive_skill,
             "/api/save-doc": app.api_save_doc, "/api/open": app.api_open, "/api/focus": app.api_focus, "/api/rescan": app.api_rescan, "/api/commit": app.api_commit}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _json(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
                lang = app.cfg["language"] if app.cfg["language"] in STRINGS else "en"
                html = html.replace("__TOKEN__", app.token).replace("__LANG__", lang).replace("__HUB__", "0")
                b = html.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b); return
            fn = GETS.get(u.path)
            if not fn: return self._json({"error": "not found"}, 404)
            try: return self._json(fn(parse_qs(u.query)))
            except Exception as e: return self._json({"ok": False, "message": str(e)}, 500)
        def do_POST(self):
            if self.headers.get("X-Cabina-Token") != app.token:
                return self._json({"ok": False, "message": "invalid token"}, 403)
            n = int(self.headers.get("Content-Length", 0))
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except Exception: return self._json({"ok": False, "message": "invalid JSON"}, 400)
            fn = POSTS.get(urlparse(self.path).path)
            if not fn: return self._json({"error": "not found"}, 404)
            try: return self._json(fn(body))
            except KeyError as e: return self._json({"ok": False, "message": f"missing field {e}"}, 400)
            except Exception as e: return self._json({"ok": False, "message": str(e)}, 500)
    return H


def serve(cfg, port=None, open_browser=True):
    app = App(cfg)
    host_ = cfg["server"]["host"]; port = port or cfg["server"]["port"]
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
