import json
import sys
import unittest

from graph_engine.config import load_policy
from graph_engine.contracts import ContractError, validate_task_brief
from graph_engine.ids import sha256_bytes
from graph_engine.state import StateError

from tests.test_support import GraphCase


class GraphHardeningTests(GraphCase):
    def setUp(self):
        super().setUp()
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["limits"]["branch_lease_seconds"] = 30
        policy["required_checks"]["repo-check"]["argv"] = [sys.executable, "-c", "import sys; sys.exit(0)"]
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.policy_bytes = policy_path.read_bytes()

    def _record_mapper(self, branch, route="full_delivery", tags=None):
        evidence = self.repo_artifact("finding", "impact-evidence")
        manifest = {
            "schema_version": 1,
            "task_id": "TASK-1",
            "route_label": route,
            "impact_tags": sorted(tags or []),
            "evidence_refs": [evidence["ref"]],
            "attempt_id": branch["attempt_id"],
            "claim_digest": sha256_bytes(branch["claim_token"].encode("utf-8")),
        }
        self.counter += 1
        path = self.inbox_manifest(manifest)
        return self.graphctl(
            "record", "branch-result", "--run-id", "RUN-1", "--branch-id", branch["branch_id"],
            "--attempt-id", branch["attempt_id"], "--claim-token", branch["claim_token"],
            "--result-manifest", str(path), "--op-id", f"mapper-result-{self.counter}",
        )

    def test_late_result_from_previous_attempt_is_fenced(self):
        self.initialize()
        first = self.claim()
        timeout_manifest = self.control_manifest("timeout", "WORKER_TIMEOUT", {"branch_id": first["branch_id"]})
        timeout_value = json.loads(timeout_manifest.read_text(encoding="utf-8"))
        timeout_value.update({
            "attempt_id": first["attempt_id"],
            "claim_digest": sha256_bytes(first["claim_token"].encode("utf-8")),
        })
        timeout_manifest.write_text(json.dumps(timeout_value), encoding="utf-8")
        self.graphctl(
            "record", "timeout", "--run-id", "RUN-1", "--branch-id", first["branch_id"],
            "--attempt-id", first["attempt_id"], "--claim-token", first["claim_token"],
            "--reason-code", "WORKER_TIMEOUT", "--evidence-manifest", str(timeout_manifest),
            "--op-id", "timeout-1",
        )
        self.graphctl("record", "retry", "--run-id", "RUN-1", "--branch-id", first["branch_id"], "--reason-code", "RETRY", "--op-id", "retry-1")
        second = self.claim()
        stale = {
            "schema_version": 1, "task_id": "TASK-1", "route_label": "full_delivery",
            "impact_tags": [], "evidence_refs": [], "attempt_id": first["attempt_id"],
            "claim_digest": sha256_bytes(first["claim_token"].encode("utf-8")),
        }
        path = self.inbox_manifest(stale)
        with self.assertRaisesRegex(StateError, "ATTEMPT_FENCE_MISMATCH"):
            self.graphctl(
                "record", "branch-result", "--run-id", "RUN-1", "--branch-id", second["branch_id"],
                "--attempt-id", first["attempt_id"], "--claim-token", first["claim_token"],
                "--result-manifest", str(path), "--op-id", "stale-result-1",
            )

    def test_heartbeat_and_expired_lease_are_visible(self):
        self.initialize()
        branch = self.claim()
        heartbeat = self.graphctl(
            "record", "heartbeat", "--run-id", "RUN-1", "--branch-id", branch["branch_id"],
            "--attempt-id", branch["attempt_id"], "--claim-token", branch["claim_token"], "--op-id", "heartbeat-1",
        )
        self.assertEqual(heartbeat["code"], "HEARTBEAT_RECORDED")
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            envelope = json.loads(connection.execute("SELECT envelope_json FROM nodes WHERE branch_id=?", (branch["branch_id"],)).fetchone()[0])
            envelope["lease_expires_at"] = "2000-01-01T00:00:00Z"
            connection.execute("UPDATE nodes SET envelope_json=? WHERE branch_id=?", (json.dumps(envelope), branch["branch_id"]))
            connection.commit()
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(status["next_action"]["kind"], "timeout_expired")

    def test_only_local_check_runner_receipts_can_satisfy_checks(self):
        self.initialize()
        self._record_mapper(self.claim())
        receipt = self.graphctl("check", "run", "--run-id", "RUN-1", "--check-id", "repo-check", "--op-id", "check-1")
        self.assertEqual(receipt["code"], "CHECK_RECORDED")
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            row = connection.execute("SELECT * FROM check_evidence WHERE check_id='repo-check'").fetchone()
            artifact = connection.execute("SELECT * FROM artifacts WHERE ref=?", (row["artifact_ref"],)).fetchone()
            self.assertEqual(artifact["source_type"], "ledger")
            self.assertEqual(json.loads(artifact["content_json"])["kind"], "check_receipt")
        forged = self.repo_artifact("check_evidence", "forged-check")
        with self.assertRaisesRegex(StateError, "CHECK_RECEIPT_REQUIRED"):
            self.graphctl(
                "record", "check-evidence", "--run-id", "RUN-1", "--check-id", "repo-check",
                "--outcome", "PASS", "--artifact-ref", forged["ref"], "--artifact-sha256", forged["sha256"],
                "--op-id", "forged-check-1",
            )

    def test_successful_non_mapper_result_keeps_attempt_provenance(self):
        self.initialize()
        self._record_mapper(self.claim())
        branch = self.claim()
        artifact = self.repo_artifact(branch["output_contract"]["artifact_kind"], "technical-design")
        manifest = {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": branch["branch_id"],
            "status": "succeeded", "output_kind": branch["output_contract"]["artifact_kind"],
            "artifact_ref": artifact, "evidence": [], "findings": [],
            "attempt_id": branch["attempt_id"],
            "claim_digest": sha256_bytes(branch["claim_token"].encode("utf-8")),
        }
        self.counter += 1
        path = self.inbox_manifest(manifest)
        result = self.graphctl(
            "record", "branch-result", "--run-id", "RUN-1", "--branch-id", branch["branch_id"],
            "--attempt-id", branch["attempt_id"], "--claim-token", branch["claim_token"],
            "--result-manifest", str(path), "--op-id", f"design-result-{self.counter}",
        )
        self.assertEqual(result["branch_status"], "succeeded")
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["status"], "active")

    def test_critical_delivery_is_forced_through_security_full_delivery(self):
        policy, snapshot = load_policy(self.repo)
        task = self.task(route="fast_path")
        task["risk_level"] = "critical"
        with self.assertRaisesRegex(ContractError, "CRITICAL_REQUIRES_FULL_DELIVERY"):
            validate_task_brief(task, snapshot.digest, policy)
        task["minimum_route"] = "full_delivery"
        with self.assertRaisesRegex(ContractError, "CRITICAL_REQUIRES_SECURITY_REVIEW"):
            validate_task_brief(task, snapshot.digest, policy)
        task["mandatory_impact_tags"] = ["security_privacy"]
        validate_task_brief(task, snapshot.digest, policy)

    def test_approval_records_local_actor_attestation(self):
        task = self.task()
        task["required_human_decisions"] = ["human-1"]
        self.initialize_task(task)
        self._record_mapper(self.claim())
        scope = self.repo_artifact("acceptance_evidence", "approval-scope")
        self.graphctl(
            "record", "acceptance-evidence", "--run-id", "RUN-1", "--criterion-id", "AC-001",
            "--artifact-ref", scope["ref"], "--artifact-sha256", scope["sha256"], "--op-id", "acceptance-1",
        )
        self.graphctl(
            "record", "approval", "--run-id", "RUN-1", "--approval-id", "human-1",
            "--scope-ref", scope["ref"], "--decision", "APPROVE", "--authority-ref", "authority:test",
            "--artifact-sha256", scope["sha256"], "--op-id", "approval-1",
        )
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            self.assertIsNotNone(connection.execute("SELECT 1 FROM approval_attestations WHERE approval_id='human-1'").fetchone())
            connection.execute("DELETE FROM approval_attestations WHERE approval_id='human-1'")
            connection.commit()
        with self.assertRaisesRegex(StateError, "APPROVAL_ATTESTATION_INVALID"):
            self.graphctl("status", "--run-id", "RUN-1")


if __name__ == "__main__":
    unittest.main()
