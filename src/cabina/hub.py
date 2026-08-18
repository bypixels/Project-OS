"""cabina hub — lee N archivos de `cabina export --activity` de una carpeta compartida y sirve
la MISMA UI (static/index.html) sobre su mezcla. Read-only por diseño (R10): HubApp (definida
aquí también) no tiene NINGUNA ruta de escritura."""
import json, os


def _confined(real_path, real_dir):
    """Guard (R10): una ruta resuelta cuenta como 'adentro' de real_dir solo si es igual o cae
    bajo él. Aislado como función propia (no inline) para que un break-test pueda desactivarlo
    sin tocar os.path.realpath en sí."""
    return real_path == real_dir or real_path.startswith(real_dir + os.sep)


def load_dir(dir_, max_mb=5):
    """Archivos *.json DIRECTAMENTE bajo dir_ (no recursivo). Cada archivo: confinado por
    realpath a dir_ (un symlink que escapa -> status "outside"), tope de tamaño max_mb MB (->
    "too-large"), json.loads envuelto por archivo (-> "unreadable"). Un archivo malo nunca
    aborta a los demás. Devuelve {files: [...], merged: {agents, skills, projects, harness,
    activity}}."""
    real_dir = os.path.realpath(dir_)
    files, agents, skills, harness = [], [], [], []
    projects_set, agg_by_key, detail_rows, has_detail = set(), {}, [], False
    if os.path.isdir(dir_):
        for name in sorted(os.listdir(dir_)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(dir_, name)
            entry = {"name": name, "machine": None, "os": None, "when": None, "status": "ok"}
            real_path = os.path.realpath(path)
            if not _confined(real_path, real_dir):
                entry["status"] = "outside"; files.append(entry); continue
            try:
                size = os.path.getsize(real_path)
            except OSError as e:
                entry["status"] = "unreadable"; entry["error"] = str(e); files.append(entry); continue
            if size > max_mb * 1024 * 1024:
                entry["status"] = "too-large"; files.append(entry); continue
            try:
                with open(real_path, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception as e:
                entry["status"] = "unreadable"; entry["error"] = str(e); files.append(entry); continue
            machine = d.get("machine") or name
            entry["machine"], entry["os"], entry["when"] = machine, d.get("os"), d.get("when")
            files.append(entry)
            for a in d.get("agents") or []: agents.append({**a, "machine": machine})
            for s in d.get("skills") or []: skills.append({**s, "machine": machine})
            for h in d.get("harness") or []: harness.append({**h, "machine": machine})
            for p in d.get("projects") or []: projects_set.add(p)
            act = d.get("activity") or {}
            for row in act.get("aggregated") or []:
                agg_by_key[(row.get("project"), machine)] = {**row, "machine": machine}
            if act.get("sessions"):
                has_detail = True
                for row in act["sessions"]: detail_rows.append({**row, "machine": machine})
    activity = {"sessions": detail_rows} if has_detail else {"aggregated": list(agg_by_key.values())}
    merged = {"agents": agents, "skills": skills, "projects": sorted(projects_set), "harness": harness, "activity": activity}
    return {"files": files, "merged": merged}
