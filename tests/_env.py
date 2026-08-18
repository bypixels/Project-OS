"""A synthetic Claude Code environment in a temp dir: global + one project, for server tests."""
import os, json, tempfile
import _helpers  # noqa
from cabina import config as CFG

AGENT = "---\nname: {n}\ndescription: Reviews things carefully\nmodel: sonnet\ntools: Read, Grep\n---\nBody.\n"

class Env:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(); t = self.tmp.name
        self.claude = os.path.join(t, "claude"); self.projects = os.path.join(t, "work"); self.state = os.path.join(t, "state")
        os.makedirs(os.path.join(self.claude, "agents")); os.makedirs(os.path.join(self.claude, "skills", "gsk")); os.makedirs(os.path.join(self.claude, "projects", "-x"))
        open(os.path.join(self.claude, "agents", "reviewer.md"), "w").write(AGENT.format(n="reviewer"))
        open(os.path.join(self.claude, "skills", "gsk", "SKILL.md"), "w").write("---\nname: gsk\ndescription: g\n---\n")
        open(os.path.join(self.claude, "CLAUDE.md"), "w").write("# global\n")
        # project alpha: an agent that shadows the global one, a doc, a hook wired + one dead
        a = os.path.join(self.projects, "alpha"); c = os.path.join(a, ".claude")
        os.makedirs(os.path.join(c, "agents")); os.makedirs(os.path.join(c, "skills", "deploy")); os.makedirs(os.path.join(c, "hooks"))
        open(os.path.join(c, "agents", "reviewer.md"), "w").write(AGENT.format(n="reviewer"))
        open(os.path.join(c, "agents", "guide.md"), "w").write("# Just a guide\n")
        open(os.path.join(c, "skills", "deploy", "SKILL.md"), "w").write("---\nname: deploy\ndescription: d\n---\n")
        open(os.path.join(c, "hooks", "ok.sh"), "w").write("#!/bin/sh"); open(os.path.join(c, "hooks", "dead.sh"), "w").write("#!/bin/sh")
        json.dump({"hooks": {"Stop": [{"hooks": [{"command": "$CLAUDE_PROJECT_DIR/.claude/hooks/ok.sh"}]}]}}, open(os.path.join(c, "settings.json"), "w"))
        open(os.path.join(c, "MEMORY.md"), "w").write("# mem\n"); open(os.path.join(a, "CLAUDE.md"), "w").write("# alpha\n")
        # history: two invocations of reviewer from alpha, one from elsewhere
        open(os.path.join(self.claude, "projects", "-x", "s.jsonl"), "w").write(
            f'{{"timestamp":"2026-08-01T00:00:00Z","cwd":"{a}/apps","x":{{"subagent_type":"reviewer"}}}}\n'
            f'{{"timestamp":"2026-08-02T00:00:00Z","cwd":"{a}","x":{{"subagent_type":"reviewer"}}}}\n'
            f'{{"timestamp":"2026-08-03T00:00:00Z","cwd":"/elsewhere","x":{{"subagent_type":"reviewer"}}}}\n'
            f'{{"timestamp":"2026-08-03T00:00:00Z","cwd":"{a}","x":{{"name":"Skill","input":{{"skill":"deploy"}}}}}}\n')
        # synthetic Codex home: one twin agent (same as claude reviewer), one copied skill
        self.codex = os.path.join(t, "codex"); os.makedirs(os.path.join(self.codex, "agents")); os.makedirs(os.path.join(self.codex, "skills", "gsk"))
        open(os.path.join(self.codex, "agents", "reviewer.toml"), "w").write('name = "reviewer"\ndescription = "Reviews things carefully"\ndeveloper_instructions = "Body."\n')
        open(os.path.join(self.codex, "skills", "gsk", "SKILL.md"), "w").write("---\nname: gsk\ndescription: g\n---\n")
        os.makedirs(os.path.join(self.codex, "sessions", "2026", "08"))
        open(os.path.join(self.codex, "sessions", "2026", "08", "r.jsonl"), "w").write(f'{{"timestamp":"2026-08-04T00:00:00Z","type":"session_meta","payload":{{"cwd":"{a}"}}}}\n')
        open(os.path.join(a, "AGENTS.md"), "w").write("# AGENTS.md\nThis file provides guidance to Codex.\n")   # a copy, not a link
        self.cfg = CFG._merge(CFG.DEFAULTS, {"claude_home": self.claude, "codex_home": self.codex, "roots": [self.projects], "state_dir": self.state,
                                             "live": {"provider": "none"}, "scan": {"measure_worktrees": False, "check_mcp": False}})
        self.alpha = a
    def cleanup(self): self.tmp.cleanup()
