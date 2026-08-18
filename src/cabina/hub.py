"""cabina hub — lee N archivos de `cabina export --activity` de una carpeta compartida y sirve
la MISMA UI (static/index.html) sobre su mezcla. Read-only por diseño (R10): HubApp (definida
aquí también) no tiene NINGUNA ruta de escritura."""
import json, os, threading, webbrowser


def _confined(real_path, real_dir):
    """Guard (R10): una ruta resuelta cuenta como 'adentro' de real_dir solo si es igual o cae
    bajo él. Aislado como función propia (no inline) para que un break-test pueda desactivarlo
    sin tocar os.path.realpath en sí."""
    return real_path == real_dir or real_path.startswith(real_dir + os.sep)


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
    realpath a dir_ (un symlink que escapa -> status "outside"), tope de tamaño max_mb MB (->
    "too-large"), json.loads envuelto por archivo (-> "unreadable"). Un archivo malo nunca
    aborta a los demás. Devuelve {files: [...], merged: {agents, skills, projects, harness,
    activity}}."""
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
            if _over_cap(real_path, max_mb):
                entry["status"] = "too-large"; files.append(entry); continue
            try:
                d = _read_export(real_path)
            except Exception as e:
                entry["status"] = "unreadable"; entry["error"] = str(e); files.append(entry); continue
            machine = d.get("machine") or name
            entry["machine"], entry["os"], entry["when"] = machine, d.get("os"), d.get("when")
            files.append(entry)
            for a in d.get("agents") or []: agents.append({**a, "machine": machine})
            for s in d.get("skills") or []: skills.append({**s, "machine": machine})
            for h in d.get("harness") or []: harness.append({**h, "machine": machine})
            for p in d.get("projects") or []: projects_set.add(p)
            for pd in d.get("projects_detail") or []:
                projects_detail.append({**pd, "machine": machine})
            act = d.get("activity") or {}
            for row in act.get("aggregated") or []:
                agg_by_key[(row.get("project"), machine)] = {**row, "machine": machine}
            for row in act.get("sessions") or []:
                detail_rows.append({**row, "machine": machine})
    # Orchestrator amendment: always carry BOTH aggregated and per-session detail — a file that
    # ships one shape must never push another file's rows of the other shape out of the merge.
    activity = {"aggregated": list(agg_by_key.values()), "sessions": detail_rows}
    merged = {"agents": agents, "skills": skills, "projects": sorted(projects_set),
              "projects_detail": projects_detail, "harness": harness, "activity": activity}
    return {"files": files, "merged": merged}


from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from .i18n import STRINGS

STATIC = os.path.join(os.path.dirname(__file__), "static")


class HubApp:
    """Sin diccionario POSTS, sin métodos api_archive/api_create/api_save_doc/api_commit/
    api_open/api_focus/api_rescan en ninguna parte de esta clase — la AUSENCIA es la guardia (R10)."""
    def __init__(self, dir_, cfg):
        self.dir = dir_
        self.max_mb = (cfg.get("hub") or {}).get("max_file_mb", 5)
        self.lang = cfg["language"] if cfg.get("language") in STRINGS else "en"

    def _merged(self):
        return load_dir(self.dir, self.max_mb)

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
        m = self._merged()["merged"]
        return {"states": m["harness"], "runlogs": [], "drift": {"codex_present": False}}

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
