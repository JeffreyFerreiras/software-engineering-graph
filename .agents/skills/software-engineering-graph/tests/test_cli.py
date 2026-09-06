import json
import io
import sys
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

from graph_engine.cli import main
from graph_engine.contracts import ContractError
from graph_engine.evidence import canonical_ledger_artifact
from graph_engine.validator import canonical_collection_members, join_members
from graph_engine.state import StateError, StateStore

from tests.test_support import GraphCase


class UsageTests(GraphCase):
    def setUp(self):
        super().setUp()
        self.log = self.root / "private-session.jsonl"
        self.log.write_text("", encoding="utf-8")
        self.append("session_meta", {"id": "synthetic-session", "cwd": "PRIVATE_SOURCE_PATH"})
        self.context()

    def append(self, kind, payload):
        with self.log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": kind, "payload": payload}) + "\n")

    def context(self, model="gpt-6-astra", effort="medium"):
        self.append("turn_context", {"model": model, "effort": effort})

    def tokens(self, input_count, output_count, last=None, **optional):
        counters = {"input_tokens": input_count, "output_tokens": output_count,
                    "total_tokens": input_count + output_count, **optional}
        self.append("event_msg", {"type": "token_count", "info": {
            "total_token_usage": counters, "last_token_usage": counters if last is None else {
                "input_tokens": last[0], "output_tokens": last[1], "total_tokens": sum(last)},
        }})

    def usage(self, action, op, *arguments):
        return self.graphctl("record", "usage", "--run-id", "RUN-1", "--action", action,
                             "--session-log", str(self.log), "--op-id", op, *arguments)

    def bind(self, phase="scoping", op="bind-usage", checkpoint=None, branch=None):
        arguments = []
        if branch:
            arguments.extend(["--branch-id", branch["branch_id"], "--attempt-id", branch["attempt_id"]])
        else:
            arguments.extend(["--phase", phase, "--generation", "0"])
        if checkpoint:
            arguments.extend(["--start-offset", str(checkpoint["offset"]), "--source-id", checkpoint["source_id"],
                              "--prefix-sha256", checkpoint["prefix_sha256"]])
        return self.usage("bind", op, *arguments)

    def collect(self, binding, op="collect-usage", close=False):
        return self.usage("close" if close else "collect", op, "--binding-id", binding)

    def test_checkpoint_before_policy_or_run_and_historical_bind(self):
        from graph_engine.cli import execute
        self.tokens(100, 20)
        before, code = execute(["usage", "checkpoint", "--session-log", str(self.log)], self.store)
        self.assertEqual(code, 0)
        self.assertEqual(before["checkpoint_schema_version"], 1)
        self.assertNotIn("synthetic-session", json.dumps(before))
        self.tokens(160, 30, last=(60, 10))
        self.initialize()
        result = self.bind(checkpoint=before)
        self.assertEqual(result["usage"]["observed_totals"]["total_tokens"], 70)
        self.assertEqual(result["usage"]["model_efforts"]["gpt-6-astra/medium"]["observed_totals"]["total_tokens"], 70)
        self.assertTrue(result["usage"]["running"])
        self.assertIsNone(result["usage"]["complete_totals"])

    def test_default_baseline_deduplicates_collects_and_replay_after_append(self):
        self.tokens(100, 20)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(120, 25, last=(20, 5), cached_input_tokens=30, reasoning_output_tokens=3)
        result = self.collect(binding)
        self.assertEqual(result["usage"]["observed_totals"]["total_tokens"], 25)
        self.tokens(120, 25, last=(20, 5), cached_input_tokens=30, reasoning_output_tokens=3)
        again = self.collect(binding, "collect-again")
        self.assertEqual(again["usage"]["observed_totals"]["total_tokens"], 25)
        self.tokens(140, 30, last=(20, 5))
        replay = self.collect(binding)
        self.assertEqual(replay["code"], "REPLAYED")
        self.assertEqual(replay["usage"]["observed_totals"]["total_tokens"], 25)
        with self.assertRaisesRegex(StateError, "OPERATION_CONFLICT"):
            self.collect(binding, close=True)
        closed = self.collect(binding, "close", close=True)
        self.assertEqual(closed["usage"]["observed_totals"]["total_tokens"], 50)
        self.assertEqual(closed["usage"]["open_bindings"], [])

    def test_source_start_subsets_cache_write_and_unknown_observed_context(self):
        from graph_engine.ids import sha256_bytes
        self.tokens(100, 20, cached_input_tokens=40, reasoning_output_tokens=10, cache_write_tokens=12)
        self.initialize()
        initial = {"offset": 0, "source_id": sha256_bytes(b"synthetic-session"), "prefix_sha256": sha256_bytes(b"")}
        binding = self.bind(checkpoint=initial)["binding_id"]
        result = self.collect(binding, close=True)["usage"]
        self.assertEqual(result["observed_totals"], {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                         "cached_input_tokens": 40, "reasoning_output_tokens": 10, "cache_write_tokens": 12})
        self.assertEqual(result["phases"]["scoping"]["coverage"], "complete")
        self.assertIsNone(result["phases"]["implementation"]["observed_totals"])
        self.context("UNCONTROLLED_MODEL_SECRET", "UNCONTROLLED_EFFORT_SECRET")
        binding = self.bind("implementation", "bind-next")["binding_id"]
        self.tokens(120, 30, last=(20, 10))
        result = self.collect(binding, "close-next", close=True)["usage"]
        self.assertIn("unknown/unknown", result["model_efforts"])
        self.assertNotIn("UNCONTROLLED", json.dumps(result))

    def test_phase_boundaries_all_five_and_effort_pairs(self):
        from graph_engine.usage import PHASES
        self.tokens(10, 1)
        self.initialize()
        count = 10
        for index, phase in enumerate(PHASES):
            effort = "high" if index % 2 else "medium"
            self.context(effort=effort)
            binding = self.bind(phase, "bind-" + phase)["binding_id"]
            count += 10
            self.tokens(count, index + 2, last=(10, 1))
            result = self.collect(binding, "close-" + phase, close=True)["usage"]
            self.assertEqual(result["phases"][phase]["observed_totals"]["total_tokens"], 11)
        self.assertEqual(result["observed_totals"]["total_tokens"], 55)
        self.assertEqual(result["model_efforts"]["gpt-6-astra/medium"]["observed_totals"]["total_tokens"], 33)
        self.assertEqual(result["model_efforts"]["gpt-6-astra/high"]["observed_totals"]["total_tokens"], 22)

    def test_overlap_rejected_and_cross_boundary_increment_not_double_counted(self):
        self.tokens(10, 1)
        self.initialize()
        binding = self.bind()["binding_id"]
        with self.assertRaisesRegex(StateError, "USAGE_INTERVAL_OVERLAP"):
            self.bind("implementation", "overlap")
        self.tokens(20, 2, last=(10, 1))
        self.collect(binding, "close", close=True)
        binding = self.bind("implementation", "next")["binding_id"]
        self.tokens(40, 4, last=(30, 3))
        result = self.collect(binding, "close-next", close=True)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 33)
        self.assertEqual(result["unattributed"]["observed_totals"]["total_tokens"], 22)
        self.assertEqual(result["phases"]["implementation"]["coverage"], "partial")

    def test_ambiguous_prerun_bridge_excluded_and_reset_keeps_prior_usage(self):
        self.tokens(10, 1)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(30, 3, last=(30, 3))
        result = self.collect(binding)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 0)
        self.assertIn("prefix_gap", result["diagnostics"])
        self.tokens(40, 4, last=(10, 1))
        self.tokens(5, 1)
        self.tokens(15, 2, last=(10, 1))
        result = self.collect(binding, "after-reset", close=True)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 22)
        self.assertIn("counter_reset", result["diagnostics"])

    def test_branch_attempt_association_and_resumed_source(self):
        self.tokens(10, 1)
        self.initialize()
        branch = self.claim_raw()
        binding = self.bind(branch=branch)["binding_id"]
        self.tokens(20, 2, last=(10, 1))
        result = self.collect(binding, close=True)["usage"]
        self.assertEqual(result["attempts"][branch["attempt_id"]]["observed_totals"]["total_tokens"], 11)
        self.assertEqual(result["agents"][branch["branch_id"]]["observed_totals"]["total_tokens"], 11)
        self.log = self.root / "resumed.jsonl"
        self.append("session_meta", {"id": "resumed-session"})
        self.context()
        self.tokens(0, 0)
        binding = self.bind(op="resume-bind", branch=branch)["binding_id"]
        self.tokens(10, 1)
        result = self.collect(binding, "resume-close", close=True)["usage"]
        self.assertEqual(result["attempts"][branch["attempt_id"]]["observed_totals"]["total_tokens"], 22)
        self.assertEqual(result["missing_executed_attempts"], [])

    def test_missing_metadata_old_schema_and_late_aborted_run(self):
        self.initialize()
        initial = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(initial["state_schema_version"], 6)
        self.assertEqual(initial["usage"]["coverage"], "unavailable")
        self.assertIsNone(initial["usage"]["observed_totals"])
        branch = self.claim_raw()
        result = self.graphctl("status", "--run-id", "RUN-1")["usage"]
        self.assertIn(branch["attempt_id"], result["missing_executed_attempts"])
        self.tokens(10, 1)
        binding = self.bind()["binding_id"]
        self.graphctl("abort", "--run-id", "RUN-1", "--reason-code", "stop", "--authority-ref", "authority:test", "--op-id", "abort")
        self.tokens(20, 2, last=(10, 1))
        result = self.collect(binding, close=True)
        self.assertEqual(result["usage"]["observed_totals"]["total_tokens"], 11)
        self.assertFalse(result["usage"]["running"])
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["status"], "aborted")

    def test_checkpoint_mismatch_and_arguments_leave_revision_unchanged(self):
        from graph_engine.usage import checkpoint
        self.tokens(10, 1)
        saved = checkpoint(str(self.log))
        self.initialize()
        revision = self.graphctl("status", "--run-id", "RUN-1")["state_revision"]
        for changed in ({**saved, "offset": 1}, {**saved, "source_id": "a" * 64},
                        {**saved, "prefix_sha256": "b" * 64}, {**saved, "offset": 1 << 63}):
            with self.assertRaises(StateError):
                self.bind(checkpoint=changed)
        with self.assertRaises(StateError):
            self.usage("bind", "bad", "--phase", "scoping", "--generation", "0", "--start-offset", "0")
        with self.assertRaises(ContractError):
            self.bind(checkpoint={**saved, "prefix_sha256": "PRIVATE_SECRET"})
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["state_revision"], revision)

    def test_rewritten_or_truncated_prefix_preserves_observed_usage(self):
        self.tokens(10, 1)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(20, 2, last=(10, 1))
        self.collect(binding)
        original = self.log.read_bytes()
        self.log.write_bytes(original.replace(b"PRIVATE_SOURCE_PATH", b"ALTERED_SOURCEPATHX"))
        result = self.collect(binding, "rewritten")["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 11)
        self.assertIn("prefix_changed", result["diagnostics"])
        self.log.write_bytes(original)
        self.tokens(30, 3, last=(10, 1))
        result = self.collect(binding, "restored", close=True)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 11)

    def test_corrupt_optional_event_does_not_block_graph_status(self):
        self.tokens(10, 1)
        self.initialize()
        self.bind()
        with self.store.open_run("albanian-live-translate", "RUN-1") as connection:
            connection.execute("UPDATE events SET detail_json=? WHERE event_type='usage.observation'",
                               (json.dumps({"PRIVATE_SECRET": "PRIVATE_SOURCE_PATH"}),))
            connection.commit()
        result = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(result["usage"]["diagnostics"], ["invalid_usage_state"])
        self.assertNotIn("PRIVATE", json.dumps(result["usage"]))

    def test_metadata_limits_malformed_nested_and_unfinished_records_are_private(self):
        from graph_engine import usage
        self.tokens(10, 1)
        self.initialize()
        binding = self.bind()["binding_id"]
        with self.log.open("ab") as handle:
            handle.write(b'{"PRIVATE_CREDENTIAL":"secret",broken}\n')
            handle.write(b'[' * 30 + b'"PRIVATE_NESTED_SECRET"' + b']' * 30 + b'\n')
        self.context("PRIVATE_MODEL", "PRIVATE_EFFORT")
        self.tokens(20, 2, last=(10, 1))
        with self.log.open("ab") as handle:
            handle.write(b'{"type":"event_msg","payload":')
        result = self.collect(binding)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 11)
        self.assertIn("malformed_record", result["diagnostics"])
        with self.store.open_run("albanian-live-translate", "RUN-1") as connection:
            saved = [row[0] for row in connection.execute("SELECT detail_json FROM events WHERE event_type LIKE '%usage%'")]
            saved.extend(row[0] for row in connection.execute("SELECT response_json FROM operations WHERE operation_id IN ('bind-usage','collect-usage')"))
        text = json.dumps(saved) + json.dumps(result)
        for forbidden in ("PRIVATE_", "synthetic-session", str(self.log), "secret"):
            self.assertNotIn(forbidden, text)
        with patch.object(usage, "MAX_BYTES", 1):
            result = self.collect(binding, "limited")["usage"]
            self.assertIn("source_limit", result["diagnostics"])
            self.assertEqual(result["observed_totals"]["total_tokens"], 11)
        with patch.object(usage, "MAX_RECORDS", 2):
            source = usage.read_source(str(self.log))
            self.assertIn("record_limit", {code for _, code in source.diagnostics})
        with patch.object(usage, "CHUNK_BYTES", 40):
            source = usage.read_source(str(self.log))
            self.assertIn("record_limit", {code for _, code in source.diagnostics})

    def test_invalid_required_counters_never_become_zero_or_complete(self):
        from graph_engine.usage import read_source
        invalid = [
            {"input_tokens": True, "output_tokens": 0, "total_tokens": 1},
            {"input_tokens": -1, "output_tokens": 2, "total_tokens": 1},
            {"input_tokens": 10, "output_tokens": 2, "total_tokens": 13},
            {"input_tokens": 1 << 63, "output_tokens": 0, "total_tokens": 1 << 63},
            {"input_tokens": 10, "total_tokens": 10},
        ]
        for counters in invalid:
            self.append("event_msg", {"type": "token_count", "info": {"total_token_usage": counters}})
        self.assertEqual(read_source(str(self.log)).snapshots, [])
        self.initialize()
        binding = self.bind()["binding_id"]
        result = self.collect(binding, close=True)["usage"]
        self.assertEqual(result["coverage"], "unavailable")
        self.assertIsNone(result["observed_totals"])

    def test_optional_discontinuity_does_not_discard_required_totals(self):
        self.tokens(100, 20, cached_input_tokens=30, reasoning_output_tokens=10, cache_write_tokens=12)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(120, 25, last=(20, 5), cached_input_tokens=10, reasoning_output_tokens=26, cache_write_tokens=15)
        result = self.collect(binding, close=True)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 25)
        self.assertIsNone(result["observed_totals"]["cached_input_tokens"])
        self.assertIsNone(result["observed_totals"]["reasoning_output_tokens"])
        self.assertEqual(result["observed_totals"]["cache_write_tokens"], 3)
        self.assertEqual(set(result["metric_partial"]), {"cached_input_tokens", "reasoning_output_tokens"})

    def test_multiple_contexts_are_unattributed_without_guessing_planned_model(self):
        self.tokens(100, 20)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.context(effort="medium")
        self.context(effort="high")
        self.tokens(120, 25, last=(20, 5))
        result = self.collect(binding, close=True)["usage"]
        self.assertEqual(result["unattributed"]["observed_totals"]["total_tokens"], 25)
        self.assertEqual(set(result["models"]), {"unknown"})
        self.assertIn("ambiguous_increment", result["diagnostics"])

    def test_unfinished_record_is_collected_once_after_newline(self):
        self.tokens(10, 1)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(20, 2, last=(10, 1))
        complete = self.log.read_bytes()
        self.log.write_bytes(complete[:-1])
        result = self.collect(binding)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 0)
        self.log.write_bytes(complete)
        result = self.collect(binding, "complete-line", close=True)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 11)

    def test_opened_source_identity_change_and_symlink_are_rejected(self):
        import os
        from graph_engine import usage
        original_stat = os.fstat

        def different_identity(descriptor):
            fields = list(original_stat(descriptor))
            fields[1] += 1
            return os.stat_result(fields)

        with patch.object(usage.os, "fstat", side_effect=different_identity):
            source = usage.read_source(str(self.log))
        self.assertIsNone(source.source_id)
        self.assertIn("source_changed", {code for _, code in source.diagnostics})
        linked = self.root / "linked-session"
        try:
            linked.symlink_to(self.log)
        except OSError:
            # Windows without symlink privilege still exercises the reparse-component guard.
            with patch.object(usage, "_safe_components", side_effect=StateError("USAGE_SOURCE_UNSAFE")):
                source = usage.read_source(str(self.log))
        else:
            source = usage.read_source(str(linked))
        self.assertIn("source_unsafe", {code for _, code in source.diagnostics})

    def test_checkpoint_replacement_same_offset_requires_identity_and_prefix(self):
        from graph_engine.usage import checkpoint
        self.tokens(10, 1)
        saved = checkpoint(str(self.log))
        original = self.log.read_bytes()
        self.initialize()
        self.log.write_bytes(original.replace(b"synthetic-session", b"different-session"))
        with self.assertRaisesRegex(StateError, "USAGE_CHECKPOINT_MISMATCH"):
            self.bind(checkpoint=saved)
        self.log.write_bytes(original.replace(b"PRIVATE_SOURCE_PATH", b"CHANGED_SOURCE_PATH"))
        with self.assertRaisesRegex(StateError, "USAGE_CHECKPOINT_MISMATCH"):
            self.bind(checkpoint=saved)
        self.log.write_bytes(original)
        binding = self.bind(checkpoint=saved)["binding_id"]
        self.log.write_bytes(original[:60])
        result = self.collect(binding, close=True)["usage"]
        self.assertEqual(result["coverage"], "partial")
        self.assertIsNone(result["complete_totals"])

    def test_concurrent_candidate_cannot_overwrite_newer_checkpoint(self):
        self.tokens(10, 1)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(20, 2, last=(10, 1))
        original_mutate = self.store.mutate

        def interleave(*args, **kwargs):
            with patch.object(self.store, "mutate", original_mutate):
                self.collect(binding, "winner")
            return original_mutate(*args, **kwargs)

        with patch.object(self.store, "mutate", side_effect=interleave):
            with self.assertRaisesRegex(StateError, "USAGE_STALE_CHECKPOINT"):
                self.collect(binding, "loser")
        result = self.graphctl("status", "--run-id", "RUN-1")["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 11)

    def test_retry_has_distinct_usage_attempt_without_recounting_first(self):
        self.tokens(10, 1)
        self.initialize()
        first = self.claim_raw()
        binding = self.bind(branch=first)["binding_id"]
        self.tokens(20, 2, last=(10, 1))
        self.collect(binding, close=True)
        self.record(first, {"schema_version": 1, "run_id": "RUN-1", "branch_id": first["branch_id"],
                           "status": "failed", "output_kind": "impact_map", "failure_code": "INSUFFICIENT_EVIDENCE",
                           "evidence": [self.repo_artifact("failure", "retry-usage-failure")]})
        self.graphctl("record", "retry", "--run-id", "RUN-1", "--branch-id", first["branch_id"],
                      "--reason-code", "RETRY", "--op-id", "retry")
        second = self.claim_raw()
        binding = self.bind(op="second-bind", branch=second)["binding_id"]
        self.tokens(30, 3, last=(10, 1))
        result = self.collect(binding, "second-close", close=True)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 22)
        self.assertEqual(result["attempts"][first["attempt_id"]]["observed_totals"]["total_tokens"], 11)
        self.assertEqual(result["attempts"][second["attempt_id"]]["observed_totals"]["total_tokens"], 11)

    def test_missing_resumed_session_remains_a_gap_after_other_interval_closes(self):
        self.tokens(10, 1)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(20, 2, last=(10, 1))
        self.collect(binding, close=True)
        self.log = self.root / "PRIVATE_MISSING_SESSION"
        missing = self.bind(op="missing-resume")
        self.assertEqual(missing["code"], "USAGE_UNAVAILABLE")
        self.assertIsNone(missing["checkpoint"])
        result = self.collect(missing["binding_id"], "missing-close", close=True)["usage"]
        self.assertEqual(result["phases"]["scoping"]["coverage"], "partial")
        self.assertEqual(result["observed_totals"]["total_tokens"], 11)
        self.assertIn("source_unavailable", result["diagnostics"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_observed_cache_write_spelling_and_alias_precedence(self):
        from graph_engine.usage import read_source
        self.tokens(100, 20, cache_write_input_tokens=12, cache_write_tokens=99)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(120, 25, last=(20, 5), cache_write_input_tokens=15, cache_write_tokens=199)
        result = self.collect(binding)["usage"]
        self.assertEqual(result["observed_totals"]["cache_write_tokens"], 3)
        self.tokens(140, 30, last=(20, 5), cache_write_input_tokens="invalid", cache_write_tokens=200)
        self.assertIsNone(read_source(str(self.log)).snapshots[-1]["counters"]["cache_write_tokens"])
        result = self.collect(binding, "invalid-preferred", close=True)["usage"]
        self.assertEqual(result["observed_totals"]["total_tokens"], 50)
        self.assertIsNone(result["observed_totals"]["cache_write_tokens"])
        self.assertIn("cache_write_tokens", result["metric_partial"])

    def test_unbound_retry_keeps_agent_role_and_generation_totals_partial(self):
        self.tokens(10, 1)
        self.initialize()
        first = self.claim_raw()
        binding = self.bind(branch=first)["binding_id"]
        self.tokens(20, 2, last=(10, 1))
        self.collect(binding, close=True)
        self.record(first, {"schema_version": 1, "run_id": "RUN-1", "branch_id": first["branch_id"],
                           "status": "failed", "output_kind": "impact_map", "failure_code": "INSUFFICIENT_EVIDENCE",
                           "evidence": [self.repo_artifact("failure", "unbound-retry-failure")]})
        self.graphctl("record", "retry", "--run-id", "RUN-1", "--branch-id", first["branch_id"],
                      "--reason-code", "RETRY", "--op-id", "unbound-retry")
        second = self.claim_raw()
        result = self.graphctl("status", "--run-id", "RUN-1")["usage"]
        for dimension, key in (("agents", first["branch_id"]), ("roles", first["role"]), ("generations", "0")):
            summary = result[dimension][key]
            self.assertEqual(summary["coverage"], "partial")
            self.assertEqual(summary["observed_totals"]["total_tokens"], 11)
            self.assertIsNone(summary["complete_totals"])
            self.assertIn(second["attempt_id"], summary["missing_executed_attempts"])
        self.assertEqual(set(result["models"]), {"gpt-6-astra"})
        for summary in (result["models"]["gpt-6-astra"], result["efforts"]["medium"], result["model_efforts"]["gpt-6-astra/medium"]):
            self.assertEqual(summary["attribution_scope"], "observed_intervals_only")
            self.assertEqual(summary["association_coverage"], "partial")

    def test_supervisor_group_keeps_missing_primary_phase_visible(self):
        self.tokens(10, 1)
        self.initialize()
        binding = self.bind("implementation")["binding_id"]
        self.tokens(20, 2, last=(10, 1))
        result = self.collect(binding, close=True)["usage"]
        for summary in (result["roles"]["supervisor"], result["generations"]["0"]):
            self.assertEqual(summary["coverage"], "partial")
            self.assertEqual(summary["observed_totals"]["total_tokens"], 11)
            self.assertIsNone(summary["complete_totals"])
            self.assertEqual(summary["missing_primary_phases"], ["scoping"])

    def test_raced_nonregular_source_is_opened_nonblocking_and_rejected(self):
        import os
        import stat
        from graph_engine import usage
        original_open, original_stat = os.open, os.fstat
        nonblocking = getattr(os, "O_NONBLOCK", 0x40000000)
        observed_flags = []

        def capture_open(path, flags):
            observed_flags.append(flags)
            # A synthetic flag on Windows is removed before the real regular-file
            # open; fstat below supplies the raced FIFO without opening a pipe.
            return original_open(path, flags & ~nonblocking)

        def fifo_stat(descriptor):
            fields = list(original_stat(descriptor))
            fields[0] = stat.S_IFIFO | 0o600
            return os.stat_result(fields)

        with patch.object(usage.os, "O_NONBLOCK", nonblocking, create=True), \
                patch.object(usage.os, "open", side_effect=capture_open), \
                patch.object(usage.os, "fstat", side_effect=fifo_stat):
            source = usage.read_source(str(self.log))
        self.assertEqual(len(observed_flags), 1)
        self.assertTrue(observed_flags[0] & nonblocking)
        self.assertIsNone(source.source_id)
        self.assertEqual(source.diagnostics, [(0, "source_changed")])

    def test_large_valid_counters_preserve_exact_aggregate_and_structured_cli_output(self):
        from graph_engine.usage import MAX_INTEGER
        self.tokens(0, 0)
        self.initialize()
        binding = self.bind()["binding_id"]
        self.tokens(10, 0)
        self.collect(binding)
        self.tokens(0, 0)
        self.tokens(MAX_INTEGER, 0)
        stream = io.StringIO()
        with patch("graph_engine.cli.StateStore", return_value=self.store), redirect_stdout(stream):
            code = main(["--repo", str(self.repo), "record", "usage", "--run-id", "RUN-1",
                         "--action", "close", "--binding-id", binding, "--session-log", str(self.log),
                         "--op-id", "large-close"])
        self.assertEqual(code, 0)
        result = json.loads(stream.getvalue())
        self.assertTrue(result["ok"])
        self.assertNotIn("Traceback", stream.getvalue())
        for summary in (result["usage"], result["usage"]["phases"]["scoping"], result["usage"]["model_efforts"]["gpt-6-astra/medium"]):
            self.assertEqual(summary["observed_totals"]["input_tokens"], MAX_INTEGER + 10)
            self.assertEqual(summary["observed_totals"]["output_tokens"], 0)
            self.assertEqual(summary["observed_totals"]["total_tokens"], MAX_INTEGER + 10)
            self.assertEqual(summary["coverage"], "partial")
            self.assertIsNone(summary["complete_totals"])
            self.assertIn("counter_reset", summary["diagnostics"])
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["usage"]["observed_totals"]["total_tokens"], MAX_INTEGER + 10)


class CliGoldenTraceTests(GraphCase):
    def setUp(self):
        super().setUp()
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["required_checks"]["repo-check"]["argv"] = [sys.executable, "-c", "import sys; sys.exit(0)"]
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.policy_bytes = policy_path.read_bytes()

    def _design_to_reviews(self, mode="delivery", route="full_delivery"):
        self.initialize(mode, route)
        self.impact(route)
        tech = self.claim()
        self.assertEqual(tech["node_key"], "tech_lead")
        self.success(tech)
        self.advance("design_inputs")

    def _record_design_review(self, decision, finding=None):
        architect = self.claim()
        self.assertEqual(architect["node_key"], "architect")
        disposition = {"BLOCK": "block", "REVISE": "revise"}.get(decision)
        findings = [] if finding is None else [{"finding_id": finding, "disposition": disposition}]
        self.success(architect, decision, findings)
        self.advance("design_collection")

    def test_collection_size_boundary_is_atomic_and_non_echoing(self):
        tags = ["security_privacy"]

        def configure_limit(maximum):
            policy_path = self.repo / ".codex" / "engineering-graph.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["artifact_kinds"]["collection"]["max_bytes"] = maximum
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            self.policy_bytes = policy_path.read_bytes()

        def ready_collection():
            self.initialize(tags=tags)
            self.impact("full_delivery", tags)
            tech = self.claim()
            self.success(tech)
            self.advance("design_inputs")
            finding_ids = []
            for index in range(2):
                branch = self.claim()
                finding_id = f"REV-{index + 100:03d}" + (str(index + 1) * 512)
                finding_ids.append(finding_id)
                self.success(branch, "APPROVE", [{"finding_id": finding_id, "disposition": "approve"}])
            join = self.open_join("design_collection")
            database = self.store.db_path("albanian-live-translate", "RUN-1")
            with self.store.connect(database) as connection:
                members = join_members(connection, join["join_id"])
                frozen = canonical_collection_members(connection, members)
                wrapper_sizes = [
                    connection.execute(
                        "SELECT size_bytes FROM artifacts WHERE ref=?",
                        (f"ledger:{member['branch_id']}#sha256={member['result_digest']}",),
                    ).fetchone()["size_bytes"]
                    for member in members
                ]
            manifest = {
                "schema_version": 1, "kind": "collection",
                "join_id": join["join_id"], "members": frozen,
            }
            return canonical_ledger_artifact(join["join_id"], "collection", manifest), wrapper_sizes, finding_ids

        baseline, wrapper_sizes, finding_ids = ready_collection()
        self.assertEqual(len(wrapper_sizes), 2)
        self.assertTrue(all(size <= 256 * 1024 for size in wrapper_sizes))

        self.tearDown()
        self.setUp()
        configure_limit(baseline.size_bytes)
        at_limit, _, _ = ready_collection()
        self.assertEqual(at_limit.size_bytes, baseline.size_bytes)
        design_join = self.open_join("design_collection")
        self.advance("design_collection")
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            persisted = connection.execute(
                "SELECT size_bytes FROM artifacts WHERE kind='collection' AND ref LIKE ?",
                ("ledger:" + design_join["join_id"] + "#%",),
            ).fetchone()
        self.assertEqual(persisted["size_bytes"], baseline.size_bytes)

        self.tearDown()
        self.setUp()
        configure_limit(baseline.size_bytes - 1)
        over_limit, _, finding_ids = ready_collection()
        self.assertEqual(over_limit.size_bytes, baseline.size_bytes)
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        revision = self.graphctl("status", "--run-id", "RUN-1")["state_revision"]
        with self.assertRaises(ContractError) as captured:
            self.advance("design_collection")
        self.assertEqual((captured.exception.field, captured.exception.code), ("artifact_ref", "FILE_TOO_LARGE"))
        self.assertEqual(str(captured.exception), "artifact_ref:FILE_TOO_LARGE")
        self.assertNotIn(finding_ids[0], str(captured.exception))
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual((status["status"], status["state_revision"]), ("active", revision))
        with self.store.connect(database) as connection:
            artifact_count = connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE kind='collection' AND ref LIKE ?",
                ("ledger:" + self.open_join("design_collection")["join_id"] + "#%",),
            ).fetchone()[0]
            stored_join = connection.execute(
                "SELECT status,result_json FROM joins WHERE join_key='design_collection'"
            ).fetchone()
        self.assertEqual(artifact_count, 0)
        self.assertEqual((stored_join["status"], stored_join["result_json"]), ("open", None))

    def _research_started(self):
        self.initialize("delivery", "full_delivery")
        self.impact("full_delivery")
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(status["next_action"]["kind"], "record_fanout_assessment")
        self.assertEqual(status["next_action"]["stage"], "research")
        fanout = next(item for item in status["fanouts"] if item["stage"] == "research")
        self.assess_fanout(fanout["fanout_id"])
        return fanout

    def _failed_research(self, branch, label):
        evidence = self.repo_artifact("failure", label)
        self.record(branch, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": branch["branch_id"],
            "status": "failed", "output_kind": "evidence_manifest",
            "failure_code": "RESEARCH_FAILURE", "evidence": [evidence],
        })

    def test_design_routes_gate_tech_lead_on_bounded_research_collection(self):
        fanout = self._research_started()
        status = self.graphctl("status", "--run-id", "RUN-1")
        research = [branch for branch in status["branches"] if branch["stage"] == "research"]
        self.assertEqual(
            {(branch["node_key"], branch["role"], branch["generation"], branch["status"], branch["model"], branch["reasoning_effort"]) for branch in research},
            {
                ("design_research_architecture", "impact_mapper", 0, "ready", "gpt-5.6-luna", "max"),
                ("design_research_validation", "impact_mapper", 0, "ready", "gpt-5.6-luna", "max"),
            },
        )
        self.assertFalse(any(branch["node_key"] == "tech_lead" for branch in status["branches"]))
        first = self.claim_raw()
        second = self.claim_raw()
        self.assertEqual(
            {first["node_key"], second["node_key"]},
            {"design_research_architecture", "design_research_validation"},
        )
        self.success(first)
        self.success(second)
        sealed = self.advance("research_collection")
        self.assertEqual(sealed["outcome"], "RESEARCH_SEALED")
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(
            [(branch["node_key"], branch["generation"], branch["status"]) for branch in status["branches"] if branch["node_key"] == "tech_lead"],
            [("tech_lead", 0, "ready")],
        )
        tech = self.claim_raw()
        self.assertEqual({item["kind"] for item in tech["inputs"]}, {
            "branch_result", "collection", "evidence_manifest", "task_brief",
        })
        collection = next(item for item in tech["inputs"] if item["kind"] == "collection")
        self.assertEqual(collection["content"]["join_id"], next(
            join["join_id"] for join in status["joins"] if join["join_key"] == "research_collection"
        ))

    def test_retryable_research_failure_requires_retry_before_collection_seal(self):
        self._research_started()
        first = self.claim_raw()
        second = self.claim_raw()
        self._failed_research(first, "research-retryable-failure")
        self.success(second)
        join = self.open_join("research_collection")
        validation = self.graphctl(
            "join", "validate", "--run-id", "RUN-1", "--join-id", join["join_id"],
        )
        self.assertEqual(validation["code"], "RETRY_REQUIRED")
        with self.assertRaisesRegex(StateError, "RETRY_REQUIRED"):
            self.advance("research_collection")
        self.graphctl(
            "record", "retry", "--run-id", "RUN-1", "--branch-id", first["branch_id"],
            "--reason-code", "RETRY", "--op-id", "research-retry-one",
        )
        retried = self.claim_raw()
        self.assertEqual(retried["branch_id"], first["branch_id"])
        self.success(retried)
        sealed = self.advance("research_collection")
        self.assertEqual(sealed["outcome"], "RESEARCH_SEALED")
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(
            [(branch["node_key"], branch["generation"], branch["status"])
             for branch in status["branches"] if branch["node_key"] == "tech_lead"],
            [("tech_lead", 0, "ready")],
        )

    def test_research_result_decisions_and_findings_are_atomic_and_forbidden(self):
        fanout = self._research_started()
        branch = self.claim_raw()
        output = self.repo_artifact("evidence_manifest", "research-output")
        evidence = self.repo_artifact("finding", "research-evidence")
        database = self.store.db_path("albanian-live-translate", "RUN-1")

        def invalid(extra):
            value = {
                "schema_version": 1, "run_id": "RUN-1", "branch_id": branch["branch_id"],
                "status": "succeeded", "output_kind": "evidence_manifest",
                "artifact_ref": output, "evidence": [evidence], "findings": [],
            }
            value.update(extra)
            return value

        for index, (extra, code) in enumerate(((
            {"decision": "APPROVE"}, "DECISION_FORBIDDEN",
        ), (
            {"findings": [{"finding_id": "ARCH-001", "disposition": "approve"}]},
            "FINDINGS_FORBIDDEN",
        ))):
            with self.subTest(code=code):
                with self.store.connect(database) as connection:
                    before = connection.execute("SELECT state_revision FROM runs").fetchone()[0]
                    artifact_count = connection.execute(
                        "SELECT COUNT(*) FROM artifacts WHERE run_id=?", ("RUN-1",)
                    ).fetchone()[0]
                with self.assertRaisesRegex(ContractError, code):
                    self.record(branch, invalid(extra))
                with self.store.connect(database) as connection:
                    current = connection.execute(
                        "SELECT nodes.status,runs.state_revision,nodes.result_json FROM nodes JOIN runs ON runs.run_id=nodes.run_id WHERE nodes.branch_id=?",
                        (branch["branch_id"],),
                    ).fetchone()
                    self.assertEqual((current["status"], current["state_revision"]), ("running", before))
                    self.assertIsNone(current["result_json"])
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM artifacts WHERE run_id=?", ("RUN-1",)).fetchone()[0],
                        artifact_count,
                    )
        self.success(branch)

    def test_persisted_research_evidence_is_reverified_before_status(self):
        self._research_started()
        branch = self.claim_raw()
        self.success(branch)
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            result_row = connection.execute(
                "SELECT result_json FROM nodes WHERE branch_id=?", (branch["branch_id"],)
            ).fetchone()
            result = json.loads(result_row["result_json"])
            connection.execute(
                "DELETE FROM artifacts WHERE ref=?", (result["evidence"][0]["ref"],)
            )
            connection.commit()
        with self.assertRaisesRegex(StateError, "TERMINAL_RESULT_INVALID"):
            self.graphctl("status", "--run-id", "RUN-1")

    def test_exhausted_mandatory_research_blocks_without_creating_tech_lead(self):
        fanout = self._research_started()
        first = self.claim_raw()
        second = self.claim_raw()
        self._failed_research(first, "research-failure-one")
        self._failed_research(second, "research-failure-two")
        self.graphctl(
            "record", "retry", "--run-id", "RUN-1", "--branch-id", first["branch_id"],
            "--reason-code", "RETRY", "--op-id", "research-retry-exhausted-one",
        )
        first_retry = self.claim_raw()
        self._failed_research(first_retry, "research-failure-one-exhausted")
        self.graphctl(
            "record", "retry", "--run-id", "RUN-1", "--branch-id", second["branch_id"],
            "--reason-code", "RETRY", "--op-id", "research-retry-exhausted-two",
        )
        second_retry = self.claim_raw()
        self._failed_research(second_retry, "research-failure-two-exhausted")
        blocked = self.advance("research_collection")
        self.assertEqual(
            (blocked["code"], blocked["reason"], self.graphctl("status", "--run-id", "RUN-1")["status"]),
            ("GRAPH_BLOCKED", "MANDATORY_RESEARCH_FAILED", "blocked"),
        )
        self.assertFalse(any(
            branch["node_key"] == "tech_lead"
            for branch in self.graphctl("status", "--run-id", "RUN-1")["branches"]
        ))

    def _approve_design_to_implementation(self):
        self._record_design_review("APPROVE")
        self.consolidation("design", "APPROVE")
        self.advance("design_consolidation")

    def _delivery_to_collection(self, finding_role=None, disposition=None):
        engineer = self.claim()
        self.assertEqual(engineer["node_key"], "senior_engineer")
        self.success(engineer, "IMPLEMENTED")
        self.advance("implementation")
        for _ in range(2):
            reviewer = self.claim()
            findings = []
            if reviewer["role"] == finding_role:
                prefix = "REV" if finding_role == "code_reviewer" else "TEST"
                findings = [{"finding_id": prefix + "-001", "disposition": disposition}]
            decision = "REVISE" if findings else "APPROVE"
            self.success(reviewer, decision=decision, findings=findings)
        self.advance("delivery_collection")

    def test_design_only_approval_closes_without_senior_engineer(self):
        self._design_to_reviews("design_only", "design_only")
        self._record_design_review("APPROVE")
        self.consolidation("design", "APPROVE")
        self.advance("design_consolidation")
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertFalse(any(branch["role"] == "senior_engineer" for branch in status["branches"]))
        self.assertEqual(status["next_action"]["kind"], "advance_join")

    def test_advisory_route_has_only_read_only_entry_and_closure(self):
        self.initialize("advisory", "advisory")
        self.impact("advisory")
        advisory = self.claim()
        self.assertEqual((advisory["node_key"], advisory["role"]), ("advisory_reviewer", "code_reviewer"))
        self.success(advisory)
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual({branch["role"] for branch in status["branches"]}, {"impact_mapper", "code_reviewer"})
        self.assertEqual([join["join_key"] for join in status["joins"]], ["closure"])

    def test_fast_path_has_writer_then_independent_delivery_gates(self):
        self.initialize("delivery", "fast_path")
        self.impact("fast_path")
        engineer = self.claim(); self.assertEqual(engineer["role"], "senior_engineer")
        self.success(engineer, "IMPLEMENTED")
        self.advance("implementation")
        fanout = self.graphctl("status", "--run-id", "RUN-1")["fanouts"][0]
        self.assess_fanout(fanout["fanout_id"])
        ready = self.graphctl("ready", "--run-id", "RUN-1")["branches"]
        self.assertEqual({branch["role"] for branch in ready}, {"code_reviewer", "test_engineer"})

    def test_fast_path_redesign_runs_fresh_design_implementation_and_delivery_to_closure(self):
        self.initialize("delivery", "fast_path")
        self.impact("fast_path")
        engineer = self.claim()
        rationale = self.repo_artifact("finding", "fast-path-redesign-rationale")
        self.record(engineer, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": engineer["branch_id"],
            "status": "succeeded", "output_kind": "implementation_handoff",
            "evidence": [rationale], "decision": "REDESIGN_REQUIRED",
            "findings": [{"finding_id": "REV-777", "disposition": "redesign"}],
        })
        self.advance("delivery_collection")
        self.consolidation(
            "delivery", "REDESIGN", 0,
            [{"finding_id": "REV-777", "disposition": "redesign"}],
        )
        self.advance("delivery_consolidation")

        tech = self.claim()
        self.assertEqual((tech["node_key"], tech["generation"]), ("tech_lead", 1))
        self.success(tech); self.advance("design_inputs", 1)
        architect = self.claim()
        self.assertEqual((architect["node_key"], architect["generation"]), ("architect", 1))
        self.success(architect, "APPROVE"); self.advance("design_collection", 1)
        self.consolidation("design", "APPROVE", 1)
        self.advance("design_consolidation", 1)

        replacement = self.claim()
        self.assertEqual((replacement["node_key"], replacement["generation"]), ("senior_engineer", 1))
        self.success(replacement, "IMPLEMENTED"); self.advance("implementation", 1)
        for _ in range(2):
            reviewer = self.claim()
            self.assertEqual(reviewer["generation"], 1)
            self.success(reviewer, "APPROVE")
        self.advance("delivery_collection", 1)
        self.consolidation("delivery", "ACCEPT", 1)
        self.advance("delivery_consolidation", 1)
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual((status["route"], status["next_action"]["kind"]), ("fast_path", "advance_join"))
        self.assertEqual(
            [(item["budget_id"], item["used"]) for item in status["budgets"] if item["budget_id"] == "design_revisions"],
            [("design_revisions", 1)],
        )

    def test_golden_block_collection_does_not_block_then_consolidation_does(self):
        self._design_to_reviews()
        self._record_design_review("BLOCK", "ARCH-001")
        mid = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(mid["status"], "active")
        self.assertEqual(next(b for b in mid["budgets"] if b["budget_id"] == "design_revisions")["used"], 0)
        self.consolidation("design", "BLOCK", dispositions=[{"finding_id": "ARCH-001", "disposition": "block"}])
        result = self.advance("design_consolidation")
        self.assertEqual(result["outcome"], "BLOCK")
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["status"], "blocked")

    def test_golden_revise_activates_only_next_design_generation(self):
        self._design_to_reviews()
        self._record_design_review("REVISE", "ARCH-001")
        self.consolidation("design", "REVISE", dispositions=[{"finding_id": "ARCH-001", "disposition": "revise"}])
        result = self.advance("design_consolidation")
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(result["outcome"], "REVISE")
        self.assertEqual(status["next_action"]["kind"], "record_fanout_assessment")
        research = [b for b in status["branches"] if b["stage"] == "research"]
        by_generation = {
            generation: [b for b in research if b["generation"] == generation]
            for generation in {b["generation"] for b in research}
        }
        self.assertEqual(set(by_generation), {0, 1})
        self.assertEqual({(b["node_key"], b["status"]) for b in by_generation[0]}, {
            ("design_research_architecture", "succeeded"),
            ("design_research_validation", "succeeded"),
        })
        self.assertEqual({(b["node_key"], b["generation"], b["status"]) for b in by_generation[1]}, {
            ("design_research_architecture", 1, "pending"),
            ("design_research_validation", 1, "pending"),
        })
        self.assertFalse(any(b["node_key"] == "tech_lead" and b["generation"] == 1 for b in status["branches"]))
        self.assertEqual(next(b for b in status["budgets"] if b["budget_id"] == "design_revisions")["used"], 1)

    def test_golden_repair_activates_fresh_implementation_generation(self):
        self._design_to_reviews()
        self._approve_design_to_implementation()
        self._delivery_to_collection("code_reviewer", "repair")
        before = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(next(b for b in before["budgets"] if b["budget_id"] == "delivery_repairs")["used"], 0)
        self.consolidation("delivery", "REPAIR", dispositions=[{"finding_id": "REV-001", "disposition": "repair"}])
        self.advance("delivery_consolidation")
        status = self.graphctl("status", "--run-id", "RUN-1")
        ready = [b for b in status["branches"] if b["status"] == "ready"]
        self.assertEqual([(b["node_key"], b["generation"]) for b in ready], [("senior_engineer", 1)])
        self.assertEqual(next(b for b in status["budgets"] if b["budget_id"] == "delivery_repairs")["used"], 1)

    def test_golden_redesign_activates_fresh_design_generation(self):
        self._design_to_reviews()
        self._approve_design_to_implementation()
        self._delivery_to_collection("test_engineer", "redesign")
        self.consolidation("delivery", "REDESIGN", dispositions=[{"finding_id": "TEST-001", "disposition": "redesign"}])
        self.advance("delivery_consolidation")
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(status["next_action"]["kind"], "record_fanout_assessment")
        research = [b for b in status["branches"] if b["stage"] == "research"]
        by_generation = {
            generation: [b for b in research if b["generation"] == generation]
            for generation in {b["generation"] for b in research}
        }
        self.assertEqual(set(by_generation), {0, 1})
        self.assertEqual({(b["node_key"], b["status"]) for b in by_generation[0]}, {
            ("design_research_architecture", "succeeded"),
            ("design_research_validation", "succeeded"),
        })
        self.assertEqual({(b["node_key"], b["generation"], b["status"]) for b in by_generation[1]}, {
            ("design_research_architecture", 1, "pending"),
            ("design_research_validation", 1, "pending"),
        })
        self.assertFalse(any(b["node_key"] == "tech_lead" and b["generation"] == 1 for b in status["branches"]))
        self.assertEqual(next(b for b in status["budgets"] if b["budget_id"] == "design_revisions")["used"], 1)

    def test_resume_preserves_running_work_and_rejects_changed_policy(self):
        self.initialize()
        claimed = self.claim()
        resumed = self.graphctl("resume", "--run-id", "RUN-1", "--ack-degraded-permissions", "--ack-degraded-durability")
        self.assertEqual(resumed["unresolved_running"], [claimed["branch_id"]])
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy_path.write_bytes(policy_path.read_bytes() + b" ")
        with self.assertRaisesRegex(StateError, "CONFIG_CHANGED"):
            self.graphctl("resume", "--run-id", "RUN-1", "--ack-degraded-permissions", "--ack-degraded-durability")

    def test_completion_requires_acceptance_and_passing_check(self):
        self._design_to_reviews("design_only", "design_only")
        self._record_design_review("APPROVE")
        self.consolidation("design", "APPROVE")
        self.advance("design_consolidation")
        with self.assertRaisesRegex(StateError, "ACCEPTANCE_EVIDENCE_INCOMPLETE"):
            self.graphctl("complete", "--run-id", "RUN-1", "--op-id", "complete-too-early")
        acceptance = self.repo_artifact("acceptance_evidence", "acceptance")
        self.graphctl("record", "acceptance-evidence", "--run-id", "RUN-1", "--criterion-id", "AC-001", "--artifact-ref", acceptance["ref"], "--artifact-sha256", acceptance["sha256"], "--op-id", "acceptance-1")
        self.graphctl("check", "run", "--run-id", "RUN-1", "--check-id", "repo-check", "--op-id", "check-1")
        result = self.graphctl("complete", "--run-id", "RUN-1", "--op-id", "complete-1")
        self.assertEqual(result["status"], "complete")
        replay = self.graphctl("complete", "--run-id", "RUN-1", "--op-id", "complete-1")
        self.assertEqual((replay["code"], replay["state_revision"]), ("REPLAYED", result["state_revision"]))
        with self.assertRaisesRegex(StateError, "TERMINAL_RUN"):
            self.graphctl("complete", "--run-id", "RUN-1", "--op-id", "complete-late")

    def test_partial_collection_reports_exact_inflight_groups(self):
        self.initialize(tags=["security_privacy"])
        self.impact("full_delivery", ["security_privacy"])
        tech = self.claim(); self.success(tech); self.advance("design_inputs")
        first = self.claim(); self.success(first, "APPROVE")
        join = self.open_join("design_collection")
        result = self.graphctl("join", "validate", "--run-id", "RUN-1", "--join-id", join["join_id"])
        self.assertEqual(result["code"], "NOT_READY")
        self.assertEqual(len(result["groups"]["ready"]), 1)
        second = self.claim(); self.success(second, "APPROVE")
        result = self.graphctl("join", "validate", "--run-id", "RUN-1", "--join-id", join["join_id"])
        self.assertEqual(result["code"], "READY")

    def test_retry_boundary_blocks_mandatory_branch(self):
        self.initialize(); self.impact("full_delivery")
        branch = self.claim()

        def fail(label):
            evidence = self.repo_artifact("failure", label)
            self.record(branch, {
                "schema_version": 1, "run_id": "RUN-1", "branch_id": branch["branch_id"],
                "status": "failed", "output_kind": "technical_design", "failure_code": "TOOL_FAILURE",
                "evidence": [evidence],
            })

        fail("failure-one")
        self.graphctl("record", "retry", "--run-id", "RUN-1", "--branch-id", branch["branch_id"], "--reason-code", "RETRY", "--op-id", "retry-one")
        branch = self.claim(); fail("failure-two")
        blocked = self.graphctl("record", "retry", "--run-id", "RUN-1", "--branch-id", branch["branch_id"], "--reason-code", "RETRY", "--op-id", "retry-two")
        self.assertEqual(blocked["code"], "GRAPH_BLOCKED")
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["status"], "blocked")

    def test_normative_golden_trace_fixture_is_complete(self):
        fixture = Path(__file__).parent / "fixtures" / "result-manifests" / "golden-traces.json"
        traces = json.loads(fixture.read_text(encoding="utf-8"))["traces"]
        self.assertEqual(
            set(traces), {"BLOCK", "REVISE", "REPAIR", "REDESIGN", "FAST_PATH_REDESIGN"}
        )

    def test_block_is_durable_replayable_and_only_abort_can_follow(self):
        initialized = self.initialize()
        claimed = self.graphctl("next", "--run-id", "RUN-1", "--claim", "--op-id", "claim-before-block")
        manifest = self.control_manifest("block", "STOP")
        blocked = self.graphctl("block", "--run-id", "RUN-1", "--reason-code", "STOP", "--evidence-manifest", str(manifest), "--op-id", "block-1")
        self.assertEqual(blocked["status"], "blocked")
        replay = self.graphctl("next", "--run-id", "RUN-1", "--claim", "--op-id", "claim-before-block")
        self.assertEqual((replay["code"], replay["state_revision"]), ("REPLAYED", claimed["state_revision"]))
        with self.assertRaisesRegex(StateError, "GRAPH_BLOCKED"):
            self.graphctl("record", "retry", "--run-id", "RUN-1", "--branch-id", initialized["branch"]["branch_id"], "--reason-code", "RETRY", "--op-id", "late-retry")
        aborted = self.graphctl("abort", "--run-id", "RUN-1", "--reason-code", "STOP", "--authority-ref", "authority:test", "--op-id", "abort-1")
        self.assertEqual(aborted["status"], "aborted")
        self.assertEqual(self.graphctl("abort", "--run-id", "RUN-1", "--reason-code", "STOP", "--authority-ref", "authority:test", "--op-id", "abort-1")["code"], "REPLAYED")
        with self.assertRaisesRegex(StateError, "TERMINAL_RUN"):
            self.graphctl("abort", "--run-id", "RUN-1", "--reason-code", "OTHER", "--authority-ref", "authority:test", "--op-id", "abort-2")

    def test_timeout_is_frozen_into_collection_and_forces_block(self):
        self._design_to_reviews()
        architect = self.claim()
        manifest = self.control_manifest("timeout", "DEADLINE", architect)
        self.graphctl("record", "timeout", "--run-id", "RUN-1", "--branch-id", architect["branch_id"], "--attempt-id", architect["attempt_id"], "--claim-token", architect["claim_token"], "--reason-code", "DEADLINE", "--evidence-manifest", str(manifest), "--op-id", "timeout-1")
        collected = self.advance("design_collection")
        self.assertEqual(collected["code"], "JOIN_ADVANCED")
        db = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(db) as connection:
            frozen = json.loads(connection.execute("SELECT result_json FROM joins WHERE join_key='design_collection'").fetchone()[0])
        self.assertEqual(frozen[0]["status"], "timed_out")
        self.consolidation("design", "BLOCK")
        outcome = self.advance("design_consolidation")
        self.assertEqual(outcome["outcome"], "BLOCK")
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["status"], "blocked")

    def test_consolidation_reconstructs_all_results_after_restart_from_envelope_only(self):
        tags = ["audio_realtime_translation", "security_privacy"]
        self.initialize(tags=tags); self.impact("full_delivery", tags)
        tech = self.claim(); self.success(tech); self.advance("design_inputs")

        architect = self.claim()
        self.success(
            architect, "REVISE",
            [{"finding_id": "ARCH-808", "disposition": "revise"}],
        )
        failed = self.claim()
        failure_evidence = self.repo_artifact("failure", "specialist-failure")
        self.record(failed, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": failed["branch_id"],
            "status": "failed", "output_kind": failed["output_contract"]["artifact_kind"],
            "failure_code": "TOOL_FAILURE", "evidence": [failure_evidence],
        })
        timed_out = self.claim()
        timeout_manifest = self.control_manifest("timeout", "DEADLINE", timed_out)
        self.graphctl(
            "record", "timeout", "--run-id", "RUN-1", "--branch-id", timed_out["branch_id"],
            "--attempt-id", timed_out["attempt_id"], "--claim-token", timed_out["claim_token"],
            "--reason-code", "DEADLINE", "--evidence-manifest", str(timeout_manifest),
            "--op-id", "restart-timeout",
        )
        self.advance("design_collection")

        self.store = StateStore(self.store.codex_home)
        resumed = self.graphctl(
            "resume", "--run-id", "RUN-1", "--ack-degraded-permissions",
            "--ack-degraded-durability",
        )
        self.assertEqual(resumed["code"], "RESUMED")
        consolidation = self.claim()
        collection = next(item for item in consolidation["inputs"] if item["kind"] == "collection")
        members = collection["content"]["members"]
        self.assertEqual({item["status"] for item in members}, {"succeeded", "failed", "timed_out"})
        self.assertEqual({item["result_kind"] for item in members}, {"branch_result", "failure", "timeout"})
        self.assertTrue(all("result" in item and "failure_code" in item and "reason_code" in item for item in members))
        architect_result = next(item["result"] for item in members if item["branch_id"] == architect["branch_id"])
        self.assertEqual(
            (architect_result["decision"], architect_result["findings"]),
            ("REVISE", [{"finding_id": "ARCH-808", "disposition": "revise"}]),
        )
        self.record(consolidation, {
            "schema_version": 1, "kind": "design_consolidation", "run_id": "RUN-1",
            "join_id": collection["content"]["join_id"], "generation": 0,
            "source_branch_ids": [item["branch_id"] for item in members],
            "finding_dispositions": [{"finding_id": "ARCH-808", "disposition": "revise"}],
            "outcome": "BLOCK",
        })

    def test_delivery_requires_typed_decision_from_every_mandatory_reviewer(self):
        tags = ["audio_realtime_translation", "ios_webkit_native", "release_operations", "security_privacy"]
        self.initialize(tags=tags); self.impact("full_delivery", tags)
        tech = self.claim(); self.success(tech); self.advance("design_inputs")
        for _ in range(5):
            self.success(self.claim(), "APPROVE")
        self.advance("design_collection"); self.consolidation("design", "APPROVE"); self.advance("design_consolidation")
        engineer = self.claim(); self.success(engineer, "IMPLEMENTED"); self.advance("implementation")
        seen = set()
        for _ in range(6):
            reviewer = self.claim(); seen.add(reviewer["role"])
            artifact = self.repo_artifact(reviewer["output_contract"]["artifact_kind"], "missing-decision-" + reviewer["role"])
            invalid = {
                "schema_version": 1, "run_id": "RUN-1", "branch_id": reviewer["branch_id"],
                "status": "succeeded", "output_kind": reviewer["output_contract"]["artifact_kind"],
                "artifact_ref": artifact, "evidence": [], "findings": [],
            }
            with self.assertRaisesRegex(ContractError, "DECISION_CONTRACT_MISMATCH"):
                self.record(reviewer, invalid)
            self.success(reviewer, "APPROVE")
        self.assertEqual(seen, {"code_reviewer", "test_engineer", "audio_realtime_specialist", "ios_platform_specialist", "release_operations_reviewer", "security_reviewer"})
        self.assertEqual(self.advance("delivery_collection")["code"], "JOIN_ADVANCED")

    def test_artifact_free_evidenced_redesign_packet_is_accepted(self):
        self._design_to_reviews(); self._approve_design_to_implementation()
        engineer = self.claim()
        missing_evidence = {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": engineer["branch_id"],
            "status": "succeeded", "output_kind": "implementation_handoff",
            "evidence": [], "decision": "REDESIGN_REQUIRED",
            "findings": [{"finding_id": "REV-900", "disposition": "redesign"}],
        }
        with self.assertRaisesRegex(ContractError, "REDESIGN_EVIDENCE_REQUIRED"):
            self.record(engineer, missing_evidence)
        evidence = self.repo_artifact("finding", "redesign-rationale")
        valid = dict(missing_evidence)
        valid["evidence"] = [evidence]
        self.record(engineer, valid)
        join = self.open_join("delivery_collection")
        self.assertEqual(join["generation"], 0)

    def test_implemented_requires_artifact_and_consistent_findings(self):
        self._design_to_reviews(); self._approve_design_to_implementation()
        engineer = self.claim()
        invalid = {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": engineer["branch_id"],
            "status": "succeeded", "output_kind": "implementation_handoff",
            "evidence": [], "decision": "IMPLEMENTED",
            "findings": [{"finding_id": "REV-900", "disposition": "redesign"}],
        }
        with self.assertRaisesRegex(ContractError, "ARTIFACT_REQUIRED"):
            self.record(engineer, invalid)
        invalid["artifact_ref"] = self.repo_artifact("implementation_handoff", "bad-implemented")
        with self.assertRaisesRegex(ContractError, "DECISION_FINDING_MISMATCH"):
            self.record(engineer, invalid)

    def test_successor_context_carries_verified_task_design_and_implementation_refs(self):
        self._design_to_reviews(); self._approve_design_to_implementation()
        engineer = self.claim()
        implementation_inputs = {item["kind"] for item in engineer["inputs"]}
        self.assertIn("task_brief", implementation_inputs)
        self.assertIn("technical_design", implementation_inputs)
        self.success(engineer, "IMPLEMENTED"); self.advance("implementation")
        reviewer = self.claim()
        kinds = {item["kind"] for item in reviewer["inputs"]}
        self.assertTrue({"task_brief", "technical_design", "implementation_handoff"}.issubset(kinds))

    def test_zero_design_and_repair_budgets_block_at_exact_boundary(self):
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["limits"]["design_revisions"] = 0
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.policy_bytes = policy_path.read_bytes()
        self._design_to_reviews(); self._record_design_review("REVISE", "ARCH-001")
        self.consolidation("design", "REVISE", dispositions=[{"finding_id": "ARCH-001", "disposition": "revise"}])
        result = self.advance("design_consolidation")
        self.assertEqual((result["outcome"], self.graphctl("status", "--run-id", "RUN-1")["status"]), ("BLOCK", "blocked"))

    def test_zero_delivery_repair_budget_blocks_at_exact_boundary(self):
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["limits"]["delivery_repairs"] = 0
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.policy_bytes = policy_path.read_bytes()
        self._design_to_reviews(); self._approve_design_to_implementation()
        self._delivery_to_collection("code_reviewer", "repair")
        self.consolidation("delivery", "REPAIR", dispositions=[{"finding_id": "REV-001", "disposition": "repair"}])
        result = self.advance("delivery_consolidation")
        self.assertEqual((result["outcome"], self.graphctl("status", "--run-id", "RUN-1")["status"]), ("BLOCK", "blocked"))

    def test_mapper_failure_is_evidenced_retryable_and_replayable(self):
        initialized = self.initialize()
        mapper = self.claim()
        evidence = self.repo_artifact("failure", "mapper-failure")
        manifest = {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": mapper["branch_id"],
            "status": "failed", "output_kind": "impact_map", "failure_code": "INSUFFICIENT_EVIDENCE",
            "evidence": [evidence],
        }
        path = self.inbox_manifest(manifest, "mapper-failure.json")
        manifest["attempt_id"] = mapper["attempt_id"]
        manifest["claim_digest"] = __import__("graph_engine.ids", fromlist=["sha256_bytes"]).sha256_bytes(mapper["claim_token"].encode("utf-8"))
        path.write_text(json.dumps(manifest), encoding="utf-8")
        args = ("record", "branch-result", "--run-id", "RUN-1", "--branch-id", mapper["branch_id"], "--attempt-id", mapper["attempt_id"], "--claim-token", mapper["claim_token"], "--result-manifest", str(path), "--op-id", "mapper-failed")
        first = self.graphctl(*args)
        replay = self.graphctl(*args)
        self.assertEqual((first["branch_status"], replay["code"], replay["state_revision"]), ("failed", "REPLAYED", first["state_revision"]))
        retried = self.graphctl("record", "retry", "--run-id", "RUN-1", "--branch-id", mapper["branch_id"], "--reason-code", "RETRY", "--op-id", "mapper-retry")
        self.assertEqual(retried["branch_status"], "ready")
        replacement = self.claim()
        self.assertEqual(replacement["branch_id"], mapper["branch_id"])
        self.assertNotEqual(replacement["attempt_id"], mapper["attempt_id"])
        self.assertEqual(replacement["retry_count"], mapper["retry_count"] + 1)
        plan = self.graphctl("status", "--run-id", "RUN-1")["execution_plan"]
        self.assertEqual(plan["status"], "approved")
        self.assertEqual(plan["plan_digest"], initialized["execution_plan_digest"])

    def test_failed_result_wrapper_cannot_satisfy_retry_output_contract(self):
        self.initialize(); self.impact("full_delivery")
        engineer = self.claim()
        evidence = self.repo_artifact("failure", "failed-design-wrapper")
        self.record(engineer, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": engineer["branch_id"],
            "status": "failed", "output_kind": "technical_design",
            "failure_code": "TOOL_FAILURE", "evidence": [evidence],
        })
        db = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(db) as connection:
            failed_node = connection.execute(
                "SELECT result_digest,envelope_json FROM nodes WHERE branch_id=?", (engineer["branch_id"],)
            ).fetchone()
            wrapper = json.loads(failed_node["envelope_json"])["artifact_ref"]
            registered_kind = connection.execute(
                "SELECT kind FROM artifacts WHERE ref=?", (wrapper["ref"],)
            ).fetchone()[0]
        self.assertEqual((wrapper["kind"], registered_kind), ("failure", "failure"))
        self.graphctl(
            "record", "retry", "--run-id", "RUN-1", "--branch-id", engineer["branch_id"],
            "--reason-code", "RETRY", "--op-id", "wrapper-retry",
        )
        retried = self.claim()
        adversarial = {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": retried["branch_id"],
            "status": "succeeded", "output_kind": "technical_design",
            "artifact_ref": {
                "kind": "technical_design", "ref": wrapper["ref"], "sha256": wrapper["sha256"],
            },
            "evidence": [], "findings": [],
        }
        with self.assertRaisesRegex(ContractError, "LEDGER_ARTIFACT_NOT_FOUND"):
            self.record(retried, adversarial)

    def test_budget_consumption_is_atomic_replayable_and_unique_per_source(self):
        self.initialize(); self.impact("full_delivery")
        mapper_id = next(branch["branch_id"] for branch in self.graphctl("status", "--run-id", "RUN-1")["branches"] if branch["node_key"] == "impact_mapper")
        args = ("record", "budget-use", "--run-id", "RUN-1", "--budget-id", "file_reads", "--amount", "1", "--source-branch-id", mapper_id, "--op-id", "budget-1")
        first = self.graphctl(*args); replay = self.graphctl(*args)
        self.assertEqual((first["code"], replay["code"], replay["state_revision"]), ("BUDGET_USE_RECORDED", "REPLAYED", first["state_revision"]))
        with self.assertRaisesRegex(StateError, "BUDGET_CONSUMPTION_CONFLICT"):
            self.graphctl("record", "budget-use", "--run-id", "RUN-1", "--budget-id", "file_reads", "--amount", "1", "--source-branch-id", mapper_id, "--op-id", "budget-2")

    def test_cli_exit_codes_are_stable(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")

        def invoke(*args):
            stream = io.StringIO()
            with patch("graph_engine.cli.StateStore", return_value=self.store), redirect_stdout(stream):
                code = main(["--repo", str(self.repo), *args])
            return code, json.loads(stream.getvalue())

        code, initialized = invoke("--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "cli-init")
        self.assertEqual((code, initialized["code"]), (0, "INITIALIZED"))
        code, _ = invoke("record", "plan-approval", "--run-id", "RUN-1", "--plan-digest", initialized["execution_plan_digest"], "--decision", "APPROVE", "--authority-ref", "authority:test", "--op-id", "cli-plan-approval")
        self.assertEqual(code, 0)
        code, _ = invoke("next", "--run-id", "RUN-1", "--claim", "--op-id", "cli-claim")
        self.assertEqual(code, 0)
        code, waiting = invoke("next", "--run-id", "RUN-1", "--all")
        self.assertEqual((code, waiting["code"]), (2, "NOT_READY"))
        code, conflict = invoke("abort", "--run-id", "RUN-1", "--reason-code", "STOP", "--authority-ref", "authority:test", "--op-id", "cli-claim")
        self.assertEqual((code, conflict["code"]), (5, "OPERATION_CONFLICT"))
        manifest = self.control_manifest("block", "STOP")
        code, blocked = invoke("block", "--run-id", "RUN-1", "--reason-code", "STOP", "--evidence-manifest", str(manifest), "--op-id", "cli-block")
        self.assertEqual((code, blocked["code"]), (3, "GRAPH_BLOCKED"))
        code, _ = invoke("abort", "--run-id", "RUN-1", "--reason-code", "STOP", "--authority-ref", "authority:test", "--op-id", "cli-abort")
        self.assertEqual(code, 0)
        code, invalid = invoke("complete", "--run-id", "RUN-1", "--op-id", "cli-complete")
        self.assertEqual((code, invalid["code"]), (4, "TERMINAL_RUN"))

    def test_v2_size_below_safety_floor_is_stable_and_leaves_no_run_state(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task_v2(risk="high")), encoding="utf-8")
        stream = io.StringIO()
        with patch("graph_engine.cli.StateStore", return_value=self.store), redirect_stdout(stream):
            code = main([
                "--repo", str(self.repo), "--ack-degraded-permissions",
                "--ack-degraded-durability", "init", "--run-id", "RUN-SIZE-FLOOR",
                "--task-brief", str(task_path), "--size", "medium", "--op-id", "size-floor",
            ])
        result = json.loads(stream.getvalue())
        self.assertEqual(
            (code, result["ok"], result["code"], result["field"]),
            (4, False, "EXECUTION_SIZE_BELOW_SAFETY_FLOOR", "size"),
        )
        self.assertFalse(
            self.store.run_root("albanian-live-translate", "RUN-SIZE-FLOOR").exists()
        )
        self.assertFalse(
            self.store.inbox_root("albanian-live-translate", "RUN-SIZE-FLOOR").exists()
        )
