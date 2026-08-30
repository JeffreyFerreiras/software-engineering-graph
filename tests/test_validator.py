from pathlib import Path
from unittest.mock import patch

from graph_engine.config import load_policy
from graph_engine.contracts import ContractError
from graph_engine.state import StateError
from graph_engine.validator import (
    compute_delivery_outcome, compute_design_outcome, validate_consolidation_manifest,
    verify_resume, verify_semantic_state,
)

from tests.test_support import GraphCase


class ValidatorTests(GraphCase):
    def test_decision_precedence_is_order_independent(self):
        approve = {"status": "succeeded", "mandatory": 1, "result_json": '{"decision":"APPROVE","findings":[]}', "branch_id": "a"}
        revise = {"status": "succeeded", "mandatory": 1, "result_json": '{"decision":"REVISE","findings":[{"finding_id":"ARCH-001"}]}', "branch_id": "b"}
        self.assertEqual(compute_design_outcome([approve, revise]), compute_design_outcome([revise, approve]))
        self.assertEqual(compute_design_outcome([approve, revise])[0], "REVISE")

    def test_delivery_dominance(self):
        repair = {"status": "succeeded", "mandatory": 1, "result_json": '{"findings":[{"finding_id":"REV-001","disposition":"repair"}]}'}
        redesign = {"status": "succeeded", "mandatory": 1, "result_json": '{"findings":[{"finding_id":"TEST-001","disposition":"redesign"}]}'}
        self.assertEqual(compute_delivery_outcome([repair, redesign])[0], "REDESIGN")
        block = {"status": "succeeded", "mandatory": 1, "result_json": '{"decision":"BLOCK","findings":[{"finding_id":"SEC-001","disposition":"block"}]}' }
        self.assertEqual(compute_delivery_outcome([repair, redesign, block])[0], "BLOCK")

    def test_duplicate_and_conflicting_finding_ids_are_rejected(self):
        sources = [
            {"status": "succeeded", "mandatory": 1, "branch_id": "a", "result_json": '{"decision":"REVISE","findings":[{"finding_id":"REV-001","disposition":"repair"}]}'},
            {"status": "succeeded", "mandatory": 1, "branch_id": "b", "result_json": '{"decision":"REVISE","findings":[{"finding_id":"REV-001","disposition":"repair"}]}'},
        ]
        manifest = {"kind": "delivery_consolidation", "run_id": "RUN-1", "join_id": "join", "generation": 0, "source_branch_ids": ["a", "b"], "finding_dispositions": [{"finding_id": "REV-001", "disposition": "repair"}], "outcome": "REPAIR"}
        with self.assertRaisesRegex(ContractError, "DUPLICATE_FINDING_ID"):
            validate_consolidation_manifest(manifest, "delivery", "RUN-1", "join", 0, sources)
        sources[1]["result_json"] = '{"decision":"REVISE","findings":[{"finding_id":"REV-001","disposition":"redesign"}]}'
        with self.assertRaisesRegex(ContractError, "CONFLICTING_FINDING_DISPOSITION"):
            validate_consolidation_manifest(manifest, "delivery", "RUN-1", "join", 0, sources)

    def test_persisted_fanout_uses_forwarded_case_policy(self):
        tags = ["security_privacy"]
        self.initialize(tags=tags)
        self.impact("full_delivery", tags)
        tech_lead = self.claim()
        self.success(tech_lead)
        advanced = self.advance("design_inputs")
        fanout_id = advanced["created_fanout_ids"][0]
        status = self.graphctl("status", "--run-id", "RUN-1")
        member_ids = next(
            fanout["member_branch_ids"] for fanout in status["fanouts"]
            if fanout["fanout_id"] == fanout_id
        )
        evidence = self.repo_artifact("finding", "case-policy-evidence")
        manifest = {
            "schema_version": 1,
            "kind": "fanout_assessment",
            "run_id": "RUN-1",
            "fanout_id": fanout_id,
            "members": [
                {
                    "branch_id": branch_id,
                    "resources": {
                        "writable_paths": [{
                            "path": "src/Feature.py" if index == 0 else "src/feature.py",
                            "scope": "exact",
                        }],
                        "mutable_state_refs": [],
                        "exclusive_device_refs": [],
                        "services": [],
                    },
                }
                for index, branch_id in enumerate(member_ids)
            ],
            "dependencies": [],
            "evidence": [evidence],
        }
        manifest_path = self.inbox_manifest(manifest)
        with patch("graph_engine.cli.os.path.normcase", side_effect=lambda value: value):
            self.graphctl(
                "record", "fanout-assessment", "--run-id", "RUN-1",
                "--fanout-id", fanout_id, "--assessment-manifest", str(manifest_path),
                "--authority-ref", "authority:test", "--op-id", "case-policy-assessment",
            )

        policy, policy_snapshot = load_policy(self.repo)
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        skill_root = Path(__file__).resolve().parents[1]
        with self.store.connect(database) as connection:
            run = connection.execute("SELECT * FROM runs WHERE run_id='RUN-1'").fetchone()
            verify_semantic_state(
                connection, run, self.repo, policy_snapshot.digest, policy, skill_root,
                case_sensitive=True,
            )
            verify_resume(
                connection, run, self.repo, policy_snapshot.digest, policy, skill_root,
                case_sensitive=True,
            )
            with self.assertRaisesRegex(StateError, "FANOUT_ASSESSMENT_INVALID"):
                verify_semantic_state(
                    connection, run, self.repo, policy_snapshot.digest, policy, skill_root,
                    case_sensitive=False,
                )
            with self.assertRaisesRegex(StateError, "FANOUT_ASSESSMENT_INVALID"):
                verify_resume(
                    connection, run, self.repo, policy_snapshot.digest, policy, skill_root,
                    case_sensitive=False,
                )
