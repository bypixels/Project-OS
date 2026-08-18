"""Agent roster: load (validated + usage), references, create, archive.
Writes: create (ONE new file, only if it meets the contract) and archive (moves ONE file)."""
import os, re, shutil, subprocess
from datetime import date
from . import scan, usage
from .contract import Contract

HOME = os.path.expanduser("~")


class Roster:
    def __init__(self, cfg, data=None):
        self.cfg = cfg
        self.data = data or scan.ensure(cfg)
        self.contract = Contract(cfg)
        self.global_dir = os.path.join(cfg["claude_home"], "agents")
        self.roots = scan.project_roots(cfg, self.data)
        self.usage_path = os.path.join(cfg["state_dir"], "usage-agents.json")
        self.history = os.path.join(cfg["claude_home"], "projects")

    def agent_dirs(self):
        out = [("global", self.global_dir)]
        for p in self.data.get("projects", []):
            d = os.path.join(p["path"], ".claude", "agents")
            if os.path.isdir(d):
                out.append((p["name"], d))
        return out

    def load(self, refresh_usage=True):
        """[(project, Result, path)], usage items"""
        glob = self.contract.validate_dir(self.global_dir)
        gnames = frozenset(r.name for r in glob if r.is_agent)
        rows = [("global", r, os.path.join(self.global_dir, r.name + ".md")) for r in glob]
        for proj, d in self.agent_dirs()[1:]:
            for r in self.contract.validate_dir(d, gnames):
                rows.append((proj, r, os.path.join(d, r.name + ".md")))
        roots = {k: v for k, v in self.roots.items() if k != "global"}
        items = usage.refresh(self.usage_path, self.history, "agents", roots)[0] if refresh_usage else usage.load(self.usage_path)
        return rows, items

    @staticmethod
    def homonyms(rows):
        h = {}
        for _, r, _ in rows:
            if r.is_agent:
                h[r.name] = h.get(r.name, 0) + 1
        return h

    def references(self, name):
        """Files (.md) mentioning `name` as an agent/skill, outside its own file. grep-based (fast)."""
        esc = re.escape(name)
        pat = (rf"`{esc}`|agent `?{esc}`?|agente `?{esc}`?|subagent_type[\"':= ]+{esc}\b"
               rf"|Agent\([^)]*{esc}|^[[:space:]]*-[[:space:]]+{esc}[[:space:]]*$")
        ch = self.cfg["claude_home"]
        paths = [os.path.join(ch, "CLAUDE.md"), os.path.join(ch, "rules"), os.path.join(ch, "commands"), os.path.join(ch, "agents")]
        for proj, d in self.agent_dirs()[1:]:
            base = os.path.dirname(d)
            paths += [os.path.join(base, x) for x in ("agents", "commands", "rules", "workflows")]
            if os.path.isdir(base):
                paths += [os.path.join(base, f) for f in os.listdir(base) if f.endswith(".md")]
            paths.append(os.path.join(os.path.dirname(base), "CLAUDE.md"))
        paths = [p for p in dict.fromkeys(paths) if os.path.exists(p)]
        if not paths:
            return []
        if shutil.which("grep"):
            try:
                r = subprocess.run(["grep", "-rlE", "--include=*.md", "--exclude-dir=worktrees", "--exclude-dir=_archive",
                                    "--exclude-dir=node_modules", pat, *paths], capture_output=True, text=True, timeout=30)
                if r.returncode in (0, 1):     # 1 = no matches; anything else = grep failed -> fall through
                    return sorted(set(h for h in r.stdout.splitlines() if os.path.basename(h) != name + ".md"))
            except Exception:
                pass
        # Python fallback (Windows, or grep missing). Same patterns, compiled once.
        rx = re.compile(pat.replace("[[:space:]]", r"\s"), re.M)
        hits = set()
        for base in paths:
            files = [base] if os.path.isfile(base) else [
                os.path.join(dp, f) for dp, dn, fn in os.walk(base)
                if not any(x in dp for x in ("worktrees", "_archive", "node_modules")) for f in fn if f.endswith(".md")]
            for f in files:
                if os.path.basename(f) == name + ".md":
                    continue
                try:
                    if rx.search(open(f, encoding="utf-8", errors="replace").read()):
                        hits.add(f)
                except Exception:
                    pass
        return sorted(hits)

    def archive(self, name, project, force=False):
        rows, _ = self.load(refresh_usage=False)
        hit = [(p, r, path) for p, r, path in rows if r.name == name and p.lower() == project.lower()]
        if not hit:
            return False, f"no {name!r} in {project}", []
        proj, r, path = hit[0]
        refs = self.references(name)
        if refs and not force:
            return False, f"{len(refs)} file(s) reference {name!r}", refs
        dest_dir = os.path.join(self.cfg["claude_home"], "_archive", date.today().isoformat(), "agents", proj)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name + ".md")
        shutil.move(path, dest)
        items = usage.load(self.usage_path)
        items.setdefault(name, {"last": None, "n_total": 0})["archived"] = date.today().isoformat()
        usage.save(self.usage_path, items, {"updated": date.today().isoformat()})
        return True, f"archived to {dest}", refs

    def create(self, project, name, description, model, tools, body):
        if project not in self.roots:
            return False, f"unknown project: {project}", None
        dest = self.global_dir if project == "global" else os.path.join(self.roots[project], ".claude", "agents")
        if not os.path.isdir(dest):
            return False, f"missing directory: {dest}", None
        path = os.path.join(dest, f"{name}.md")
        if os.path.exists(path):
            return False, f"{name}.md already exists in {project}", None
        gnames = {f[:-3] for f in os.listdir(self.global_dir) if f.endswith(".md")} if os.path.isdir(self.global_dir) else set()
        shadows = project != "global" and name in gnames
        t = tools.strip()
        t = '"*"' if t == "*" else t
        fm = [f"name: {name}", f"description: {description.strip()}", f"model: {model.strip()}", f"tools: {t}"]
        if shadows:
            fm.append("overrides: global")
        text = "---\n" + "\n".join(fm) + "\n---\n\n" + body.strip() + "\n"
        r = self.contract.validate_text(text, name, shadows_global=shadows)
        if r.category != "valid":
            return False, "contract not met: " + "; ".join(r.critical + r.warnings), None
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return True, f"created {path}", path
