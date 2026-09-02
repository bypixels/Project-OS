import json, os, threading, time, unittest
from unittest import mock
import _helpers  # noqa
from _env import Env
from project_os import scan

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
from project_os import sessions as S

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
        self.assertEqual(state["tokens"], {"in": 230, "out": 420, "cache_read": 50, "cache_write": 10,
                                            "thinking": 0, "thinking_lines": 0})
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

    def test_last_tools_rolling_window_and_details(self):
        lines, _ = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        # the sidechain Read (excluded above) never reaches last_tools either -- it `continue`s
        # out of _merge_lines before the tool_use loop is ever entered for that line.
        self.assertEqual(state["last_tools"], [
            {"name": "Edit", "detail": "widget.py", "ts": "2026-08-10T09:01:00Z"},
            {"name": "Agent", "detail": "sessions-demo-agent", "ts": "2026-08-10T09:01:30Z"},
            {"name": "Skill", "detail": "sessions-demo-skill", "ts": "2026-08-10T09:01:30Z"},
            {"name": "Bash", "detail": "git commit -m done", "ts": "2026-08-10T09:03:00Z"},
        ])

    def test_last_tools_caps_at_eight_dropping_the_oldest(self):
        lines = [
            '{"type":"assistant","timestamp":"2026-08-10T09:%02d:00Z","message":{"role":"assistant",'
            '"content":[{"type":"tool_use","name":"Read","input":{"file_path":"/p/f%d.py"}}],'
            '"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
            % (i, i) for i in range(9)
        ]
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(len(state["last_tools"]), 8)
        self.assertEqual(state["last_tools"][0]["detail"], "f1.py")    # f0 (the 1st) evicted
        self.assertEqual(state["last_tools"][-1]["detail"], "f8.py")

    def test_last_tools_detail_per_tool_type(self):
        lines = [
            '{"type":"assistant","timestamp":"t1","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{"file_path":"/a/b/c.py"}}],"usage":{}}}',
            '{"type":"assistant","timestamp":"t2","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write","input":{"file_path":"/a/b/d.py"}}],"usage":{}}}',
            '{"type":"assistant","timestamp":"t3","message":{"role":"assistant","content":[{"type":"tool_use","name":"NotebookEdit","input":{"file_path":"/a/b/e.ipynb"}}],"usage":{}}}',
            '{"type":"assistant","timestamp":"t4","message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{"pattern":"x"}}],"usage":{}}}',
        ]
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual([t["detail"] for t in state["last_tools"]], ["c.py", "d.py", "e.ipynb", ""])

    def test_last_tools_bash_detail_truncated_to_80_chars(self):
        cmd = "echo " + "y" * 100
        line = ('{"type":"assistant","timestamp":"t1","message":{"role":"assistant","content":'
                '[{"type":"tool_use","name":"Bash","input":{"command":"%s"}}],"usage":{}}}' % cmd)
        state = S._merge_lines(S._new_state(), [line])
        self.assertEqual(state["last_tools"][0]["detail"], cmd[:80])
        self.assertEqual(len(state["last_tools"][0]["detail"]), 80)

    def test_last_tools_detail_hard_capped_at_120_chars(self):
        long_name = "x" * 200 + ".py"
        line = ('{"type":"assistant","timestamp":"t1","message":{"role":"assistant","content":'
                '[{"type":"tool_use","name":"Read","input":{"file_path":"/a/%s"}}],"usage":{}}}' % long_name)
        state = S._merge_lines(S._new_state(), [line])
        self.assertEqual(len(state["last_tools"][0]["detail"]), 120)

class TestLastToolsHydration(unittest.TestCase):
    def test_hydrate_state_defaults_last_tools_to_empty_list(self):
        # simulates a partial_state persisted before last_tools existed -- an old session
        # must render an empty list, never None.
        hydrated = S._hydrate_state({})
        self.assertEqual(hydrated["last_tools"], [])

    def test_hydrate_state_coerces_non_list_last_tools_to_empty_list(self):
        for bad in (None, {"oops": 1}, "not-a-list", 42):
            hydrated = S._hydrate_state({"last_tools": bad})
            self.assertEqual(hydrated["last_tools"], [], f"did not coerce {bad!r}")

    def test_hydrate_state_keeps_a_real_last_tools_list_untouched(self):
        real = [{"name": "Bash", "detail": "ls", "ts": "t"}]
        hydrated = S._hydrate_state({"last_tools": real})
        self.assertEqual(hydrated["last_tools"], real)

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
        self.assertEqual(summary["subagent_tokens"], {"in": 15, "out": 25, "cache_read": 0, "cache_write": 0,
                                                        "thinking": 0, "thinking_lines": 0})
        self.assertEqual(summary["tokens"]["in"], 230)             # unchanged: subagent tokens NOT added in

    def test_subagent_tokens_read_incrementally_by_offset(self):
        # R2 perf fix: subagent transcripts are re-read by offset, not in full every refresh —
        # same idea as the session file's own incremental parsing (Tarea 17).
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        summary = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
        self.assertEqual(summary["subagent_tokens"], {"in": 15, "out": 25, "cache_read": 0, "cache_write": 0,
                                                        "thinking": 0, "thinking_lines": 0})
        sub_path = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents", "agent-1.jsonl")
        self.assertIn(sub_path, state["subagent_files"])
        off1 = state["subagent_files"][sub_path]["offset"]
        open(sub_path, "a").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:05:00Z","message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{"pattern":"y"}}],"usage":{"input_tokens":7,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n')
        summary2 = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
        self.assertEqual(summary2["subagent_tokens"], {"in": 22, "out": 28, "cache_read": 0, "cache_write": 0,
                                                         "thinking": 0, "thinking_lines": 0})  # grew by exactly the appended amount
        self.assertGreater(state["subagent_files"][sub_path]["offset"], off1)

    def test_subagent_rows_derived_from_subagent_files_sorted_by_tokens_desc(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        summary = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
        # fixture subagent agent-1.jsonl: in=15, out=25, cache_read=0, cache_write=0 -> 40 total
        self.assertEqual(summary["subagent_rows"], [{"name": "agent-1", "tokens": 40}])

    def test_never_stores_prompt_text_and_matches_allowlist(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        summary = S._redact_unknown_fields(S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off))
        dumped = json.dumps(summary)
        self.assertNotIn("PROMPT_MARKER_DO_NOT_LEAK", dumped)
        self.assertEqual(set(summary), set(S.SUMMARY_FIELDS))

class TestSubagentRowsHonesty(unittest.TestCase):
    """subagent_rows must distinguish "read and summed to zero for real" (0) from "no
    measurement in the state at all" (None) -- a missing/malformed "tokens" entry must never
    fabricate a 0."""
    def test_measured_zero_stays_zero(self):
        files_state = {"/x/agent-1.jsonl": {"offset": 10, "tokens": S._empty_tokens()}}
        self.assertEqual(S._subagent_rows(files_state), [{"name": "agent-1", "tokens": 0}])

    def test_unmeasured_entry_is_none_not_zero(self):
        files_state = {"/x/agent-2.jsonl": {"offset": 0}}   # no "tokens" key: never measured
        self.assertEqual(S._subagent_rows(files_state), [{"name": "agent-2", "tokens": None}])

    def test_none_rows_sort_after_measured_rows(self):
        files_state = {
            "/x/unmeasured.jsonl": {"offset": 0},
            "/x/measured.jsonl": {"offset": 5, "tokens": {**S._empty_tokens(), "in": 3}},
        }
        rows = S._subagent_rows(files_state)
        self.assertEqual([r["name"] for r in rows], ["measured", "unmeasured"])

class TestSubagentDisplayName(unittest.TestCase):
    def test_prefers_sibling_meta_json_name(self):
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "agent-c66d104646b4ce40.jsonl")
            open(os.path.join(d, "agent-c66d104646b4ce40.meta.json"), "w").write('{"name": "abench"}')
            rows = S._subagent_rows({fp: {"offset": 0, "tokens": S._empty_tokens()}})
            self.assertEqual(rows[0]["name"], "abench")

    def test_falls_back_to_agent_type_in_meta_json(self):
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "agent-c66d104646b4ce40.jsonl")
            open(os.path.join(d, "agent-c66d104646b4ce40.meta.json"), "w").write('{"agentType": "bench"}')
            rows = S._subagent_rows({fp: {"offset": 0, "tokens": S._empty_tokens()}})
            self.assertEqual(rows[0]["name"], "bench")

    def test_falls_back_to_hash_stripped_stem_without_meta_json(self):
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "bench-c66d104646b4ce40.jsonl")
            rows = S._subagent_rows({fp: {"offset": 0, "tokens": S._empty_tokens()}})
            self.assertEqual(rows[0]["name"], "bench")     # the hash never reaches the user

class TestAgentNameFromId(unittest.TestCase):
    """F3 join, the derivation step verified against real transcripts: agentId is always
    "a" + <invocation name> + "-" + <16 hex char suffix>."""
    def test_derives_name_stripping_the_a_prefix_and_hash_suffix(self):
        self.assertEqual(S._agent_name_from_id("aexec-f1-8c90eac07a24bee4"), "exec-f1")
        self.assertEqual(S._agent_name_from_id("askeptic-f2-f5ee8e421520b674"), "skeptic-f2")

    def test_none_or_empty_or_not_a_prefixed_returns_none(self):
        self.assertIsNone(S._agent_name_from_id(None))
        self.assertIsNone(S._agent_name_from_id(""))
        self.assertIsNone(S._agent_name_from_id("no-leading-a-marker-0123456789abcdef"))

    def test_non_conforming_id_that_merely_starts_with_a_returns_none(self):
        # "admin" starts with "a" (the old check's ONLY test) but is not the real shape at all
        # -- must not be misread as name "dmin".
        self.assertIsNone(S._agent_name_from_id("admin"))

    def test_unnamed_hash_only_id_returns_none(self):
        # An unnamed invocation's agentId is "a" + 16 hex chars, no name/"-" part at all -- after
        # requiring the full "a" + name + "-" + 16hex shape, there is no name to recover.
        self.assertIsNone(S._agent_name_from_id("a0123456789abcdef"))

    def test_full_conforming_shape_with_short_name(self):
        self.assertEqual(S._agent_name_from_id("aalpha-0123456789abcdef"), "alpha")

    def test_full_conforming_shape_with_hyphenated_name(self):
        self.assertEqual(S._agent_name_from_id("afix-0123456789abcdef-8c90eac07a24bee4"), "fix-0123456789abcdef")


class TestMergeLinesAgentNamesJoin(unittest.TestCase):
    """F3 join, half 1: `_merge_lines` must record, per session, the invocation `name` ->
    `subagent_type` mapping from parent Agent tool_use blocks -- and mark it ambiguous (None)
    the moment the SAME name is reused for a conflicting subagent_type."""
    def _agent_line(self, name, subagent_type):
        return ('{"type":"assistant","timestamp":"t","message":{"role":"assistant","content":'
                '[{"type":"tool_use","name":"Agent","input":{"subagent_type":"%s","name":"%s"}}],"usage":{}}}'
                % (subagent_type, name))

    def test_records_name_to_subagent_type(self):
        state = S._merge_lines(S._new_state(), [self._agent_line("exec-f1", "general-purpose")])
        self.assertEqual(state["agent_names"], {"exec-f1": "general-purpose"})

    def test_no_name_in_input_leaves_agent_names_untouched(self):
        # the shared fixture's own Agent tool_use never carries a "name" -- this is the
        # existing/legacy shape, must not raise or fabricate an entry.
        line = ('{"type":"assistant","timestamp":"t","message":{"role":"assistant","content":'
                '[{"type":"tool_use","name":"Agent","input":{"subagent_type":"reviewer"}}],"usage":{}}}')
        state = S._merge_lines(S._new_state(), [line])
        self.assertEqual(state["agent_names"], {})
        self.assertEqual(state["agents"], {"reviewer": 1})   # unaffected

    def test_same_name_same_type_repeated_stays_unambiguous(self):
        lines = [self._agent_line("exec-f1", "general-purpose"), self._agent_line("exec-f1", "general-purpose")]
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["agent_names"], {"exec-f1": "general-purpose"})

    def test_same_name_different_type_becomes_ambiguous(self):
        lines = [self._agent_line("fix-f1", "general-purpose"), self._agent_line("fix-f1", "code-reviewer")]
        state = S._merge_lines(S._new_state(), lines)
        self.assertIsNone(state["agent_names"]["fix-f1"])

    def test_ambiguity_is_sticky_across_further_lines(self):
        lines = [self._agent_line("fix-f1", "general-purpose"), self._agent_line("fix-f1", "code-reviewer"),
                 self._agent_line("fix-f1", "general-purpose")]
        state = S._merge_lines(S._new_state(), lines)
        self.assertIsNone(state["agent_names"]["fix-f1"])   # once ambiguous, stays ambiguous

    def test_different_names_do_not_interfere(self):
        lines = [self._agent_line("exec-f1", "general-purpose"), self._agent_line("skeptic-f1", "code-reviewer")]
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["agent_names"], {"exec-f1": "general-purpose", "skeptic-f1": "code-reviewer"})


class TestSubagentTokensCapturesAgentIdAndToolCalls(unittest.TestCase):
    """F3 join, half 2: `_subagent_tokens` must also capture the subagent transcript's own
    `agentId` (from its first line) and a per-tool tool_use count -- both read in the SAME pass
    that already reads tokens, never a second file walk."""
    def test_agent_id_and_tool_calls_captured_from_a_subagent_file(self):
        with tempfile.TemporaryDirectory() as d:
            sdir = os.path.join(d, "sess", "subagents")
            os.makedirs(sdir)
            fp = os.path.join(sdir, "agent-aexec-f1-8c90eac07a24bee4.jsonl")
            open(fp, "w").write(
                '{"agentId":"aexec-f1-8c90eac07a24bee4","isSidechain":true,"message":{"role":"user","content":[]}}\n'
                '{"isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{}}],"usage":{}}}\n'
                '{"isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{}},{"type":"tool_use","name":"Read","input":{}}],"usage":{}}}\n'
            )
            source_path = os.path.join(d, "sess.jsonl")
            state = S._new_state()
            S._subagent_tokens(source_path, state)
            entry = state["subagent_files"][fp]
            self.assertEqual(entry["agent_id"], "aexec-f1-8c90eac07a24bee4")
            self.assertEqual(entry["tool_calls"], {"Bash": 2, "Read": 1})

    def test_agent_id_captured_only_once_even_across_incremental_reads(self):
        with tempfile.TemporaryDirectory() as d:
            sdir = os.path.join(d, "sess", "subagents")
            os.makedirs(sdir)
            fp = os.path.join(sdir, "agent-aexec-f2-786cf1f1f994415e.jsonl")
            open(fp, "w").write('{"agentId":"aexec-f2-786cf1f1f994415e","isSidechain":true,"message":{"role":"user","content":[]}}\n')
            source_path = os.path.join(d, "sess.jsonl")
            state = S._new_state()
            S._subagent_tokens(source_path, state)
            open(fp, "a").write('{"isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{}}],"usage":{}}}\n')
            S._subagent_tokens(source_path, state)
            entry = state["subagent_files"][fp]
            self.assertEqual(entry["agent_id"], "aexec-f2-786cf1f1f994415e")
            self.assertEqual(entry["tool_calls"], {"Grep": 1})   # accumulated, not reset


class TestSubagentToolNames(unittest.TestCase):
    """`_subagent_tool_names` derives {name: {tool: count}} from files_state -- purely derived,
    no new state, same pattern as `_subagent_rows`."""
    def test_derives_name_via_agent_id(self):
        files_state = {"/x/agent-aexec-f1-hash.jsonl": {"agent_id": "aexec-f1-8c90eac07a24bee4",
                                                          "tool_calls": {"Bash": 91, "Read": 3}}}
        self.assertEqual(S._subagent_tool_names(files_state), {"exec-f1": {"Bash": 91, "Read": 3}})

    def test_entry_without_agent_id_contributes_nothing(self):
        files_state = {"/x/agent-1.jsonl": {"tool_calls": {"Bash": 5}}}   # no agent_id captured
        self.assertEqual(S._subagent_tool_names(files_state), {})

    def test_entry_without_tool_calls_contributes_nothing(self):
        files_state = {"/x/agent-aexec-f1-hash.jsonl": {"agent_id": "aexec-f1-8c90eac07a24bee4"}}
        self.assertEqual(S._subagent_tool_names(files_state), {})

    def test_two_files_deriving_the_same_name_sum_their_counts(self):
        files_state = {
            "/x/a.jsonl": {"agent_id": "aexec-f1-8c90eac07a24bee4", "tool_calls": {"Bash": 1}},
            "/x/b.jsonl": {"agent_id": "aexec-f1-1111111111111111", "tool_calls": {"Bash": 2}},
        }
        self.assertEqual(S._subagent_tool_names(files_state), {"exec-f1": {"Bash": 3}})


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

    def test_refresh_reprocesses_when_only_a_subagent_transcript_grew(self):
        # Fast-path bug: the parent transcript's mtime/size are what gate re-processing on a
        # refresh, but a subagent can still be writing long after the parent stops changing --
        # growing ONLY the subagent file must still be picked up on the next refresh.
        S.refresh(self.env.cfg, days=30)
        sub_path = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents", "agent-1.jsonl")
        open(sub_path, "a").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:05:00Z","isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{"pattern":"y"}}],"usage":{"input_tokens":7,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n')
        items = S.refresh(self.env.cfg, days=30)
        s = next(s for s in items if s["session_id"] == "sess-1")
        self.assertEqual(s["subagent_tokens"]["in"], 22)      # 15 + 7
        self.assertEqual(s["subagent_tokens"]["out"], 28)     # 25 + 3
        self.assertEqual(s["subagent_rows"], [{"name": "agent-1", "tokens": 50}])   # 22 + 28

    def test_refresh_recovers_from_corrupt_last_tools_in_registry(self):
        # Defensive: a persisted partial_state whose last_tools is not a list (None, a dict, a
        # stray string -- e.g. from a bug in an earlier version, or hand-edited state) must
        # never stop the session from refreshing normally afterwards.
        S.refresh(self.env.cfg, days=30)
        reg_path = S.registry_path(self.env.cfg)
        reg = S._load_registry(reg_path)
        reg[self.env.session_file]["partial_state"]["last_tools"] = None
        S._save_registry(reg_path, reg)
        open(self.env.session_file, "a").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:04:00Z","cwd":"%s","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write","input":{"file_path":"%s/src/new2.py"}}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
            % (self.env.alpha, self.env.alpha))
        items = S.refresh(self.env.cfg, days=30)
        s = next(s for s in items if s["session_id"] == "sess-1")
        self.assertIn("Write", s["tool_calls"])
        self.assertIsInstance(s["last_tools"], list)

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

class TestObservedToolsEndToEnd(unittest.TestCase):
    """Full F3 join through `refresh()` + `observed_tools()`: a parent Agent tool_use (name +
    subagent_type) joined against its subagents/agent-a<name>-<hash>.jsonl transcript's own
    tool_use calls, read INCREMENTALLY (offset-by-offset, same as everything else in this
    module) -- and the ambiguity rule (a name reused for a conflicting subagent_type is dropped,
    never guessed) holds end to end, not just at the `_merge_lines` unit level."""
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def _add_agent_invocation(self, env, name, subagent_type):
        open(env.session_file, "a").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:04:00Z","cwd":"%s","message":{"role":"assistant","content":'
            '[{"type":"tool_use","name":"Agent","input":{"subagent_type":"%s","name":"%s"}}],"usage":{}}}\n'
            % (env.alpha, subagent_type, name))

    def _new_subagent_file(self, env, agent_id, extra_lines=()):
        sdir = os.path.join(os.path.dirname(env.session_file), env.session_id, "subagents")
        fp = os.path.join(sdir, "agent-%s.jsonl" % agent_id)
        content = '{"agentId":"%s","isSidechain":true,"message":{"role":"user","content":[]}}\n' % agent_id
        content += "".join(l + "\n" for l in extra_lines)
        open(fp, "w").write(content)
        return fp

    def _bash_line(self):
        return '{"isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{}}],"usage":{}}}'

    def _grep_line(self):
        return '{"isSidechain":true,"message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{}}],"usage":{}}}'

    def test_full_join_end_to_end_through_refresh(self):
        self._add_agent_invocation(self.env, "exec-w", "worker")
        self._new_subagent_file(self.env, "aexec-w-8c90eac07a24bee4", [self._bash_line(), self._bash_line()])
        items = S.refresh(self.env.cfg, days=30)
        s = next(x for x in items if x["session_id"] == "sess-1")
        self.assertEqual(s["agent_names"]["exec-w"], "worker")
        self.assertEqual(s["subagent_tool_names"]["exec-w"], {"Bash": 2})
        observed = S.observed_tools(self.env.cfg)
        self.assertEqual(observed["worker"], {"Bash": 2})

    def test_ambiguous_name_excluded_from_observed_tools(self):
        self._add_agent_invocation(self.env, "fix-f1", "general-purpose")
        self._add_agent_invocation(self.env, "fix-f1", "code-reviewer")   # same name, conflicting type
        self._new_subagent_file(self.env, "afix-f1-1111111111111111", [self._bash_line()])
        S.refresh(self.env.cfg, days=30)
        observed = S.observed_tools(self.env.cfg)
        self.assertNotIn("general-purpose", observed)
        self.assertNotIn("code-reviewer", observed)

    def test_incremental_resume_two_refresh_passes_equals_one_pass(self):
        # Same final content, built two ways: env A gets everything before a SINGLE refresh; env
        # B (self.env) gets the subagent's tool_use lines appended and refreshed in a SECOND
        # pass, after a first refresh already ran with just the agentId line on disk. Final
        # observed_tools() must agree either way, proving the join survives incremental resume.
        envA = Env()
        try:
            self._add_agent_invocation(envA, "exec-w", "worker")
            self._new_subagent_file(envA, "aexec-w-8c90eac07a24bee4", [self._bash_line(), self._grep_line()])
            S.refresh(envA.cfg, days=30)
            observed_a = S.observed_tools(envA.cfg)
        finally:
            envA.cleanup()

        self._add_agent_invocation(self.env, "exec-w", "worker")
        fp = self._new_subagent_file(self.env, "aexec-w-8c90eac07a24bee4")   # agentId line only
        S.refresh(self.env.cfg, days=30)                                      # pass 1: no tool_use yet
        open(fp, "a").write(self._bash_line() + "\n")
        open(fp, "a").write(self._grep_line() + "\n")
        S.refresh(self.env.cfg, days=30)                                      # pass 2: picked up incrementally
        observed_b = S.observed_tools(self.env.cfg)
        self.assertEqual(observed_a, observed_b)
        self.assertEqual(observed_b["worker"], {"Bash": 1, "Grep": 1})


class TestObservedToolsTypeGuards(unittest.TestCase):
    """Defensive: a corrupt registry entry (hand-edited, or from a bug in an earlier version)
    must never raise up into check.run() -- same doctrine as _hydrate_state's last_tools/
    agent_names guards and _subagent_tool_names's `isinstance(entry, dict)` check. A corrupt
    summary contributes nothing observable, never a crash."""
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def _seed(self, summaries):
        reg = {}
        for i, s in enumerate(summaries):
            reg[f"/fake/session-{i}.jsonl"] = {"offset": 0, "size": 0, "mtime": 0,
                                                "partial_state": {}, "summary": s}
        S._save_registry(S.registry_path(self.env.cfg), reg)

    def test_agent_names_as_a_list_contributes_nothing(self):
        self._seed([{"agent_names": ["exec-w"], "subagent_tool_names": {"exec-w": {"Bash": 1}}}])
        self.assertEqual(S.observed_tools(self.env.cfg), {})

    def test_subagent_tool_names_as_a_list_contributes_nothing(self):
        self._seed([{"agent_names": {"exec-w": "worker"}, "subagent_tool_names": ["exec-w"]}])
        self.assertEqual(S.observed_tools(self.env.cfg), {})

    def test_non_dict_tool_bucket_contributes_nothing(self):
        self._seed([{"agent_names": {"exec-w": "worker"}, "subagent_tool_names": {"exec-w": ["Bash"]}}])
        self.assertEqual(S.observed_tools(self.env.cfg), {})

    def test_corrupt_summary_does_not_block_a_clean_one(self):
        self._seed([
            {"agent_names": ["exec-bad"], "subagent_tool_names": {"exec-bad": {"Bash": 1}}},
            {"agent_names": {"exec-w": "worker"}, "subagent_tool_names": {"exec-w": {"Bash": 2}}},
        ])
        self.assertEqual(S.observed_tools(self.env.cfg), {"worker": {"Bash": 2}})

    def test_non_str_subagent_type_value_contributes_nothing(self):
        # A `subagent_type` value that survived as a list (not a plain str, not the ambiguous-None
        # sentinel) is unhashable -- `result.setdefault(subagent_type, {})` must not raise.
        self._seed([{"agent_names": {"exec-w": ["worker"]}, "subagent_tool_names": {"exec-w": {"Bash": 1}}}])
        self.assertEqual(S.observed_tools(self.env.cfg), {})

    def test_non_numeric_tool_count_is_skipped_not_summed(self):
        # A tool count persisted as a str (or a bool, which is an int subclass and would silently
        # pass a bare `isinstance(n, int)` check) must not reach `bucket.get(tool, 0) + n` -- that
        # raises TypeError (int + str) or, for bool, corrupts the count with True/False math.
        self._seed([{"agent_names": {"exec-w": "worker"},
                      "subagent_tool_names": {"exec-w": {"Bash": "5", "Read": True, "Grep": 3}}}])
        self.assertEqual(S.observed_tools(self.env.cfg), {"worker": {"Grep": 3}})

    def test_one_corrupt_summary_does_not_block_another_summarys_valid_entries(self):
        self._seed([
            {"agent_names": {"exec-bad": ["worker"]}, "subagent_tool_names": {"exec-bad": {"Bash": 1}}},
            {"agent_names": {"exec-w": "worker"}, "subagent_tool_names": {"exec-w": {"Bash": "5", "Grep": 2}}},
        ])
        self.assertEqual(S.observed_tools(self.env.cfg), {"worker": {"Grep": 2}})


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

    def test_nested_git_repo_gets_a_deterministic_relative_name(self):
        # Naming is now ALWAYS path-relative-to-the-containing-root, never basename-with-a-
        # collision-branch: deterministic regardless of what other projects happen to be
        # scanned first. A repo directly under a root still reduces to its basename.
        gamma = os.path.join(self.env.projects, "sub", "gamma")
        os.makedirs(os.path.join(gamma, ".git"))
        roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
        state = S._new_state()
        state["cwd_counts"] = {gamma: 1}
        summary = S._finalize(state, "/fake/source3.jsonl", roots, 0, cfg_roots=[self.env.projects])
        self.assertEqual(summary["project"], os.path.join("sub", "gamma"))

    def test_fallback_repo_files_touched_are_relative_to_its_git_root(self):
        beta = os.path.join(self.env.projects, "beta")
        os.makedirs(os.path.join(beta, ".git"))
        roots = scan.project_roots(self.env.cfg, scan.run(self.env.cfg))
        state = S._new_state()
        state["cwd_counts"] = {beta: 1}
        state["files_touched"] = [os.path.join(beta, "src", "x.py")]
        summary = S._finalize(state, "/fake/source4.jsonl", roots, 0, cfg_roots=[self.env.projects])
        self.assertEqual(summary["project"], "beta")
        self.assertEqual(summary["files_touched"], [os.path.join("src", "x.py")])

class TestEntrypointAndThinkingTokens(unittest.TestCase):
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def test_entrypoint_survives_refresh_save_load_roundtrip(self):
        # defends against the SUMMARY_FIELDS/PARTIAL_STATE_FIELDS allowlist trap: if entrypoint
        # is missing from either, it vanishes somewhere in refresh -> save -> load.
        open(self.env.session_file, "a").write(
            '{"type":"user","entrypoint":"sdk-py","timestamp":"2026-08-10T09:03:30Z","sessionId":"%s",'
            '"message":{"role":"user","content":[{"type":"text","text":"more"}]}}\n' % self.env.session_id)
        S.refresh(self.env.cfg, days=30)
        items = S.load(self.env.cfg)
        s = next(s for s in items if s["session_id"] == "sess-1")
        self.assertEqual(s["entrypoint"], "sdk-py")

    def test_entrypoint_first_occurrence_wins(self):
        lines = [
            '{"type":"user","entrypoint":"cli","timestamp":"2026-08-10T09:00:00Z","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}',
            '{"type":"assistant","entrypoint":"sdk-py","timestamp":"2026-08-10T09:01:00Z","message":{"role":"assistant","content":[],"usage":{}}}',
        ]
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["entrypoint"], "cli")

    def test_thinking_tokens_accumulate_and_thinking_lines_counts_presence(self):
        lines = [
            '{"type":"assistant","timestamp":"2026-08-12T09:00:00Z","message":{"role":"assistant","content":[{"type":"text","text":"a"}],"usage":{"input_tokens":1,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens_details":{"thinking_tokens":10}}}}',
            '{"type":"assistant","timestamp":"2026-08-12T09:01:00Z","message":{"role":"assistant","content":[{"type":"text","text":"b"}],"usage":{"input_tokens":1,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens_details":{"thinking_tokens":5}}}}',
            '{"type":"assistant","timestamp":"2026-08-12T09:02:00Z","message":{"role":"assistant","content":[{"type":"text","text":"c"}],"usage":{"input_tokens":1,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}',
        ]
        state = S._merge_lines(S._new_state(), lines)
        self.assertEqual(state["tokens"]["thinking"], 15)
        self.assertEqual(state["tokens"]["thinking_lines"], 2)     # only the 2 lines that carry the key

    def test_no_output_tokens_details_is_the_unknown_signature(self):
        # the pre-2026-08-12 transcript shape: out > 0 but thinking/thinking_lines stay 0 —
        # "unknown", distinguishable from "measured, genuinely zero reasoning".
        lines, _ = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        self.assertGreater(state["tokens"]["out"], 0)
        self.assertEqual(state["tokens"]["thinking"], 0)
        self.assertEqual(state["tokens"]["thinking_lines"], 0)

    def test_back_compat_old_registry_record_loads_and_refreshes_without_raising(self):
        S.refresh(self.env.cfg, days=30)
        path = S.registry_path(self.env.cfg)
        reg = S._load_registry(path)
        entry = reg[self.env.session_file]
        del entry["partial_state"]["entrypoint"]                       # simulate a pre-upgrade registry record
        del entry["partial_state"]["tokens"]["thinking"]
        del entry["partial_state"]["tokens"]["thinking_lines"]
        del entry["summary"]["entrypoint"]
        del entry["summary"]["tokens"]["thinking"]
        del entry["summary"]["tokens"]["thinking_lines"]
        entry["mtime"] = entry["mtime"] - 1                            # off the "unchanged, skip" fast path
        reg[self.env.session_file] = entry
        S._save_registry(path, reg)
        items = S.refresh(self.env.cfg, days=30)                       # must not raise
        s = next(s for s in items if s["session_id"] == "sess-1")
        self.assertIsNone(s["entrypoint"])
        self.assertEqual(s["tokens"]["thinking"], 0)
        self.assertEqual(s["tokens"]["thinking_lines"], 0)
        self.assertEqual(s["tokens"]["out"], 420)                      # totals preserved, not corrupted

    def test_subagent_tokens_carry_thinking_keys_and_stay_unsummed(self):
        lines, off = S._read_new_lines(self.env.session_file, 0)
        state = S._merge_lines(S._new_state(), lines)
        sub_path = os.path.join(os.path.dirname(self.env.session_file), self.env.session_id, "subagents", "agent-1.jsonl")
        open(sub_path, "a").write(
            '{"type":"assistant","timestamp":"2026-08-12T09:05:00Z","message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{"pattern":"z"}}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens_details":{"thinking_tokens":9}}}}\n')
        summary = S._finalize(state, self.env.session_file, {"alpha": self.env.alpha}, off)
        self.assertEqual(summary["subagent_tokens"]["thinking"], 9)
        self.assertEqual(summary["subagent_tokens"]["thinking_lines"], 1)
        self.assertEqual(summary["tokens"]["thinking"], 0)              # R3: never summed into the session total

class TestEntrypointBackfill(unittest.TestCase):
    """The real-world defect: entrypoint is incremental-parser-only, so a session whose byte
    offset already sits at EOF (i.e. every session parsed before entrypoint existed) can never
    see the line carrying it again. refresh() must backfill it with a bounded, one-time head
    read instead."""
    def setUp(self):
        self.env = Env()
    def tearDown(self):
        self.env.cleanup()

    def _prime_registry_with_entrypoint_then_strip(self, stored_entrypoint="__absent__"):
        # the file genuinely carries entrypoint; a normal refresh() would find it the ordinary
        # way (via _merge_lines) — then we edit the SAVED registry to look like it was written
        # before entrypoint existed (or already carries some other value), file untouched.
        open(self.env.session_file, "a").write(
            '{"type":"assistant","timestamp":"2026-08-10T09:03:30Z","sessionId":"%s","entrypoint":"sdk-py",'
            '"message":{"role":"assistant","content":[],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
            % self.env.session_id)
        S.refresh(self.env.cfg, days=30)
        path = S.registry_path(self.env.cfg)
        reg = S._load_registry(path)
        entry = reg[self.env.session_file]
        if stored_entrypoint == "__absent__":
            entry["partial_state"].pop("entrypoint", None)
            entry["summary"].pop("entrypoint", None)
            entry.pop("entrypoint_checked", None)     # a genuinely pre-upgrade record has no marker either
        else:
            entry["partial_state"]["entrypoint"] = stored_entrypoint
            entry["summary"]["entrypoint"] = stored_entrypoint
        S._save_registry(path, reg)
        return entry["summary"]

    def test_backfill_fills_entrypoint_for_a_cached_unchanged_record(self):
        # regression test for the defect found in the browser: 735 real sessions had `entrypoint`
        # stuck at None forever because their offset was already at EOF. This must go red if the
        # backfill is removed.
        self._prime_registry_with_entrypoint_then_strip()
        items = S.refresh(self.env.cfg, days=30)
        s = next(x for x in items if x["session_id"] == "sess-1")
        self.assertEqual(s["entrypoint"], "sdk-py")

    def test_backfill_does_not_disturb_offset_turns_or_tokens(self):
        before = self._prime_registry_with_entrypoint_then_strip()
        items = S.refresh(self.env.cfg, days=30)
        s = next(x for x in items if x["session_id"] == "sess-1")
        self.assertEqual(s["offset"], before["offset"])
        self.assertEqual(s["turns"], before["turns"])
        self.assertEqual(s["tokens"], before["tokens"])

    def test_backfill_respects_the_head_line_bound(self):
        entrypoint_line_idx = S._HEAD_LINES     # the first line index NOT scanned
        content = "".join('{"n":%d}\n' % i for i in range(entrypoint_line_idx)) + '{"entrypoint":"sdk-py"}\n'
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "far.jsonl")
            open(fp, "w").write(content)
            self.assertIsNone(S._backfill_entrypoint(fp))                          # guard on: not found
            with mock.patch.object(S, "_HEAD_LINES", entrypoint_line_idx + 1):
                self.assertEqual(S._backfill_entrypoint(fp), "sdk-py")             # guard relaxed: found

    def test_backfill_not_attempted_when_entrypoint_already_present(self):
        self._prime_registry_with_entrypoint_then_strip(stored_entrypoint="cli")
        # other unrelated session files in the fixture (e.g. the usage-history one) legitimately
        # still need backfilling; only OUR file must never reach _backfill_entrypoint.
        real = S._backfill_entrypoint
        def guarded(fp):
            if fp == self.env.session_file:
                raise AssertionError("must not be called: entrypoint already present")
            return real(fp)
        with mock.patch.object(S, "_backfill_entrypoint", side_effect=guarded):
            items = S.refresh(self.env.cfg, days=30)
        s = next(x for x in items if x["session_id"] == "sess-1")
        self.assertEqual(s["entrypoint"], "cli")            # stays "cli", not "sdk-py" read from the file

    def test_backfill_scanned_at_most_once_even_when_entrypoint_is_never_found(self):
        # regression test for the unbounded-retry defect: the fixture's own session file
        # genuinely never carries `entrypoint` anywhere. Without remembering the MISS (not just
        # a hit), refresh() re-opens and re-scans it on every single call, forever. Assert the
        # call COUNT, not a boolean -- a boolean would go green even for "still unbounded but
        # happens to be called fewer times in this particular run".
        calls = []
        real = S._backfill_entrypoint
        def counting(fp):
            if fp == self.env.session_file:
                calls.append(fp)
            return real(fp)
        with mock.patch.object(S, "_backfill_entrypoint", side_effect=counting):
            S.refresh(self.env.cfg, days=30)
            S.refresh(self.env.cfg, days=30)
            S.refresh(self.env.cfg, days=30)
            S.refresh(self.env.cfg, days=30)
        self.assertEqual(len(calls), 1)

    def test_rotated_file_gets_one_fresh_entrypoint_look_and_counters_are_not_corrupted(self):
        # a rotated/rewritten file (new content, old offset now past the new size) must not
        # stay stuck on a stale "already checked, absent" marker from its PREVIOUS incarnation
        # -- and the rotation's normal reparse-from-scratch behavior (offset/turns/tokens) must
        # be untouched by any of this.
        self._prime_registry_with_entrypoint_then_strip()          # marks the record "checked, absent" pre-rotation
        rotated = (
            '{"type":"user","timestamp":"2026-08-11T09:00:00Z","sessionId":"sess-1","entrypoint":"cli",'
            '"message":{"role":"user","content":[{"type":"text","text":"new content after rotation"}]}}\n'
        )
        open(self.env.session_file, "w").write(rotated)            # shorter than the old offset -> rotated/rewritten
        items = S.refresh(self.env.cfg, days=30)
        s = next(x for x in items if x["session_id"] == "sess-1")
        self.assertEqual(s["entrypoint"], "cli")                   # the fresh look finds the NEW file's own value
        self.assertEqual(s["turns"], 1)                            # one real user text line in the rotated content
        self.assertEqual(s["offset"], len(rotated.encode("utf-8")))

class TestRefreshTransaction(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.cleanup()

    def test_refresh_lock_covers_load_and_save(self):
        original_load, original_save = S._load_registry, S._save_registry
        checks = []

        def load(path):
            acquired = S._REFRESH_LOCK.acquire(False)
            checks.append(("load", not acquired))
            if acquired:
                S._REFRESH_LOCK.release()
            return original_load(path)

        def save(path, registry):
            acquired = S._REFRESH_LOCK.acquire(False)
            checks.append(("save", not acquired))
            if acquired:
                S._REFRESH_LOCK.release()
            return original_save(path, registry)

        with mock.patch.object(S, "_load_registry", side_effect=load), \
             mock.patch.object(S, "_save_registry", side_effect=save):
            self.assertTrue(S.refresh(self.env.cfg, days=30))
        self.assertEqual([name for name, _ in checks], ["load", "save"])
        self.assertTrue(all(locked for _, locked in checks))

    def test_refresh_serializes_entire_refresh_operation(self):
        class ProbeLock:
            def __init__(self):
                self.inner = threading.Lock()
                self.attempts = 0
                self.attempts_lock = threading.Lock()
                self.second_attempted = threading.Event()
                self.allow_second_acquire = threading.Event()

            def __enter__(self):
                with self.attempts_lock:
                    self.attempts += 1
                    attempt = self.attempts
                if attempt == 2:
                    self.second_attempted.set()
                    if not self.allow_second_acquire.wait(timeout=2):
                        raise AssertionError("second lock acquisition was not released")
                self.inner.acquire()
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.inner.release()

        probe = ProbeLock()
        entered = threading.Event()
        release = threading.Event()
        counters_lock = threading.Lock()
        active = 0
        max_active = 0
        errors = []

        def fake_refresh(*args, **kwargs):
            nonlocal active, max_active
            with counters_lock:
                active += 1
                max_active = max(max_active, active)
            entered.set()
            if not release.wait(timeout=2):
                raise AssertionError("first refresh was not released")
            with counters_lock:
                active -= 1
            return []

        def run():
            try:
                S.refresh(self.env.cfg, days=30)
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(S, "_REFRESH_LOCK", probe), \
             mock.patch.object(S, "_refresh", side_effect=fake_refresh):
            started = []
            first = threading.Thread(target=run)
            second = threading.Thread(target=run)
            try:
                first.start()
                started.append(first)
                self.assertTrue(entered.wait(timeout=1))
                second.start()
                started.append(second)
                self.assertTrue(probe.second_attempted.wait(timeout=1))
                self.assertTrue(probe.inner.locked())
                with counters_lock:
                    self.assertEqual(active, 1)
                    self.assertEqual(max_active, 1)
            finally:
                release.set()
                probe.allow_second_acquire.set()
                for thread in started:
                    thread.join(timeout=2)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertFalse(errors)
        self.assertEqual(max_active, 1)

    def test_save_ignores_legacy_tmp_symlink_and_cleans_unique_temp(self):
        path = S.registry_path(self.env.cfg)
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        legacy = path + ".tmp"
        sentinel = os.path.join(directory, "outside-sentinel")
        with open(sentinel, "w", encoding="utf-8") as f:
            f.write("untouched")
        os.symlink(sentinel, legacy)
        S._save_registry(path, {"x": {"summary": {"started": "now"}}})
        self.assertEqual(open(sentinel, encoding="utf-8").read(), "untouched")
        self.assertTrue(os.path.islink(legacy))
        self.assertFalse(any(name.startswith(".sessions-") for name in os.listdir(directory)))

    def test_save_cleans_unique_temp_when_replace_fails(self):
        path = S.registry_path(self.env.cfg)
        with mock.patch.object(S.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                S._save_registry(path, {})
        self.assertFalse(any(name.startswith(".sessions-") for name in os.listdir(os.path.dirname(path))))

    def test_save_closes_fd_and_cleans_temp_when_dump_fails(self):
        path = S.registry_path(self.env.cfg)
        real_mkstemp = S.tempfile.mkstemp
        captured = {}

        def capture_mkstemp(*args, **kwargs):
            fd, temp_path = real_mkstemp(*args, **kwargs)
            captured["fd"] = fd
            return fd, temp_path

        with mock.patch.object(S.tempfile, "mkstemp", side_effect=capture_mkstemp), \
             mock.patch.object(S.json, "dump", side_effect=OSError("dump failed")):
            with self.assertRaises(OSError):
                S._save_registry(path, {})
        with self.assertRaises(OSError):
            os.fstat(captured["fd"])
        self.assertFalse(any(name.startswith(".sessions-") for name in os.listdir(os.path.dirname(path))))


if __name__ == "__main__":
    unittest.main()
