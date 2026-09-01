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
