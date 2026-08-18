"""Drift between the Claude Code and Codex environments. Read-only.
Same content copied by hand into two tools diverges silently; these detectors make it visible."""
import os, re, difflib
from .contract import parse_agent_file

_TOOL_LINE = re.compile(r"(claude|codex|anthropic|openai|claude\.ai|CLAUDE\.md|AGENTS\.md)", re.I)


def _norm(t):
    return re.sub(r"\s+", " ", t or "").strip().lower()


def _agents(d):
    out = {}
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        n, ext = os.path.splitext(f)
        if ext in (".md", ".toml"):
            try:
                fields, body, has, fmt = parse_agent_file(os.path.join(d, f))
            except Exception:
                continue
            if has:
                out[n] = {"body": body, "desc": fields.get("description", ""), "path": os.path.join(d, f)}
    return out


def twin_agents(claude_agents_dir, codex_agents_dir, threshold=0.9):
    """Agents present in both tools by name; compare instruction bodies."""
    a, b = _agents(claude_agents_dir), _agents(codex_agents_dir)
    out = []
    for n in sorted(set(a) & set(b)):
        ratio = difflib.SequenceMatcher(None, _norm(a[n]["body"]), _norm(b[n]["body"])).ratio()
        out.append({"name": n, "similarity": round(ratio, 3), "status": "same" if ratio >= threshold else "diverged",
                    "claude": a[n]["path"], "codex": b[n]["path"]})
    return out


def rules_file(project_root):
    """CLAUDE.md vs AGENTS.md in a project root.
    linked: AGENTS.md is a symlink to CLAUDE.md (ideal) · copy: identical except tool-name lines ·
    bridge: a short AGENTS.md that explicitly points at CLAUDE.md as canonical (deliberate) ·
    diverged: real content differs · missing: no AGENTS.md · only-agents: AGENTS.md without CLAUDE.md"""
    c = os.path.join(project_root, "CLAUDE.md"); a = os.path.join(project_root, "AGENTS.md")
    if not os.path.lexists(a):
        return {"status": "missing"}
    if os.path.islink(a):
        target = os.path.realpath(a)
        if os.path.isfile(c) and os.path.exists(target) and os.path.samefile(target, c):
            return {"status": "linked"}
        return {"status": "broken-link"}
    if not os.path.isfile(c):
        return {"status": "only-agents"}
    try:
        ta = open(a, encoding="utf-8", errors="replace").read().splitlines()
        tc = open(c, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return {"status": "unreadable"}
    fa = [l for l in ta if not _TOOL_LINE.search(l)]; fc = [l for l in tc if not _TOOL_LINE.search(l)]
    if fa == fc:
        return {"status": "copy"}
    # A short AGENTS.md that points at CLAUDE.md as canonical is a deliberate bridge, not drift.
    if len(ta) < len(tc) and any("CLAUDE.md" in l for l in ta):
        return {"status": "bridge"}
    diff = list(difflib.unified_diff(tc, ta, "CLAUDE.md", "AGENTS.md", lineterm="", n=0))
    return {"status": "diverged", "diff_lines": len([l for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---")]),
            "diff": "\n".join(diff[:40])}


def skill_copies(codex_skills_dir, sources):
    """Codex skills that also exist (by name) in a source dir (~/.agents/skills, ~/.claude/skills)."""
    out = []
    if not os.path.isdir(codex_skills_dir):
        return out
    for n in sorted(os.listdir(codex_skills_dir)):
        cp = os.path.join(codex_skills_dir, n, "SKILL.md")
        if not os.path.isfile(cp):
            continue
        for src in sources:
            sp = os.path.join(src, n, "SKILL.md")
            if os.path.isfile(sp):
                try:
                    same = open(cp, "rb").read() == open(sp, "rb").read()
                except Exception:
                    same = False
                out.append({"name": n, "status": "same" if same else "diverged", "codex": cp, "source": sp,
                            "linked": os.path.islink(os.path.join(codex_skills_dir, n))})
                break
    return out


def report(cfg, data):
    """All drift findings for the environment."""
    ch, cx = cfg["claude_home"], cfg.get("codex_home") or ""
    out = {"codex_present": os.path.isdir(cx), "twins": [], "rules": [], "skills": []}
    if not out["codex_present"]:
        return out
    out["twins"] = twin_agents(os.path.join(ch, "agents"), os.path.join(cx, "agents"))
    for p in data.get("projects", []):
        r = rules_file(p["path"]); r["project"] = p["name"]; r["path"] = p["path"]
        if r["status"] != "missing":
            out["rules"].append(r)
    agents_skills = os.path.join(os.path.dirname(ch), ".agents", "skills")
    out["skills"] = skill_copies(os.path.join(cx, "skills"), [agents_skills, os.path.join(ch, "skills")])
    return out
