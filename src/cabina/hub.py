"""cabina hub — lee N archivos de `cabina export --activity` de una carpeta compartida y sirve
la MISMA UI (static/index.html) sobre su mezcla. Read-only por diseño (R10): HubApp (definida
aquí también) no tiene NINGUNA ruta de escritura.

Known limitation: hardlinks to files outside DIR are not detected (no symlink to resolve); the
shared folder must be trusted at the filesystem level — this is a read-only viewer, not a
sandbox."""
import json, os, stat, threading, webbrowser, math

_AGENT_CATEGORIES = {"valid", "warnings", "invalid", "document"}
_AGENT_TOOLS = {"claude", "codex"}
_SKILL_STATES = {"ok", "no-frontmatter", "no-skill-md", "broken-link"}
_HARNESS_LEVELS = {"complete", "partial", "none"}
_TOKEN_FIELDS = ("in", "out", "cache_read", "cache_write")


def _text(value, default="", limit=500):
    return value[:limit] if isinstance(value, str) else default


def _enum(value, allowed, default):
    return value if isinstance(value, str) and value in allowed else default


def _number(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(n) or n < 0:
        return default
    return int(n) if n.is_integer() else n


def _list(value):
    """Accept only JSON arrays for sections consumed as row collections."""
    return value if isinstance(value, list) else []


def _boolean(value, default=False):
    return value if isinstance(value, bool) else default


def _texts(value, limit=100):
    if not isinstance(value, list):
        return []
    return [_text(item, limit=limit) for item in value if isinstance(item, str)]


def _count_map(value):
    if not isinstance(value, dict):
        return {}
    return {_text(k, limit=100): _number(v) for k, v in value.items() if isinstance(k, str)}


def _token_map(value):
    """Keep only the historical token counters; reasoning is never an export field."""
    if not isinstance(value, dict):
        return {}
    return {key: _number(value.get(key)) for key in _TOKEN_FIELDS if key in value}


def _safe_dict(value):
    if not isinstance(value, dict):
        return {}
    return {"CLAUDE.md": _boolean(value.get("CLAUDE.md")),
            "HARNESS.md": _boolean(value.get("HARNESS.md")),
            "MEMORY.md": _boolean(value.get("MEMORY.md")),
            "PROGRESS.md": _boolean(value.get("PROGRESS.md"))}


def _agent_row(row, machine):
    if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
        return None
    return {"name": _text(row["name"], limit=120), "project": _text(row.get("project"), limit=120),
            "tool": _enum(row.get("tool"), _AGENT_TOOLS, "claude"),
            "category": _enum(row.get("category"), _AGENT_CATEGORIES, "document"),
            "model": _text(row.get("model"), limit=120), "tools": _text(row.get("tools"), limit=300),
            "description": _text(row.get("description") or row.get("desc"), limit=300),
            "desc": _text(row.get("desc") or row.get("description"), limit=300),
            "uses": _number(row.get("uses")), "uses_here": _number(row.get("uses_here")),
            "last": _text(row.get("last"), limit=80), "critical": _texts(row.get("critical")),
            "warnings": _texts(row.get("warnings")), "attributed": _boolean(row.get("attributed"), True),
            "homonyms": _number(row.get("homonyms")), "is_agent": _boolean(row.get("is_agent"), True),
            "path": "", "machine": machine}


def _skill_row(row, machine):
    if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
        return None
    return {"name": _text(row["name"], limit=120), "project": _text(row.get("project"), limit=120),
            "tool": _enum(row.get("tool"), _AGENT_TOOLS, "claude"),
            "state": _enum(row.get("state"), _SKILL_STATES, "no-frontmatter"),
            "symlink": _boolean(row.get("symlink")), "target": "", "path": "",
            "desc": _text(row.get("desc"), limit=300), "lines": _number(row.get("lines")),
            "uses": _number(row.get("uses")), "uses_here": _number(row.get("uses_here")),
            "last": _text(row.get("last"), limit=80), "machine": machine}


def _harness_row(row, machine):
    if not isinstance(row, dict):
        return None
    name = row.get("project") or row.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return {"project": _text(name, limit=120), "level": _enum(row.get("level"), _HARNESS_LEVELS, "none"),
            "hooks_dead": _texts(row.get("hooks_dead")), "hooks_broken": _texts(row.get("hooks_broken")),
            "machine": machine}


def _project_detail_row(row, machine):
    if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
        return None
    return {"name": _text(row["name"], limit=120), "branch": _text(row.get("branch"), limit=200),
            "dirty": _number(row.get("dirty")), "worktrees": _number(row.get("worktrees")),
            "docs": _safe_dict(row.get("docs")), "memory_days": _number(row.get("memory_days"), None),
            "last_commit": _text(row.get("last_commit"), limit=300), "agents": _number(row.get("agents")),
            "skills": _number(row.get("skills")), "machine": machine}


def _activity_aggregated_row(row, machine):
    if not isinstance(row, dict) or not isinstance(row.get("project"), str) or not row["project"].strip():
        return None
    return {"project": _text(row["project"], limit=120), "sessions": _number(row.get("sessions")),
            "hours": _number(row.get("hours")), "tokens": _token_map(row.get("tokens")),
            "commits": _number(row.get("commits")), "files_touched": _number(row.get("files_touched")),
            "tool_calls": _count_map(row.get("tool_calls")), "agents": _count_map(row.get("agents")),
            "skills": _count_map(row.get("skills")), "machine": machine}


def _activity_session_row(row, machine):
    if not isinstance(row, dict) or not isinstance(row.get("project"), str) or not row["project"].strip():
        return None
    return {"project": _text(row["project"], limit=120), "started": _text(row.get("started"), limit=80),
            "ended": _text(row.get("ended"), limit=80), "duration_s": _number(row.get("duration_s")),
            "turns": _number(row.get("turns")), "commits": _number(row.get("commits")),
            "branch": _text(row.get("branch"), limit=200), "files_touched": _texts(row.get("files_touched"), 300),
            "files_outside": _number(row.get("files_outside")), "agents": _count_map(row.get("agents")),
            "skills": _count_map(row.get("skills")), "tokens": _token_map(row.get("tokens")),
            "subagents": _number(row.get("subagents")), "title": _text(row.get("title"), limit=300),
            "machine": machine}


def _confined(real_path, real_dir):
    """Guard (R10): una ruta resuelta cuenta como 'adentro' de real_dir solo si es igual o cae
    bajo él. Aislado como función propia (no inline) para que un break-test pueda desactivarlo
    sin tocar os.path.realpath en sí.

    Known limitation: hardlinks to files outside DIR are not detected (no symlink to resolve);
    the shared folder must be trusted at the filesystem level — this is a read-only viewer, not
    a sandbox."""
    return real_path == real_dir or real_path.startswith(real_dir + os.sep)


def _is_regular_file(path):
    """Guard (D1): True only if path is a regular file. A FIFO named `*.json` under DIR would
    otherwise block forever inside `open()` (`_read_export`) — and since every hub endpoint
    calls `load_dir`, that hang takes down the whole hub. Aislado (no inline) por la misma razón
    que `_confined`/`_over_cap`: un break-test puede desactivarlo sin tocar os.stat en sí. Any
    error probing the path (e.g. it vanished) counts as "not a regular file", never as "trust it"."""
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except OSError:
        return False


def _over_cap(path, max_mb):
    """Guard: True si path pesa más de max_mb MB. Aislado (no inline) por la misma razón que
    `_confined`: un break-test puede desactivarlo sin tocar os.path.getsize en sí. Un error al
    medir el tamaño (p. ej. el archivo desapareció) no cuenta como "demasiado grande" — cae en
    `_read_export`, que sí lo marca "unreadable"."""
    try:
        return os.path.getsize(path) > max_mb * 1024 * 1024
    except OSError:
        return False


def _read_export(path):
    """Parsea UN archivo de export. Aislado para que un break-test pueda forzarlo a lanzar y
    confirmar que el try/except por archivo alrededor de esta llamada (en load_dir) es lo que
    evita que un export roto tumbe a los demás — no una coincidencia de que hoy nadie lo rompió."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_dir(dir_, max_mb=5):
    """Archivos *.json DIRECTAMENTE bajo dir_ (no recursivo). Cada archivo: confinado por
    realpath a dir_ (un symlink que escapa -> status "outside"), debe ser un archivo regular (un
    FIFO/directorio/socket -> "not-a-file", D1: evita que open() se cuelgue para siempre),
    tope de tamaño max_mb MB (-> "too-large"), json.loads envuelto por archivo (-> "unreadable").
    Un archivo malo nunca aborta a los demás. Devuelve {files: [...], merged: {agents, skills,
    projects, harness, activity}}."""
    real_dir = os.path.realpath(dir_)
    files, agents, skills, harness = [], [], [], []
    projects_set, agg_by_key, detail_rows, projects_detail = set(), {}, [], []
    if os.path.isdir(dir_):
        for name in sorted(os.listdir(dir_)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(dir_, name)
            entry = {"name": name, "machine": None, "os": None, "when": None, "status": "ok"}
            real_path = os.path.realpath(path)
            if not _confined(real_path, real_dir):
                entry["status"] = "outside"; files.append(entry); continue
            if not _is_regular_file(real_path):
                entry["status"] = "not-a-file"; files.append(entry); continue
            if _over_cap(real_path, max_mb):
                entry["status"] = "too-large"; files.append(entry); continue
            try:
                d = _read_export(real_path)
                if not isinstance(d, dict):
                    raise ValueError("export root must be an object")
            except Exception as e:
                entry["status"] = "unreadable"; entry["error"] = str(e); files.append(entry); continue
            machine = _text(d.get("machine"), name)
            entry["machine"], entry["os"], entry["when"] = machine, _text(d.get("os"), limit=80), _text(d.get("when"), limit=80)
            files.append(entry)
            for a in _list(d.get("agents")):
                clean = _agent_row(a, machine)
                if clean: agents.append(clean)
            for s in _list(d.get("skills")):
                clean = _skill_row(s, machine)
                if clean: skills.append(clean)
            for h in _list(d.get("harness")):
                clean = _harness_row(h, machine)
                if clean: harness.append(clean)
            for p in _list(d.get("projects")):
                if isinstance(p, str) and p.strip(): projects_set.add(_text(p, limit=120))
            for pd in _list(d.get("projects_detail")):
                clean = _project_detail_row(pd, machine)
                if clean: projects_detail.append(clean)
            act = d.get("activity") if isinstance(d.get("activity"), dict) else {}
            for row in _list(act.get("aggregated")):
                clean = _activity_aggregated_row(row, machine)
                if clean: agg_by_key[(clean["project"], machine)] = clean
            for row in _list(act.get("sessions")):
                clean = _activity_session_row(row, machine)
                if clean: detail_rows.append(clean)
    # Orchestrator amendment: always carry BOTH aggregated and per-session detail — a file that
    # ships one shape must never push another file's rows of the other shape out of the merge.
    activity = {"aggregated": list(agg_by_key.values()), "sessions": detail_rows}
    merged = {"agents": agents, "skills": skills, "projects": sorted(projects_set),
              "projects_detail": projects_detail, "harness": harness, "activity": activity}
    return {"files": files, "merged": merged}


from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import server as SRV
from .i18n import STRINGS

STATIC = os.path.join(os.path.dirname(__file__), "static")


class HubApp:
    """Sin diccionario POSTS, sin métodos api_archive/api_create/api_save_doc/api_commit/
    api_open/api_focus/api_rescan en ninguna parte de esta clase — la AUSENCIA es la guardia (R10)."""
    def __init__(self, dir_, cfg):
        self.dir = dir_
        self.max_mb = (cfg.get("hub") or {}).get("max_file_mb", 5)
        self.lang = cfg["language"] if cfg.get("language") in STRINGS else "en"
        self._cache_key = None
        self._cache_val = None

    def _fingerprint(self):
        """(name, mtime_ns, size) per *.json entry under self.dir — cheap enough to compute on
        every request, and any change to it means an export was added, removed or rewritten."""
        try:
            names = sorted(n for n in os.listdir(self.dir) if n.endswith(".json"))
        except OSError:
            return ()
        key = []
        for n in names:
            try:
                st = os.stat(os.path.join(self.dir, n))
                key.append((n, st.st_mtime_ns, st.st_size))
            except OSError:
                key.append((n, None, None))
        return tuple(key)

    def _merged(self):
        """Perf: skip re-reading and re-merging every export on every request when DIR hasn't
        changed since the last call — the fingerprint is the cache key."""
        key = self._fingerprint()
        if self._cache_val is not None and key == self._cache_key:
            return self._cache_val
        self._cache_val = load_dir(self.dir, self.max_mb)
        self._cache_key = key
        return self._cache_val

    def api_hub(self, q=None):
        return {"files": self._merged()["files"]}

    def api_agents(self, q=None):
        m = self._merged()["merged"]
        return {"agents": m["agents"], "projects": m["projects"], "window": None, "codex_present": False}

    def api_skills(self, q=None):
        return {"skills": self._merged()["merged"]["skills"], "window": None}

    def api_projects(self, q=None):
        # projects_detail carries only the whitelisted export fields (never "path", local-only
        # like cwd/source_path) — fields the UI's renderProjects/renderProjDetail also read but
        # that never leave a machine get a safe default here so a hub row never throws.
        defaults = {"exists": True, "git": True, "path": "", "commands": 0, "rules": 0, "hooks": 0,
                    "workflows": 0, "worktrees_mb": 0, "worktrees_detail": []}
        rows = [{**defaults, **p} for p in self._merged()["merged"]["projects_detail"]]
        return {"projects": rows}

    def api_harness(self, q=None):
        # snapshot.export()'s harness rows carry `project` (not `name`) and only {level,
        # hooks_dead, hooks_broken} — renderHarness/renderHarDetail also read hooks_active,
        # hooks, missing, hooks_helpers, memory_days, runlog, has, path, rules, workflows,
        # none of which a hub row exports. Without `name` a click never resolved its detail
        # (silent no-op); the rest default here so a hub row never throws.
        m = self._merged()["merged"]
        defaults = {"hooks_active": [], "hooks": [], "missing": [], "hooks_helpers": [],
                    "memory_days": None, "runlog": False, "has": {}, "path": "", "rules": 0,
                    "workflows": 0}
        states = [{**defaults, **h, "name": h.get("name") or h.get("project")} for h in m["harness"]]
        return {"states": states, "runlogs": [], "drift": {"codex_present": False}}

    def api_activity(self, q=None):
        act = self._merged()["merged"]["activity"]
        return {"aggregated": act.get("aggregated") or [], "sessions": act.get("sessions") or [], "active_seconds": None}


def make_hub_handler(app):
    GETS = {"/api/hub": app.api_hub, "/api/agents": app.api_agents, "/api/skills": app.api_skills,
            "/api/projects": app.api_projects, "/api/harness": app.api_harness, "/api/activity": app.api_activity}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _json(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            # Anti-DNS-rebinding (same guard as server.py): the hub binds 127.0.0.1 unconditionally
            # (see serve_hub below), so only loopback Host headers are ever accepted here.
            if not SRV.host_allowed(self.headers.get("Host"), "127.0.0.1"):
                return self._json({"ok": False, "message": "bad host"}, 421)
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
                html = html.replace("__TOKEN__", "").replace("__LANG__", app.lang).replace("__HUB__", "1")
                b = html.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b); return
            fn = GETS.get(u.path)
            if not fn: return self._json({"error": "not found"}, 404)
            try: return self._json(fn(parse_qs(u.query)))
            except Exception as e: return self._json({"ok": False, "message": str(e)}, 500)
        def do_POST(self):
            if not SRV.host_allowed(self.headers.get("Host"), "127.0.0.1"):
                return self._json({"ok": False, "message": "bad host"}, 421)
            return self._json({"ok": False, "message": "cabina hub is read-only: no write route exists"}, 405)
    return H


def serve_hub(dir_, cfg, port=None, open_browser=True):
    app = HubApp(dir_, cfg)
    port = port or cfg["server"]["port"]
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_hub_handler(app))   # 127.0.0.1 fijo (R10) — nunca cfg["server"]["host"]
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"cabina hub (read-only) at {url}  — {dir_}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return srv
