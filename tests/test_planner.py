from graph_engine.config import load_policy
from graph_engine.ids import stable_id
from graph_engine.planner import (
    NodeSpec, design_review_nodes, envelope, initial_route_nodes, validate_fanout_ordering,
)

from tests.test_support import GraphCase


class PlannerTests(GraphCase):
    def test_every_route_has_exact_entry(self):
        policy, _ = load_policy(self.repo)
        expected = {"advisory": "advisory_reviewer", "design_only": "tech_lead", "full_delivery": "tech_lead", "fast_path": "senior_engineer"}
        self.assertEqual({route: initial_route_nodes(policy, route)[0].key for route in expected}, expected)

    def test_multiple_specialists_are_canonical_and_mandatory(self):
        policy, _ = load_policy(self.repo)
        nodes = design_review_nodes(policy, ["security_privacy", "audio_realtime_translation"], 0)
        self.assertEqual([node.specialist_tag for node in nodes[1:]], ["audio_realtime_translation", "security_privacy"])
        self.assertTrue(all(node.mandatory for node in nodes))

    def test_ids_are_stable_across_ordering(self):
        first = stable_id("RUN-1", "a" * 64, "branch", "architect", 0)
        second = stable_id("RUN-1", "a" * 64, "branch", "architect", 0)
        changed = stable_id("RUN-1", "a" * 64, "branch", "architect", 1)
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_policy_and_role_bounds_cannot_add_task_authority(self):
        policy, snapshot = load_policy(self.repo)
        task = self.task()
        task["authority"]["capabilities"].append({"effect": "deploy", "action": "deploy", "target_ref": "production"})
        env = envelope("RUN-1", snapshot.digest, policy, task, NodeSpec("senior_engineer", "senior_engineer", "implementation", 0), "ready", [])
        self.assertNotIn("deploy", {cap["effect"] for cap in env["effect_capabilities"]})

    @staticmethod
    def _member(branch_id, paths=None, services=None):
        return {
            "branch_id": branch_id,
            "resources": {
                "writable_paths": paths or [], "mutable_state_refs": [],
                "exclusive_device_refs": [], "services": services or [],
            },
        }

    def test_fanout_conflicts_require_transitive_ordering(self):
        members = [
            self._member("A", [{"path": "src", "scope": "subtree"}]),
            self._member("B", [{"path": "src/app.py", "scope": "exact"}]),
            self._member("C"),
        ]
        with self.assertRaisesRegex(ValueError, "FANOUT_UNORDERED_CONFLICT"):
            validate_fanout_ordering(members, [], case_sensitive=True)
        dependencies = [
            {"before_branch_id": "A", "after_branch_id": "C", "reason": "first"},
            {"before_branch_id": "C", "after_branch_id": "B", "reason": "then"},
        ]
        self.assertEqual(
            len(validate_fanout_ordering(members, dependencies, case_sensitive=True)), 2,
        )

    def test_fanout_rejects_cycles_and_over_capacity_antichains(self):
        service = {"ref": "gpu", "units": 1, "capacity": 1}
        members = [self._member("A", services=[service]), self._member("B", services=[service])]
        with self.assertRaisesRegex(ValueError, "FANOUT_CAPACITY_EXCEEDED"):
            validate_fanout_ordering(members, [], case_sensitive=True)
        ordered = [{"before_branch_id": "A", "after_branch_id": "B", "reason": "capacity"}]
        validate_fanout_ordering(members, ordered, case_sensitive=True)
        with self.assertRaisesRegex(ValueError, "FANOUT_CYCLE"):
            validate_fanout_ordering(
                members,
                ordered + [{"before_branch_id": "B", "after_branch_id": "A", "reason": "cycle"}],
                case_sensitive=True,
            )

    def test_fanout_case_policy_is_explicit(self):
        members = [
            self._member("A", [{"path": "src/Feature.py", "scope": "exact"}]),
            self._member("B", [{"path": "src/feature.py", "scope": "exact"}]),
        ]
        with self.assertRaisesRegex(ValueError, "FANOUT_UNORDERED_CONFLICT"):
            validate_fanout_ordering(members, [], case_sensitive=False)
        self.assertEqual(
            validate_fanout_ordering(members, [], case_sensitive=True), [],
        )
