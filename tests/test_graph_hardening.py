import json
import sys
import unittest

from graph_engine.config import load_policy
from graph_engine.contracts import ContractError, validate_task_brief
from graph_engine.ids import sha256_bytes
from graph_engine.state import StateError
from graph_engine.validator import compute_timing

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

    def _awaiting_design_fanout(self, tags=None):
        selected = tags or ["security_privacy"]
        self.initialize(tags=selected)
        self._record_mapper(self.claim(), tags=selected)
        self.success(self.claim())
        self.advance("design_inputs")
        return self.graphctl("status", "--run-id", "RUN-1")["fanouts"][0]

    def _resource_assessment(self, fanout, dependencies=None, claims=None):
        evidence = self.repo_artifact("finding", "fanout-resource-proof-" + str(self.counter))
        members = []
        for index, branch_id in enumerate(reversed(fanout["member_branch_ids"])):
            default = {
                "writable_paths": [
                    {"path": "src/member-{}/file.py".format(index), "scope": "exact"},
                    {"path": "docs/member-{}".format(index), "scope": "subtree"},
                ],
                "mutable_state_refs": ["state:member-{}".format(index)],
                "exclusive_device_refs": ["device:member-{}".format(index)],
                "services": [{"ref": "service:review", "units": 1, "capacity": len(fanout["member_branch_ids"])}],
            }
            members.append({
                "branch_id": branch_id,
                "resources": (claims or {}).get(branch_id, default),
            })
        return {
            "schema_version": 1, "kind": "fanout_assessment", "run_id": "RUN-1",
            "fanout_id": fanout["fanout_id"], "members": members,
            "dependencies": dependencies or [], "evidence": [evidence],
        }

    def _record_assessment_manifest(self, fanout, manifest, op_id):
        path = self.inbox_manifest(manifest)
        return self.graphctl(
            "record", "fanout-assessment", "--run-id", "RUN-1", "--fanout-id", fanout["fanout_id"],
            "--assessment-manifest", str(path), "--authority-ref", "authority:test", "--op-id", op_id,
        )

    def _assert_failed_assessment_atomic(self, fanout, manifest, code, op_id):
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            before_revision = connection.execute("SELECT state_revision FROM runs").fetchone()[0]
            before_envelopes = connection.execute(
                "SELECT branch_id,envelope_json,status FROM nodes ORDER BY branch_id"
            ).fetchall()
            before_artifacts = connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE ref LIKE ?", ("ledger:" + fanout["fanout_id"] + "#%",)
            ).fetchone()[0]
        with self.assertRaisesRegex((StateError, ContractError), code):
            self._record_assessment_manifest(fanout, manifest, op_id)
        with self.store.connect(database) as connection:
            row = connection.execute("SELECT * FROM fanouts WHERE fanout_id=?", (fanout["fanout_id"],)).fetchone()
            self.assertEqual(row["status"], "awaiting")
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM fanout_dependencies WHERE fanout_id=?", (fanout["fanout_id"],)
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE ref LIKE ?", ("ledger:" + fanout["fanout_id"] + "#%",)
            ).fetchone()[0], before_artifacts)
            self.assertEqual(connection.execute("SELECT state_revision FROM runs").fetchone()[0], before_revision)
            after_envelopes = connection.execute(
                "SELECT branch_id,envelope_json,status FROM nodes ORDER BY branch_id"
            ).fetchall()
            self.assertEqual([tuple(row) for row in after_envelopes], [tuple(row) for row in before_envelopes])
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM operations WHERE operation_id=?", (op_id,)
            ).fetchone())

    def _assert_corrupt_mutation_rejected(self, code, op_id):
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            revision = connection.execute("SELECT state_revision FROM runs").fetchone()[0]
        with self.assertRaisesRegex(StateError, code):
            self.graphctl("next", "--run-id", "RUN-1", "--claim", "--op-id", op_id)
        with self.store.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT state_revision FROM runs").fetchone()[0], revision)
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM operations WHERE operation_id=?", (op_id,)
            ).fetchone())

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

    def test_execution_plan_is_visible_and_blocks_claim_until_human_approval(self):
        initialized = self.initialize(size="small", approve=False)
        plan = initialized["execution_plan"]
        self.assertEqual(plan["size"], "small")
        self.assertTrue(plan["approval_required"])
        senior = next(item for item in plan["assignments"] if item["node_key"] == "senior_engineer")
        self.assertEqual((senior["model"], senior["reasoning_effort"]), ("gpt-5.6-luna", "medium"))
        ready = self.graphctl("next", "--run-id", "RUN-1")
        self.assertEqual(ready["code"], "EXECUTION_PLAN_APPROVAL_REQUIRED")
        with self.assertRaisesRegex(StateError, "EXECUTION_PLAN_APPROVAL_REQUIRED"):
            self.claim()
        self.graphctl(
            "record", "plan-approval", "--run-id", "RUN-1",
            "--plan-digest", initialized["execution_plan_digest"], "--decision", "APPROVE",
            "--authority-ref", "authority:test", "--op-id", "plan-approval-1",
        )
        branch = self.claim()
        self.assertEqual((branch["model"], branch["reasoning_effort"]), ("gpt-5.6-luna", "low"))

    def test_rejected_execution_plan_blocks_the_run(self):
        initialized = self.initialize(approve=False)
        result = self.graphctl(
            "record", "plan-approval", "--run-id", "RUN-1",
            "--plan-digest", initialized["execution_plan_digest"], "--decision", "REJECT",
            "--authority-ref", "authority:test", "--op-id", "plan-rejection-1",
        )
        self.assertEqual(result["status"], "blocked")
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(status["execution_plan"]["status"], "rejected")
        with self.assertRaisesRegex(StateError, "GRAPH_BLOCKED"):
            self.claim()

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

    def test_whole_join_deletion_is_detected_from_operation_history(self):
        self.initialize(tags=["security_privacy"])
        self._record_mapper(self.claim(), tags=["security_privacy"])
        self.success(self.claim())
        join = self.open_join("design_inputs")
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            connection.execute("DELETE FROM join_members WHERE join_id=?", (join["join_id"],))
            connection.execute("DELETE FROM joins WHERE join_id=?", (join["join_id"],))
            connection.commit()
        self._assert_corrupt_mutation_rejected("TOPOLOGY_JOIN_INVALID", "deleted-join-claim")

    def test_whole_successor_deletion_is_detected_from_operation_history(self):
        self.initialize()
        self._record_mapper(self.claim())
        branches = self.graphctl("status", "--run-id", "RUN-1")["branches"]
        successor_id = next(item["branch_id"] for item in branches if item["node_key"] == "tech_lead")
        with self.store.connect(self.store.db_path("albanian-live-translate", "RUN-1")) as connection:
            connection.execute("DELETE FROM nodes WHERE branch_id=?", (successor_id,))
            connection.commit()
        self._assert_corrupt_mutation_rejected("TOPOLOGY_NODE_INVALID", "deleted-successor-claim")

    def test_extra_node_and_join_fail_before_mutation(self):
        self.initialize()
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            source = connection.execute("SELECT * FROM nodes WHERE node_key='impact_mapper'").fetchone()
            envelope = json.loads(source["envelope_json"])
            envelope.update({"branch_id": "extra-branch", "node_instance_id": "extra-node", "generation": 1})
            connection.execute(
                """INSERT INTO nodes(branch_id,run_id,node_instance_id,node_key,role,stage,generation,
                mandatory,specialist_tag,status,retry_count,max_retries,envelope_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("extra-branch", "RUN-1", "extra-node", source["node_key"], source["role"],
                 source["stage"], 1, source["mandatory"], None, "ready", 0,
                 source["max_retries"], json.dumps(envelope)),
            )
            connection.commit()
        self._assert_corrupt_mutation_rejected("STABLE_ID_INVALID|TOPOLOGY_NODE_INVALID", "extra-node-claim")

        self.tearDown(); self.setUp()
        self.initialize(); self._record_mapper(self.claim()); self.success(self.claim())
        with self.store.connect(self.store.db_path("albanian-live-translate", "RUN-1")) as connection:
            tech = connection.execute("SELECT * FROM nodes WHERE node_key='tech_lead'").fetchone()
            connection.execute(
                "INSERT INTO joins(join_id,run_id,join_key,kind,stage,generation,status,degraded) VALUES(?,?,?,?,?,?,?,0)",
                ("extra-join", "RUN-1", "closure", "closure", "closure", 99, "open"),
            )
            connection.execute("INSERT INTO join_members VALUES(?,?,1)", ("extra-join", tech["branch_id"]))
            connection.commit()
        self._assert_corrupt_mutation_rejected("STABLE_ID_INVALID|JOIN_MEMBERSHIP_INVALID", "extra-join-claim")

    def test_removed_and_added_join_member_edges_fail_closed(self):
        fanout = self._awaiting_design_fanout(["audio_realtime_translation", "security_privacy"])
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            collection = connection.execute("SELECT * FROM joins WHERE join_key='design_collection'").fetchone()
            connection.execute(
                "DELETE FROM join_members WHERE join_id=? AND branch_id=?",
                (collection["join_id"], fanout["member_branch_ids"][0]),
            )
            connection.commit()
        self._assert_corrupt_mutation_rejected("JOIN_MEMBERSHIP_INVALID", "removed-member-claim")

        self.tearDown(); self.setUp()
        self._awaiting_design_fanout(["audio_realtime_translation", "security_privacy"])
        with self.store.connect(self.store.db_path("albanian-live-translate", "RUN-1")) as connection:
            collection = connection.execute("SELECT * FROM joins WHERE join_key='design_collection'").fetchone()
            producer = connection.execute("SELECT * FROM nodes WHERE node_key='tech_lead'").fetchone()
            connection.execute(
                "INSERT INTO join_members VALUES(?,?,1)", (collection["join_id"], producer["branch_id"])
            )
            connection.commit()
        self._assert_corrupt_mutation_rejected("JOIN_MEMBERSHIP_INVALID", "added-member-claim")

    def test_assessment_envelope_and_dependency_mismatches_fail_closed(self):
        fanout = self._awaiting_design_fanout()
        self._record_assessment_manifest(fanout, self._resource_assessment(fanout), "envelope-assessment")
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            assessed = connection.execute("SELECT * FROM fanouts WHERE fanout_id=?", (fanout["fanout_id"],)).fetchone()
            branch_id = fanout["member_branch_ids"][0]
            envelope = json.loads(connection.execute(
                "SELECT envelope_json FROM nodes WHERE branch_id=?", (branch_id,)
            ).fetchone()[0])
            envelope["inputs"] = [item for item in envelope["inputs"] if item["ref"] != assessed["assessment_ref"]]
            connection.execute("UPDATE nodes SET envelope_json=? WHERE branch_id=?", (json.dumps(envelope), branch_id))
            connection.commit()
        self._assert_corrupt_mutation_rejected("FANOUT_ASSESSMENT_INVALID", "envelope-mismatch-claim")

        self.tearDown(); self.setUp()
        fanout = self._awaiting_design_fanout()
        self._record_assessment_manifest(fanout, self._resource_assessment(fanout), "provenance-assessment")
        with self.store.connect(self.store.db_path("albanian-live-translate", "RUN-1")) as connection:
            connection.execute("DROP TRIGGER fanout_transition_guard")
            connection.execute(
                "UPDATE fanouts SET actor='tampered-actor' WHERE fanout_id=?", (fanout["fanout_id"],)
            )
            connection.commit()
        self._assert_corrupt_mutation_rejected(
            "FANOUT_ASSESSMENT_INVALID", "provenance-mismatch-claim"
        )

        self.tearDown(); self.setUp()
        fanout = self._awaiting_design_fanout()
        before, after = fanout["member_branch_ids"]
        dependencies = [{"before_branch_id": before, "after_branch_id": after, "reason": "ordered"}]
        self._record_assessment_manifest(
            fanout, self._resource_assessment(fanout, dependencies=dependencies), "dependency-assessment"
        )
        with self.store.connect(self.store.db_path("albanian-live-translate", "RUN-1")) as connection:
            connection.execute("DROP TRIGGER fanout_dependency_delete_guard")
            connection.execute(
                "DELETE FROM fanout_dependencies WHERE fanout_id=?", (fanout["fanout_id"],)
            )
            connection.commit()
        self._assert_corrupt_mutation_rejected(
            "FANOUT_DEPENDENCY_STATE_INVALID", "dependency-mismatch-claim"
        )

    def test_fanout_assessment_gates_claim_and_orders_promotion(self):
        self.initialize(tags=["security_privacy"])
        self._record_mapper(self.claim(), tags=["security_privacy"])
        self.success(self.claim())
        self.advance("design_inputs")
        required = self.graphctl("next", "--run-id", "RUN-1")
        self.assertEqual(required["code"], "FANOUT_ASSESSMENT_REQUIRED")
        fanout = self.graphctl("status", "--run-id", "RUN-1")["fanouts"][0]
        before, after = fanout["member_branch_ids"]
        result = self.assess_fanout(fanout["fanout_id"], [{
            "before_branch_id": before, "after_branch_id": after, "reason": "shared review state",
        }])
        self.assertEqual(result["ready_branch_ids"], [before])
        by_id = {item["branch_id"]: item for item in self.graphctl("status", "--run-id", "RUN-1")["branches"]}
        self.assertEqual((by_id[before]["status"], by_id[after]["status"]), ("ready", "pending"))
        first = self.claim()
        timeout_path = self.control_manifest("timeout", "WORKER_TIMEOUT", first)
        timeout = json.loads(timeout_path.read_text(encoding="utf-8"))
        timeout.update({
            "attempt_id": first["attempt_id"],
            "claim_digest": sha256_bytes(first["claim_token"].encode("utf-8")),
        })
        timeout_path.write_text(json.dumps(timeout), encoding="utf-8")
        self.graphctl(
            "record", "timeout", "--run-id", "RUN-1", "--branch-id", before,
            "--attempt-id", first["attempt_id"], "--claim-token", first["claim_token"],
            "--reason-code", "WORKER_TIMEOUT", "--evidence-manifest", str(timeout_path),
            "--op-id", "ordered-timeout",
        )
        by_id = {item["branch_id"]: item for item in self.graphctl("status", "--run-id", "RUN-1")["branches"]}
        self.assertEqual(by_id[after]["status"], "pending")
        self.graphctl(
            "record", "retry", "--run-id", "RUN-1", "--branch-id", before,
            "--reason-code", "RETRY", "--op-id", "ordered-retry",
        )
        self.success(self.claim())
        by_id = {item["branch_id"]: item for item in self.graphctl("status", "--run-id", "RUN-1")["branches"]}
        self.assertEqual(by_id[after]["status"], "ready")

    def test_fanout_assessment_is_atomic_replayable_and_single_assignment(self):
        self.initialize(tags=["security_privacy"])
        self._record_mapper(self.claim(), tags=["security_privacy"])
        self.success(self.claim())
        self.advance("design_inputs")
        fanout = self.graphctl("status", "--run-id", "RUN-1")["fanouts"][0]
        evidence = self.repo_artifact("finding", "assessment-proof")

        def manifest(member_ids):
            return {
                "schema_version": 1, "kind": "fanout_assessment", "run_id": "RUN-1",
                "fanout_id": fanout["fanout_id"],
                "members": [{
                    "branch_id": branch_id,
                    "resources": {
                        "writable_paths": [], "mutable_state_refs": [],
                        "exclusive_device_refs": [], "services": [],
                    },
                } for branch_id in member_ids],
                "dependencies": [], "evidence": [evidence],
            }

        invalid_path = self.inbox_manifest(manifest(fanout["member_branch_ids"][:-1]))
        with self.assertRaisesRegex(ContractError, "FANOUT_MEMBER_INVALID"):
            self.graphctl(
                "record", "fanout-assessment", "--run-id", "RUN-1",
                "--fanout-id", fanout["fanout_id"], "--assessment-manifest", str(invalid_path),
                "--authority-ref", "authority:test", "--op-id", "assessment-invalid",
            )
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["fanouts"][0]["status"], "awaiting")

        valid_path = self.inbox_manifest(manifest(fanout["member_branch_ids"]))
        args = (
            "record", "fanout-assessment", "--run-id", "RUN-1", "--fanout-id", fanout["fanout_id"],
            "--assessment-manifest", str(valid_path), "--authority-ref", "authority:test",
            "--op-id", "assessment-valid",
        )
        recorded = self.graphctl(*args)
        replay = self.graphctl(*args)
        self.assertEqual((recorded["code"], replay["code"]), ("FANOUT_ASSESSMENT_RECORDED", "REPLAYED"))
        with self.assertRaisesRegex(StateError, "FANOUT_ASSESSMENT_EXISTS"):
            self.graphctl(
                "record", "fanout-assessment", "--run-id", "RUN-1",
                "--fanout-id", fanout["fanout_id"], "--assessment-manifest", str(valid_path),
                "--authority-ref", "authority:test", "--op-id", "assessment-replacement",
            )

    def test_retained_schemas_fail_closed_without_mutation(self):
        self.initialize()
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        for schema_version in (2, 3, 4):
            with self.subTest(schema_version=schema_version):
                with self.store.connect(database) as connection:
                    connection.execute("UPDATE runs SET state_schema_version=?", (schema_version,))
                    connection.commit()
                    revision = connection.execute("SELECT state_revision FROM runs").fetchone()[0]
                    operation_count = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
                with self.assertRaisesRegex(StateError, "UNSUPPORTED_STATE_SCHEMA"):
                    self.graphctl(
                        "next", "--run-id", "RUN-1", "--claim",
                        "--op-id", "unsupported-schema-{}".format(schema_version),
                    )
                with self.store.connect(database) as connection:
                    current = connection.execute(
                        "SELECT state_schema_version,state_revision FROM runs"
                    ).fetchone()
                    self.assertEqual(tuple(current), (schema_version, revision))
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0], operation_count)

    def test_real_resource_assessment_is_canonical_and_promotes_three_roots(self):
        fanout = self._awaiting_design_fanout(["audio_realtime_translation", "security_privacy"])
        self.assertEqual(len(fanout["member_branch_ids"]), 3)
        result = self._record_assessment_manifest(
            fanout, self._resource_assessment(fanout), "real-resource-assessment"
        )
        self.assertEqual(result["ready_branch_ids"], fanout["member_branch_ids"])
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            persisted = connection.execute(
                "SELECT * FROM fanouts WHERE fanout_id=?", (fanout["fanout_id"],)
            ).fetchone()
            artifact = connection.execute(
                "SELECT * FROM artifacts WHERE ref=?", (persisted["assessment_ref"],)
            ).fetchone()
            content = json.loads(artifact["content_json"])
            self.assertEqual(
                [member["branch_id"] for member in content["members"]],
                sorted(fanout["member_branch_ids"]),
            )
            self.assertTrue(all(
                member["resources"][category]
                for member in content["members"]
                for category in ("writable_paths", "mutable_state_refs", "exclusive_device_refs", "services")
            ))
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM nodes WHERE status='ready' AND branch_id IN ({})".format(
                    ",".join("?" for _ in fanout["member_branch_ids"])
                ), fanout["member_branch_ids"],
            ).fetchone()[0], 3)
            assessment_ref = persisted["assessment_ref"]
            for branch_id in fanout["member_branch_ids"]:
                envelope = json.loads(connection.execute(
                    "SELECT envelope_json FROM nodes WHERE branch_id=?", (branch_id,)
                ).fetchone()[0])
                self.assertEqual(sum(item["ref"] == assessment_ref for item in envelope["inputs"]), 1)

    def test_invalid_resource_assessments_are_atomic(self):
        fanout = self._awaiting_design_fanout(["audio_realtime_translation", "security_privacy"])
        member_ids = fanout["member_branch_ids"]

        def unique_claims():
            return {
                branch_id: {
                    "writable_paths": [{"path": "src/{}.py".format(index), "scope": "exact"}],
                    "mutable_state_refs": ["state:{}".format(index)],
                    "exclusive_device_refs": ["device:{}".format(index)],
                    "services": [{"ref": "service:review", "units": 1, "capacity": 3}],
                }
                for index, branch_id in enumerate(member_ids)
            }

        for category in ("file", "state", "device"):
            claims = unique_claims()
            if category == "file":
                claims[member_ids[0]]["writable_paths"] = [{"path": "src/shared", "scope": "subtree"}]
                claims[member_ids[1]]["writable_paths"] = [{"path": "src/shared/file.py", "scope": "exact"}]
            elif category == "state":
                claims[member_ids[0]]["mutable_state_refs"] = ["state:shared"]
                claims[member_ids[1]]["mutable_state_refs"] = ["state:shared"]
            else:
                claims[member_ids[0]]["exclusive_device_refs"] = ["device:shared"]
                claims[member_ids[1]]["exclusive_device_refs"] = ["device:shared"]
            self._assert_failed_assessment_atomic(
                fanout, self._resource_assessment(fanout, claims=claims),
                "FANOUT_UNORDERED_CONFLICT", "unordered-" + category,
            )

        inconsistent = unique_claims()
        inconsistent[member_ids[0]]["services"][0]["capacity"] = 2
        self._assert_failed_assessment_atomic(
            fanout, self._resource_assessment(fanout, claims=inconsistent),
            "FANOUT_CAPACITY_INVALID", "inconsistent-capacity",
        )
        over_capacity = unique_claims()
        for resources in over_capacity.values():
            resources["services"][0]["capacity"] = 2
        self._assert_failed_assessment_atomic(
            fanout, self._resource_assessment(fanout, claims=over_capacity),
            "FANOUT_CAPACITY_EXCEEDED", "over-capacity",
        )
        cycle = [
            {"before_branch_id": member_ids[0], "after_branch_id": member_ids[1], "reason": "first"},
            {"before_branch_id": member_ids[1], "after_branch_id": member_ids[0], "reason": "cycle"},
        ]
        self._assert_failed_assessment_atomic(
            fanout, self._resource_assessment(fanout, dependencies=cycle),
            "FANOUT_CYCLE", "cycle-assessment",
        )

    def test_mandatory_ready_branch_cannot_be_skipped(self):
        fanout = self._awaiting_design_fanout()
        self._record_assessment_manifest(fanout, self._resource_assessment(fanout), "skip-assessment")
        branch_id = fanout["member_branch_ids"][0]
        status = self.graphctl("status", "--run-id", "RUN-1")
        branch = next(item for item in status["branches"] if item["branch_id"] == branch_id)
        self.assertEqual(branch["status"], "ready")
        manifest = self.control_manifest("skip", "NOT_APPLICABLE", branch)
        revision = status["state_revision"]
        with self.assertRaisesRegex(StateError, "INVALID_BRANCH_TRANSITION"):
            self.graphctl(
                "record", "skip", "--run-id", "RUN-1", "--branch-id", branch_id,
                "--reason-code", "NOT_APPLICABLE", "--evidence-manifest", str(manifest),
                "--op-id", "mandatory-skip",
            )
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["state_revision"], revision)

    def test_status_returns_incomplete_and_completed_attempt_timing(self):
        self.initialize()
        mapper = self.claim()
        running = self.graphctl("status", "--run-id", "RUN-1")
        mapper_status = next(item for item in running["branches"] if item["branch_id"] == mapper["branch_id"])
        self.assertEqual(mapper_status["attempt_count"], 1)
        self.assertFalse(mapper_status["timing_complete"])
        self.assertIsNone(mapper_status["wall_time_ms"])
        self.assertIsNone(mapper_status["active_duration_ms"])
        self.assertFalse(running["timing"]["overall"]["timing_complete"])
        self.assertIsNone(running["timing"]["overall"]["critical_path"])
        self._record_mapper(mapper)
        completed = self.graphctl("status", "--run-id", "RUN-1")
        mapper_status = next(item for item in completed["branches"] if item["branch_id"] == mapper["branch_id"])
        self.assertTrue(mapper_status["timing_complete"])
        self.assertEqual(mapper_status["attempt_count"], 1)
        self.assertIsNotNone(mapper_status["active_duration_ms"])
        bootstrap = next(item for item in completed["timing"]["stages"] if item["stage"] == "bootstrap")
        self.assertTrue(bootstrap["timing_complete"])

    def test_reversed_attempt_timestamp_fails_semantic_status_without_mutation(self):
        self.initialize()
        mapper = self.claim()
        self._record_mapper(mapper)
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            connection.execute("DROP TRIGGER branch_attempt_identity_guard")
            connection.execute(
                "UPDATE branch_attempts SET finished_at='2000-01-01T00:00:00Z' WHERE branch_id=?",
                (mapper["branch_id"],),
            )
            connection.commit()
            revision = connection.execute("SELECT state_revision FROM runs").fetchone()[0]
        with self.assertRaisesRegex(StateError, "ATTEMPT_TIMESTAMP_INVALID"):
            self.graphctl("status", "--run-id", "RUN-1")
        with self.store.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT state_revision FROM runs").fetchone()[0], revision)


class TimingMetricTests(unittest.TestCase):
    def setUp(self):
        import sqlite3
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE nodes(branch_id TEXT PRIMARY KEY,run_id TEXT,node_key TEXT,role TEXT,stage TEXT,
          generation INTEGER,status TEXT,retry_count INTEGER,max_retries INTEGER,envelope_json TEXT,
          started_at TEXT,finished_at TEXT);
        CREATE TABLE branch_attempts(run_id TEXT,branch_id TEXT,attempt_number INTEGER,attempt_id TEXT,
          claim_digest TEXT,started_at TEXT,finished_at TEXT,outcome TEXT);
        CREATE TABLE operations(run_id TEXT,resulting_revision INTEGER,response_json TEXT);
        CREATE TABLE joins(join_id TEXT PRIMARY KEY,run_id TEXT);
        CREATE TABLE join_members(join_id TEXT,branch_id TEXT,mandatory INTEGER);
        CREATE TABLE fanouts(fanout_id TEXT PRIMARY KEY,run_id TEXT);
        CREATE TABLE fanout_dependencies(fanout_id TEXT,before_branch_id TEXT,after_branch_id TEXT,reason TEXT);
        """)

    def tearDown(self):
        self.connection.close()

    def _node(self, branch_id, started, finished):
        self.connection.execute(
            "INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (branch_id, "RUN", branch_id, "role", "delivery", 0, "succeeded", 0, 1, "{}", started, finished),
        )

    def _attempt(self, branch_id, number, started, finished):
        self.connection.execute(
            "INSERT INTO branch_attempts VALUES(?,?,?,?,?,?,?,?)",
            ("RUN", branch_id, number, branch_id + str(number), "a" * 64, started, finished, "succeeded"),
        )

    def test_exact_overlap_slowest_and_critical_path_metrics(self):
        for branch_id, start, finish in (("A", 1, 5), ("B", 2, 7), ("C", 7, 9)):
            self._node(branch_id, "2026-01-01T00:00:0{}Z".format(start), "2026-01-01T00:00:0{}Z".format(finish))
            self._attempt(branch_id, 1, "2026-01-01T00:00:0{}Z".format(start), "2026-01-01T00:00:0{}Z".format(finish))
        self.connection.execute("INSERT INTO fanouts VALUES('F','RUN')")
        self.connection.execute("INSERT INTO fanout_dependencies VALUES('F','B','C','ordered')")
        timing = compute_timing(self.connection, {
            "run_id": "RUN", "status": "complete", "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:10Z",
        })
        stage = timing["stages"][0]
        self.assertEqual(timing["run"]["wall_time_ms"], 10000)
        self.assertEqual((stage["wall_time_ms"], stage["overlap_time_ms"]), (8000, 3000))
        self.assertEqual(stage["slowest_branch"], {"branch_id": "B", "active_duration_ms": 5000})
        self.assertEqual(stage["critical_path"], {"branch_ids": ["B", "C"], "active_duration_ms": 7000})

    def test_retry_lifecycle_and_microsecond_flooring(self):
        self._node("R", "2026-01-01T00:00:01Z", "2026-01-01T00:00:06Z")
        self._attempt("R", 1, "2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z")
        self._attempt("R", 2, "2026-01-01T00:00:04Z", "2026-01-01T00:00:06Z")
        timing = compute_timing(self.connection, {
            "run_id": "RUN", "status": "complete", "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01.001500Z",
        })
        self.assertEqual(timing["branches"]["R"]["wall_time_ms"], 5000)
        self.assertEqual(timing["branches"]["R"]["active_duration_ms"], 3000)
        self.assertEqual(timing["run"]["wall_time_ms"], 1001)

    def test_incomplete_metrics_are_null_and_equal_ties_are_lexical(self):
        for branch_id in ("B", "A"):
            self._node(branch_id, "2026-01-01T00:00:01Z", "2026-01-01T00:00:03Z")
            self._attempt(branch_id, 1, "2026-01-01T00:00:01Z", "2026-01-01T00:00:03Z")
        tied = compute_timing(self.connection, {
            "run_id": "RUN", "status": "complete", "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:04Z",
        })["stages"][0]
        self.assertEqual(tied["slowest_branch"]["branch_id"], "A")
        self.assertEqual(tied["critical_path"]["branch_ids"], ["A"])

        self.connection.execute("DELETE FROM branch_attempts")
        self.connection.execute("DELETE FROM nodes")
        self.connection.execute(
            "INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("RUNNING", "RUN", "running", "role", "delivery", 0, "running", 0, 1, "{}",
             "2026-01-01T00:00:01Z", None),
        )
        self.connection.execute(
            "INSERT INTO branch_attempts VALUES(?,?,?,?,?,?,?,?)",
            ("RUN", "RUNNING", 1, "attempt", "a" * 64, "2026-01-01T00:00:01Z", None, None),
        )
        incomplete = compute_timing(self.connection, {
            "run_id": "RUN", "status": "active", "started_at": "2026-01-01T00:00:00Z",
            "finished_at": None,
        })
        branch = incomplete["branches"]["RUNNING"]
        self.assertFalse(branch["timing_complete"])
        self.assertIsNone(branch["wall_time_ms"])
        self.assertIsNone(branch["active_duration_ms"])
        self.assertIsNone(incomplete["overall"]["overlap_time_ms"])
        self.assertIsNone(incomplete["overall"]["slowest_branch"])
        self.assertIsNone(incomplete["overall"]["critical_path"])


if __name__ == "__main__":
    unittest.main()
