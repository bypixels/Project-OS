import json, os, unittest
from unittest import mock
import _helpers  # noqa
from _env import Env
from cabina import scan

class TestSessionsFixture(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_fixture_has_a_session_file_and_a_subagent_file(self):
        self.assertTrue(os.path.isfile(self.env.session_file))
        sub_dir = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents")
        self.assertEqual(len([f for f in os.listdir(sub_dir) if f.endswith(".jsonl")]), 1)


import tempfile
from cabina import sessions as S

class TestReadNewLines(unittest.TestCase):
    def test_only_returns_bytes_after_offset(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.jsonl")
            open(p, "w").write('{"a":1}\n{"a":2}\n')
            lines1, off1 = S._read_new_lines(p, 0)
            self.assertEqual(len(lines1), 2)
            open(p, "a").write('{"a":3}\n')
            lines2, off2 = S._read_new_lines(p, off1)
            self.assertEqual(lines2, ['{"a":3}'])
            self.assertGreater(off2, off1)

    def test_never_consumes_a_partial_trailing_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.jsonl")
            first_line = '{"a":1}\n'
            open(p, "w").write(first_line + '{"a":2, "partial')  # no trailing \n: still being written
            lines1, off1 = S._read_new_lines(p, 0)
            self.assertEqual(lines1, ['{"a":1}'])
            self.assertEqual(off1, len(first_line))
            open(p, "a").write('": true}\n')  # the writer finishes the line
            lines2, off2 = S._read_new_lines(p, off1)
            self.assertEqual(lines2, ['{"a":2, "partial": true}'])

class TestMergeLinesCore(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_turns_tokens_and_sidechain_exclusion(self):
        lines, _ = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["turns"], 1)                     # only the one real human text message
        self.assertEqual(state["tokens"], {"in": 230, "out": 420, "cache_read": 50, "cache_write": 10})
        self.assertEqual(state["sidechain_lines"], 1)           # the isSidechain:true line, excluded above
        self.assertEqual(state["branch"], "main")
        self.assertEqual(state["title"], "Refactor the widget loader")

    def test_sidechain_excluded_from_started_ended_too(self):
        # a standalone, minimal pair of lines (not the shared fixture): the sidechain line's
        # timestamp is LATER than the real one, so if it leaked into `ended` this would catch it.
        lines = [
            '{"type":"user","timestamp":"2026-08-10T09:00:00Z","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}',
            '{"type":"assistant","timestamp":"2026-08-10T09:05:00Z","isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{}}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}',
        ]
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["ended"], "2026-08-10T09:00:00Z")     # the sidechain line's later timestamp never counts

    def test_tool_extraction_excludes_sidechain(self):
        lines, _ = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["tool_calls"], {"Edit": 1, "Agent": 1, "Skill": 1, "Bash": 1})   # no "Read" (sidechain)
        self.assertEqual(state["files_touched"], [f"{self.env.alpha}/src/widget.py"])           # absolute here; relpath happens at _finalize
        self.assertEqual(state["agents"], {"sessions-demo-agent": 1})
        self.assertEqual(state["skills"], {"sessions-demo-skill": 1})
        self.assertEqual(state["commits"], 1)

class TestFinalize(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_finalize_majority_cwd_and_local_time(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        roots = {"alpha": self.env.alpha}
        summary = S._finalize(state, self.env.session_file, roots, off)
        self.assertEqual(summary["cwd"], self.env.alpha)          # 3 lines with alpha vs 1 with alpha/apps
        self.assertTrue(summary["cwd_changed"])
        self.assertEqual(summary["project"], "alpha")
        self.assertEqual(summary["started"], S._to_local_iso("2026-08-10T09:00:00Z"))
        self.assertEqual(summary["ended"], S._to_local_iso("2026-08-10T09:03:00Z"))
        self.assertEqual(summary["duration_s"], 180)
        self.assertEqual(summary["files_touched"], ["src/widget.py"])   # relative to the project root now

    def test_finalize_unknown_project_when_no_cwd_lines(self):
        state = S._merge_lines(S._new_state(), ['{"type":"ai-title","aiTitle":"x"}'])
        summary = S._finalize(state, "/tmp/fake/-nowhere/s.jsonl", {}, 0)
        self.assertEqual(summary["project"], "unknown")
        self.assertIsNone(summary["cwd"])
        self.assertFalse(summary["cwd_changed"])

    def test_subagents_count_and_unsummed_tokens(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        summary = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
        self.assertEqual(summary["subagents"], 1)
        self.assertEqual(summary["subagent_tokens"], {"in": 15, "out": 25, "cache_read": 0, "cache_write": 0})
        self.assertEqual(summary["tokens"]["in"], 230)             # unchanged: subagent tokens NOT added in

    def test_subagent_tokens_read_incrementally_by_offset(self):
        # R2 perf fix: subagent transcripts are re-read by offset, not in full every refresh —
        # same idea as the session file's own incremental parsing (Tarea 17).
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        summary = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
        self.assertEqual(summary["subagent_tokens"], {"in": 15, "out": 25, "cache_read": 0, "cache_write": 0})
        sub_path = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents", "agent-1.jsonl")
        self.assertIn(sub_path, state["subagent_files"])
        off1 = state["subagent_files"][sub_path]["offset"]
        open(sub_path, "a").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:05:00Z","message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{"pattern":"y"}}],"usage":{"input_tokens":7,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n')
        summary2 = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
        self.assertEqual(summary2["subagent_tokens"], {"in": 22, "out": 28, "cache_read": 0, "cache_write": 0})  # grew by exactly the appended amount
        self.assertGreater(state["subagent_files"][sub_path]["offset"], off1)

    def test_never_stores_prompt_text_and_matches_allowlist(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        summary = S._redact_unknown_fields(S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off))
        dumped = json.dumps(summary)
        self.assertNotIn("PROMPT_MARKER_DO_NOT_LEAK", dumped)
        self.assertEqual(set(summary), set(S.SUMMARY_FIELDS))

class TestSessionsRegistry(unittest.TestCase):
    def test_save_load_roundtrip_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sessions.json")
            S._save_registry(p, {"a.jsonl": {"offset": 10, "size": 10, "mtime": 1.0, "partial_state": {}, "summary": {"session_id": "a"}}})
            self.assertEqual(S._load_registry(p)["a.jsonl"]["summary"]["session_id"], "a")
        self.assertEqual(S._load_registry("/no/such/file.json"), {})

class TestSessionsRefresh(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_refresh_finds_the_session(self):
        items = S.refresh(self.env.cfg, days=30)
        self.assertTrue(any(s["session_id"] == "sess-1" for s in items))

    def test_refresh_is_truly_incremental_on_appended_bytes(self):
        S.refresh(self.env.cfg, days=30)
        reg = S._load_registry(S.registry_path(self.env.cfg))
        off1 = reg[self.env.session_file]["offset"]
        open(self.env.session_file, "a").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:04:00Z","cwd":"%s","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write","input":{"file_path":"%s/src/new.py"}}],"usage":{"input_tokens":5,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
            % (self.env.alpha, self.env.alpha))
        items = S.refresh(self.env.cfg, days=30)
        reg2 = S._load_registry(S.registry_path(self.env.cfg))
        self.assertGreater(reg2[self.env.session_file]["offset"], off1)
        s = next(s for s in items if s["session_id"] == "sess-1")
        self.assertIn("Write", s["tool_calls"])

    def test_refresh_survives_source_deletion_but_prunes_by_retention_age(self):
        S.refresh(self.env.cfg, days=30)
        os.remove(self.env.session_file)
        items = S.refresh(self.env.cfg, days=30)
        self.assertTrue(any(s["session_id"] == "sess-1" for s in items))     # R4: NOT pruned just because deleted
        cfg2 = dict(self.env.cfg, activity={"retention_days": 0})            # everything is "too old" now
        items2 = S.refresh(cfg2, days=30)
        self.assertFalse(any(s["session_id"] == "sess-1" for s in items2))   # pruned by age, not by existence

    # NOTE: the on-disk "never leaks prompt text" canary used to live here, but it stayed
    # green even if _redact_partial_state were identity (_merge_lines never actually copies
    # prompt text into `state`, so there was nothing for the guard to catch). It has been
    # replaced by a real canary in tests/test_breaks.py that injects the marker via a wrapper
    # around the real _merge_lines, so the guard at the write site is genuinely exercised.

    def test_load_reads_cache_without_touching_source_files(self):
        S.refresh(self.env.cfg, days=30)
        os.remove(self.env.session_file)
        items = S.load(self.env.cfg)
        self.assertTrue(any(s["session_id"] == "sess-1" for s in items))

    def test_refresh_survives_one_unreadable_transcript_keeps_the_rest(self):
        # A second session file, sitting right next to the fixture's own one — if reading it
        # raises (permission error, disk hiccup, mid-rotation), refresh() must still return
        # every OTHER session, and still write the registry to disk (R2/R4's "one bad
        # transcript is never fatal" promise, exercised end-to-end through refresh()).
        second = os.path.join(os.path.dirname(self.env.session_file), "sess-2.jsonl")
        content = open(self.env.session_file, encoding="utf-8").read().replace("sess-1", "sess-2")
        open(second, "w", encoding="utf-8").write(content)
        real_read = S._read_new_lines
        def flaky_read(path, offset):
            if path.endswith("sess-2.jsonl"):
                raise OSError("simulated unreadable transcript")
            return real_read(path, offset)
        with mock.patch.object(S, "_read_new_lines", flaky_read):
            items = S.refresh(self.env.cfg, days=30)
        self.assertTrue(any(s["session_id"] == "sess-1" for s in items))
        self.assertFalse(any(s["session_id"] == "sess-2" for s in items))
        self.assertTrue(os.path.isfile(S.registry_path(self.env.cfg)))

class TestGitProjectFallback(unittest.TestCase):
    """A session whose cwd is a git repo WITHOUT a .claude/ dir (so scan.py never registers it
    as a project) must not be dropped as project=None — it gets attributed to its own repo."""
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_git_repo_without_claude_dir_is_attributed_by_its_own_root(self):
        beta = os.path.join(self.env.projects, "beta")
        os.makedirs(os.path.join(beta, ".git"))
        os.makedirs(os.path.join(beta, "src"))
        roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
        state = S._new_state()
        state["cwd_counts"] = {os.path.join(beta, "src"): 1}
        summary = S._finalize(state, "/fake/source.jsonl", roots, 0, cfg_roots=[self.env.projects])
        self.assertEqual(summary["project"], "beta")

        outside_state = S._new_state()
        outside_state["cwd_counts"] = {"/somewhere/else/entirely": 1}
        outside_summary = S._finalize(outside_state, "/fake/source2.jsonl", roots, 0, cfg_roots=[self.env.projects])
        self.assertEqual(outside_summary["project"], "unknown")   # one sentinel for "no project", never None

if __name__ == "__main__":
    unittest.main()
