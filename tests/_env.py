"""A synthetic Claude Code environment in a temp dir: global + one project, for server tests."""
import os, json, tempfile, time
import _helpers  # noqa
from project_os import config as CFG

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
        self.usage_history_file = os.path.join(self.claude, "projects", "-x", "s.jsonl")
        open(self.usage_history_file, "w").write(
            f'{{"timestamp":"2026-08-01T00:00:00Z","cwd":"{a}/apps","x":{{"subagent_type":"reviewer"}}}}\n'
            f'{{"timestamp":"2026-08-02T00:00:00Z","cwd":"{a}","x":{{"subagent_type":"reviewer"}}}}\n'
            f'{{"timestamp":"2026-08-03T00:00:00Z","cwd":"/elsewhere","x":{{"subagent_type":"reviewer"}}}}\n'
            f'{{"timestamp":"2026-08-03T00:00:00Z","cwd":"{a}","x":{{"name":"Skill","input":{{"skill":"deploy"}}}}}}\n')
        # a nested invocation inside a subagent's own transcript — the recursive scan of
        # usage.py's history_dir must still find it (it lives under projects/-x/<sid>/subagents/).
        sub_x_dir = os.path.join(self.claude, "projects", "-x", "usage-sid", "subagents")
        os.makedirs(sub_x_dir)
        self.usage_subagent_file = os.path.join(sub_x_dir, "sub.jsonl")
        open(self.usage_subagent_file, "w").write(
            f'{{"timestamp":"2026-08-04T00:00:00Z","cwd":"{a}","x":{{"subagent_type":"nested-from-subagent"}}}}\n')
        # synthetic Codex home: one twin agent (same as claude reviewer), one copied skill
        self.codex = os.path.join(t, "codex"); os.makedirs(os.path.join(self.codex, "agents")); os.makedirs(os.path.join(self.codex, "skills", "gsk"))
        open(os.path.join(self.codex, "agents", "reviewer.toml"), "w").write('name = "reviewer"\ndescription = "Reviews things carefully"\ndeveloper_instructions = "Body."\n')
        open(os.path.join(self.codex, "skills", "gsk", "SKILL.md"), "w").write("---\nname: gsk\ndescription: g\n---\n")
        os.makedirs(os.path.join(self.codex, "sessions", "2026", "08"))
        open(os.path.join(self.codex, "sessions", "2026", "08", "r.jsonl"), "w").write(f'{{"timestamp":"2026-08-04T00:00:00Z","type":"session_meta","payload":{{"cwd":"{a}"}}}}\n')
        open(os.path.join(a, "AGENTS.md"), "w").write("# AGENTS.md\nThis file provides guidance to Codex.\n")   # a copy, not a link
        # a solo-Codex project: AGENTS.md at its root but NO .claude/ dir at all -- must still be
        # discovered as a project (scan.find_claude_dirs used to only look for .claude). It needs
        # its own .git too (scan.find_claude_dirs requires one, so a bare AGENTS.md anywhere
        # under a root doesn't qualify -- a plain os.makedirs is enough to simulate the entry).
        self.codex_only = os.path.join(self.projects, "beta-codex-only")
        os.makedirs(self.codex_only)
        os.makedirs(os.path.join(self.codex_only, ".git"))
        open(os.path.join(self.codex_only, "AGENTS.md"), "w").write("# AGENTS.md\nSolo-Codex project, no .claude/ here.\n")
        # sessions fixture: one real-shaped transcript for project alpha + one subagent file.
        # Uses names ("sessions-demo-agent"/"sessions-demo-skill") that do NOT collide with
        # "reviewer"/"deploy" above, so usage.py-based assertions elsewhere stay unaffected.
        self.session_id = "sess-1"
        sdir = os.path.join(self.claude, "projects", "-work-alpha")
        os.makedirs(os.path.join(sdir, self.session_id, "subagents"))
        self.session_file = os.path.join(sdir, self.session_id + ".jsonl")
        open(self.session_file, "w").write(
            f'{{"type":"user","timestamp":"2026-08-10T09:00:00Z","cwd":"{a}","gitBranch":"main","sessionId":"{self.session_id}","version":"1.2.3","message":{{"role":"user","content":[{{"type":"text","text":"PROMPT_MARKER_DO_NOT_LEAK please refactor the widget loader"}}]}}}}\n'
            f'{{"type":"assistant","timestamp":"2026-08-10T09:01:00Z","cwd":"{a}","gitBranch":"main","sessionId":"{self.session_id}","message":{{"role":"assistant","content":[{{"type":"text","text":"On it."}},{{"type":"tool_use","name":"Edit","input":{{"file_path":"{a}/src/widget.py"}}}}],"usage":{{"input_tokens":120,"output_tokens":340,"cache_read_input_tokens":50,"cache_creation_input_tokens":10}}}}}}\n'
            f'{{"type":"assistant","timestamp":"2026-08-10T09:01:30Z","cwd":"{a}/apps","gitBranch":"main","sessionId":"{self.session_id}","message":{{"role":"assistant","content":[{{"type":"tool_use","name":"Agent","input":{{"subagent_type":"sessions-demo-agent"}}}},{{"type":"tool_use","name":"Skill","input":{{"skill":"sessions-demo-skill"}}}}],"usage":{{"input_tokens":80,"output_tokens":60,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}}}}\n'
            f'{{"type":"assistant","timestamp":"2026-08-10T09:02:00Z","cwd":"{a}","isSidechain":true,"sessionId":"{self.session_id}","message":{{"role":"assistant","content":[{{"type":"tool_use","name":"Read","input":{{"file_path":"{a}/src/secret.py"}}}}],"usage":{{"input_tokens":999,"output_tokens":999,"cache_read_input_tokens":999,"cache_creation_input_tokens":999}}}}}}\n'
            f'{{"type":"assistant","timestamp":"2026-08-10T09:03:00Z","cwd":"{a}","gitBranch":"main","sessionId":"{self.session_id}","message":{{"role":"assistant","content":[{{"type":"tool_use","name":"Bash","input":{{"command":"git commit -m done"}}}}],"usage":{{"input_tokens":30,"output_tokens":20,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}}}}\n'
            f'{{"type":"ai-title","aiTitle":"Refactor the widget loader","sessionId":"{self.session_id}"}}\n'
        )
        # A real subagent transcript marks EVERY line isSidechain:true (relative to the parent
        # conversation) -- unlike the parent transcript's own occasional sidechain line, this is
        # not a duplicate to exclude; it is the only shape subagent lines ever come in.
        open(os.path.join(sdir, self.session_id, "subagents", "agent-1.jsonl"), "w").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:01:35Z","isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{"pattern":"x"}}],"usage":{"input_tokens":15,"output_tokens":25,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n')
        # CRITICAL fix from adversarial review: default every transcript fixture (the pre-existing
        # -x/s.jsonl included) to a STALE mtime, so live.TranscriptProvider (Tarea 20) never marks
        # "alpha" active by accident in an ordinary Env-based test. Tests that need "active"
        # call env.touch_session(fresh=True) explicitly (see the method below).
        old = time.time() - 3600
        for p in (self.usage_history_file, self.usage_subagent_file, self.session_file,
                  os.path.join(sdir, self.session_id, "subagents", "agent-1.jsonl")):
            os.utime(p, (old, old))
        self.cfg = CFG._merge(CFG.DEFAULTS, {"claude_home": self.claude, "codex_home": self.codex, "roots": [self.projects], "state_dir": self.state,
                                             "live": {"provider": "none"}, "scan": {"measure_worktrees": False, "check_mcp": False}})
        self.alpha = a
    def cleanup(self): self.tmp.cleanup()

    def touch_session(self, fresh=True):
        """Set the mtime of the sessions fixture (session file + its subagent file) to 'now'
        (fresh=True, looks active to live.TranscriptProvider) or back to stale (fresh=False).
        Tests call this explicitly — the fixture defaults to stale (see Env.__init__ above)."""
        t = time.time() if fresh else time.time() - 3600
        sub = os.path.join(os.path.dirname(self.session_file), self.session_id, "subagents", "agent-1.jsonl")
        for p in (self.session_file, sub):
            os.utime(p, (t, t))

    def append_usage_line(self, text):
        """Append one more line to the main usage-history transcript (`self.usage_history_file`),
        simulating a session that keeps growing between two usage.refresh() calls."""
        with open(self.usage_history_file, "a") as f:
            f.write(text.rstrip("\n") + "\n")

    def truncate_usage_history(self, new_content):
        """Replace the full content of the main usage-history transcript with something
        SHORTER, simulating a rotation/rewrite under the same source_path."""
        with open(self.usage_history_file, "w") as f:
            f.write(new_content)

    def refresh_sessions(self):
        """Conveniencia para tests que necesitan `activity` poblada antes de llamar a
        snapshot.export_activity o de golpear el hub: corre sessions.refresh() de verdad
        contra el cfg de este Env, devuelve la lista de resúmenes."""
        from project_os import sessions as SESS
        return SESS.refresh(self.cfg)


def sample_export(machine, project="alpha", sessions=1, hours=1.0):
    """Un payload de `project-os export --activity` mínimo pero realista — para tests de hub que
    necesitan DOS O MÁS máquinas sin levantar un segundo Env sintético completo por cada una."""
    return {"project_os": 1, "machine": machine, "os": "Linux", "when": "2026-08-18T10:00",
            "agents": [], "skills": [], "harness": [], "projects": [project],
            "activity": {"aggregated": [{"project": project, "sessions": sessions, "hours": hours,
                                          "tokens": {"in": 100, "out": 200}, "commits": 1,
                                          "files_touched": 3, "tool_calls": {"Edit": 2},
                                          "agents": {}, "skills": {}}]}}
