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
        self.advance("design_collection")
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            persisted = connection.execute(
                "SELECT size_bytes FROM artifacts WHERE kind='collection'"
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
                "SELECT COUNT(*) FROM artifacts WHERE kind='collection'"
            ).fetchone()[0]
            stored_join = connection.execute(
                "SELECT status,result_json FROM joins WHERE join_key='design_collection'"
            ).fetchone()
        self.assertEqual(artifact_count, 0)
        self.assertEqual((stored_join["status"], stored_join["result_json"]), ("open", None))

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
        self.assertEqual(status["next_action"]["kind"], "claim")
        ready = [b for b in status["branches"] if b["status"] == "ready"]
        self.assertEqual([(b["node_key"], b["generation"]) for b in ready], [("tech_lead", 1)])
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
        ready = [b for b in status["branches"] if b["status"] == "ready"]
        self.assertEqual([(b["node_key"], b["generation"]) for b in ready], [("tech_lead", 1)])
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
        self.initialize(); mapper = self.claim()
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
