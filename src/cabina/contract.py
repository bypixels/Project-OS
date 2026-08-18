"""Agent contract validation. One implementation shared by `check`, `agents` and the UI.

Categories:
    valid      meets everything
    warnings   has name+description; missing model/tools or inconsistent
    invalid    name not kebab-case / != filename / missing description
    document   .md without frontmatter — NOT an agent, do not "fix" it
    error      unreadable
Severity of each field comes from the config (contract.critical / contract.warn).
"""
import os, re, tomllib
from dataclasses import dataclass, field

# Per-tool contract defaults. Claude Code agents are Markdown with YAML frontmatter;
# Codex agents are TOML (name, description, developer_instructions) with no model/tools.
TOOL_DEFAULTS = {
    "claude": {},
    "codex": {"required": ["name", "description"], "critical": ["name", "description"], "warn": [],
              "known_fields": ["developer_instructions", "model", "model_reasoning_effort", "sandbox_mode", "approval_policy", "nickname_candidates"]},
}

_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class Result:
    name: str
    category: str
    critical: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    fields: dict = field(default_factory=dict)

    @property
    def is_agent(self):
        return self.category in ("valid", "warnings", "invalid")


class Contract:
    def __init__(self, cfg=None, tool="claude"):
        c = dict((cfg or {}).get("contract", {}) if cfg else {})
        c.update(TOOL_DEFAULTS.get(tool, {}))              # tool defaults win over the generic ones
        c.update((cfg or {}).get("contract", {}).get(tool, {}) if cfg else {})   # explicit per-tool config wins over all
        self.tool = tool
        self.required = tuple(c.get("required", ("name", "description", "model", "tools")))
        self.critical = set(c.get("critical", ("name", "description")))
        self.warn = set(c.get("warn", ("model", "tools")))
        self.models = tuple(c.get("models", ("sonnet", "opus", "haiku")))
        self.known = set(self.required) | set(c.get("known_fields", ("overrides", "maxTurns", "color", "version")))

    def _sev(self, fld):
        return "critical" if fld in self.critical else "warn"

    def validate_text(self, text, filename, shadows_global=False, fmt="md"):
        if fmt == "toml":
            try:
                fields = {k: (v if isinstance(v, str) else str(v)) for k, v in tomllib.loads(text).items()}
            except Exception as e:
                return Result(filename, "error", critical=[f"invalid TOML: {e}"])
            has_fm = True
        else:
            fields, has_fm = parse_frontmatter(text)
        if not has_fm:
            return Result(filename, "document", fields=fields)
        crit, warn = [], []
        add = lambda fld, msg: (crit if self._sev(fld) == "critical" else warn).append(msg)

        name = _clean(fields.get("name"))
        if "name" in self.required:
            if not name:
                add("name", "missing `name`")
            elif not _KEBAB.match(name):
                add("name", f"`name` is not kebab-case: {name!r}")
            elif name != filename:
                add("name", f"`name` ({name!r}) does not match the file ({filename!r})")
        if "description" in self.required and not _clean(fields.get("description")):
            add("description", "missing `description`")
        if "model" in self.required:
            model = _clean(fields.get("model"))
            if not model:
                add("model", "missing `model` (routing undeclared)")
            elif model not in self.models:
                add("model", f"unknown `model`: {model!r} (allowed: {', '.join(self.models)})")
        if "tools" in self.required:
            if "tools" not in fields:
                add("tools", "missing `tools` (no permission boundary declared)")
            elif not _clean(fields.get("tools")):
                add("tools", "`tools` is empty (use \"*\" for full access)")

        ov = _clean(fields.get("overrides"))
        if shadows_global and ov != "global" and not crit:
            warn.append("shadows a global agent with the same name without declaring `overrides: global`")
        if ov == "global" and not shadows_global:
            warn.append("declares `overrides: global` but shadows no global agent")
        if ov and ov != "global":
            warn.append(f"unknown `overrides` value: {ov!r}")
        foreign = sorted(set(fields) - self.known)
        if foreign:
            warn.append(f"fields Claude Code does not read: {', '.join(foreign)}")
        return Result(filename, categorize(crit, warn, False), crit, warn, fields)

    def validate_file(self, path, shadows_global=False):
        name, ext = os.path.splitext(os.path.basename(path))
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            return Result(name, "error", critical=[f"unreadable: {e}"])
        return self.validate_text(text, name, shadows_global, fmt="toml" if ext == ".toml" else "md")

    def validate_dir(self, agents_dir, global_names=frozenset()):
        out = []
        if not os.path.isdir(agents_dir):
            return out
        for f in sorted(os.listdir(agents_dir)):
            name, ext = os.path.splitext(f)
            if ext in (".md", ".toml"):
                out.append(self.validate_file(os.path.join(agents_dir, f), shadows_global=(name in global_names)))
        return out


def parse_agent_file(path):
    """(fields, body, has_frontmatter, fmt) for .md (frontmatter) or .toml agents."""
    ext = os.path.splitext(path)[1]
    text = open(path, encoding="utf-8", errors="replace").read()
    if ext == ".toml":
        try:
            d = tomllib.loads(text)
        except Exception:
            return {}, text, False, "toml"
        body = str(d.get("developer_instructions") or d.get("instructions") or "")
        return {k: (v if isinstance(v, str) else str(v)) for k, v in d.items()}, body, True, "toml"
    fields, has = parse_frontmatter(text)
    body = text[text.find("\n---", 3) + 4:] if has else text
    return fields, body, has, "md"


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, False
    end = text.find("\n---", 3)
    if end < 0:
        return {}, False
    fields = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields, True


def categorize(critical, warnings, is_document):
    if is_document:
        return "document"
    if critical:
        return "invalid"
    if warnings:
        return "warnings"
    return "valid"


def _clean(v):
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()
