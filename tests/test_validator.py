from graph_engine.contracts import ContractError
from graph_engine.validator import compute_delivery_outcome, compute_design_outcome, validate_consolidation_manifest

from test_support import GraphCase


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
