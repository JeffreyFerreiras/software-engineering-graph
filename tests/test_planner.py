from pathlib import Path

from graph_engine.config import load_policy
from graph_engine.execution import (
    CLASS_ASSIGNMENTS, SIZE_ASSIGNMENTS, build_execution_plan, validate_model_assignment,
)
from graph_engine.hosts import DEFAULT_HOST, dispatch_weight_for, known_hosts, resolve_assignment
from graph_engine.ids import stable_id
from graph_engine.planner import (
    NodeSpec, design_research_nodes, design_review_nodes, envelope, initial_route_nodes,
    validate_fanout_ordering,
)

from tests.test_support import GraphCase


EXPECTED_SIZE_ASSIGNMENTS = {
    "small": {
        "impact_mapper": ("gpt-5.6-luna", "max"),
        "advisory_reviewer": ("gpt-5.6-luna", "max"),
        "tech_lead": ("gpt-5.6-sol", "medium"),
        "architect": ("gpt-5.6-sol", "medium"),
        "senior_engineer": ("gpt-5.6-luna", "max"),
        "code_reviewer": ("gpt-5.6-luna", "max"),
        "test_engineer": ("gpt-5.6-luna", "max"),
        "audio_realtime_specialist": ("gpt-5.6-luna", "max"),
        "ios_platform_specialist": ("gpt-5.6-luna", "max"),
        "release_operations_reviewer": ("gpt-5.6-sol", "medium"),
        "security_reviewer": ("gpt-5.6-sol", "high"),
        "supervisor": ("primary-thread", "inherited"),
    },
    "medium": {
        "impact_mapper": ("gpt-5.6-luna", "max"),
        "advisory_reviewer": ("gpt-5.6-sol", "medium"),
        "tech_lead": ("gpt-5.6-sol", "medium"),
        "architect": ("gpt-5.6-sol", "high"),
        "senior_engineer": ("gpt-5.6-sol", "medium"),
        "code_reviewer": ("gpt-5.6-sol", "high"),
        "test_engineer": ("gpt-5.6-luna", "max"),
        "audio_realtime_specialist": ("gpt-5.6-sol", "high"),
        "ios_platform_specialist": ("gpt-5.6-sol", "high"),
        "release_operations_reviewer": ("gpt-5.6-sol", "high"),
        "security_reviewer": ("gpt-5.6-sol", "high"),
        "supervisor": ("primary-thread", "inherited"),
    },
    "large": {
        "impact_mapper": ("gpt-5.6-luna", "max"),
        "advisory_reviewer": ("gpt-5.6-sol", "high"),
        "tech_lead": ("gpt-5.6-sol", "high"),
        "architect": ("gpt-5.6-sol", "xhigh"),
        "senior_engineer": ("gpt-5.6-sol", "high"),
        "code_reviewer": ("gpt-5.6-sol", "xhigh"),
        "test_engineer": ("gpt-5.6-sol", "high"),
        "audio_realtime_specialist": ("gpt-5.6-sol", "high"),
        "ios_platform_specialist": ("gpt-5.6-sol", "high"),
        "release_operations_reviewer": ("gpt-5.6-sol", "high"),
        "security_reviewer": ("gpt-5.6-sol", "xhigh"),
        "supervisor": ("primary-thread", "inherited"),
    },
}


class PlannerTests(GraphCase):
    def test_size_assignment_matrix_is_exact(self):
        self.assertEqual(SIZE_ASSIGNMENTS, EXPECTED_SIZE_ASSIGNMENTS)

    def test_impact_mapper_always_uses_economy_class(self):
        assignments = {
            size: roles["impact_mapper"] for size, roles in CLASS_ASSIGNMENTS.items()
        }
        self.assertEqual(
            assignments,
            {
                "small": ("economy", "max"),
                "medium": ("economy", "max"),
                "large": ("economy", "max"),
            },
        )

    def test_luna_and_design_model_invariants_hold_at_every_size(self):
        for size, assignments in SIZE_ASSIGNMENTS.items():
            for role, (model, effort) in assignments.items():
                if model == "gpt-5.6-luna":
                    self.assertEqual(effort, "max", (size, role))
            self.assertEqual(assignments["tech_lead"][0], "gpt-5.6-sol")
            self.assertEqual(assignments["architect"][0], "gpt-5.6-sol")

    def test_codex_is_the_default_test_host(self):
        plan = build_execution_plan("RUN-1", self.task(), "medium")
        explicit = build_execution_plan("RUN-1", self.task(), "medium", host="codex")
        self.assertEqual(plan, explicit)
        self.assertEqual(plan["host"], DEFAULT_HOST)
        by_key = {item["node_key"]: item for item in plan["assignments"]}
        self.assertEqual(by_key["tech_lead"]["model"], "gpt-5.6-sol")
        self.assertEqual(by_key["tech_lead"]["dispatch_model"], "gpt-5.6-sol")
        self.assertEqual(by_key["impact_mapper"]["model"], "gpt-5.6-luna")
        self.assertEqual(plan["supervisor_recommendation"]["model"], "gpt-5.6-sol")
        self.assertEqual(plan["publication_assignment"]["model"], "gpt-5.6-luna")

    def test_every_host_can_expand_the_class_matrix(self):
        for host in known_hosts():
            for size, roles in CLASS_ASSIGNMENTS.items():
                for role, (intelligence_class, effort) in roles.items():
                    model, resolved = resolve_assignment(host, intelligence_class, effort)
                    self.assertTrue(model, (host, size, role))
                    self.assertTrue(resolved, (host, size, role))

    def test_execution_plan_prefers_node_assignment_then_role_fallback(self):
        for size in SIZE_ASSIGNMENTS:
            assignments = {
                item["node_key"]: (item["model"], item["reasoning_effort"])
                for item in build_execution_plan("RUN-1", self.task(), size)["assignments"]
            }
            self.assertEqual(assignments["advisory_reviewer"], SIZE_ASSIGNMENTS[size]["advisory_reviewer"])
            self.assertEqual(assignments["supervisor_design_consolidation"], SIZE_ASSIGNMENTS[size]["supervisor"])
            self.assertEqual(assignments["supervisor_delivery_consolidation"], SIZE_ASSIGNMENTS[size]["supervisor"])

    def test_profile_defaults_match_medium_runtime_assignments(self):
        profile_roles = {
            "impact_mapper": "impact_mapper",
            "tech_lead": "tech_lead",
            "software_architect": "architect",
            "senior_engineer": "senior_engineer",
            "code_reviewer": "code_reviewer",
            "test_engineer": "test_engineer",
            "security_reviewer": "security_reviewer",
        }
        profile_root = Path(__file__).resolve().parents[1] / "profile-agents"
        for profile_name, assignment_role in profile_roles.items():
            lines = (profile_root / (profile_name + ".toml")).read_text(encoding="utf-8").splitlines()
            effort_line = next(line for line in lines if line.startswith("model_reasoning_effort = "))
            effort = effort_line.split('"', 2)[1]
            self.assertEqual(effort, SIZE_ASSIGNMENTS["medium"][assignment_role][1], profile_name)

    def test_every_route_has_exact_entry(self):
        policy, _ = load_policy(self.repo)
        expected = {"advisory": "advisory_reviewer", "fast_path": "senior_engineer"}
        self.assertEqual({route: initial_route_nodes(policy, route)[0].key for route in expected}, expected)
        for route in ("design_only", "full_delivery"):
            self.assertEqual(
                [node.key for node in initial_route_nodes(policy, route)],
                ["design_research_architecture", "design_research_validation"],
            )

    def test_research_envelopes_split_budget_and_project_read_only_capabilities(self):
        policy, snapshot = load_policy(self.repo)
        task = self.task()
        task["authority"]["capabilities"] = [
            {"effect": "filesystem_read", "action": "read", "target_ref": "repo:docs/"},
            {"effect": "filesystem_write", "action": "edit", "target_ref": "repo:docs/"},
            {"effect": "external_read", "action": "inspect", "target_ref": "andromeda"},
            {"effect": "command", "action": "run", "target_ref": "npm-run-check"},
        ]
        nodes = design_research_nodes(policy, 3)
        envelopes = [
            envelope("RUN-1", snapshot.digest, policy, task, node, "pending", [])
            for node in nodes
        ]
        self.assertEqual([item["research_assignment"]["focus"] for item in envelopes], ["architecture", "validation"])
        totals = task["inspection_budget"]
        for key in totals:
            self.assertLessEqual(
                sum(item["research_assignment"]["inspection_budget"][key] for item in envelopes),
                totals[key],
            )
        for item in envelopes:
            self.assertEqual(
                {cap["effect"] for cap in item["effect_capabilities"]},
                {"filesystem_read", "external_read"},
            )

    def test_research_node_assignments_reuse_impact_mapper(self):
        policy, _ = load_policy(self.repo)
        execution = build_execution_plan("RUN-1", self.task(), "small")
        by_key = {item["node_key"]: item for item in execution["assignments"]}
        for node in design_research_nodes(policy, 0):
            self.assertEqual(
                (node.role, by_key[node.key]["model"], by_key[node.key]["reasoning_effort"]),
                ("impact_mapper", "gpt-5.6-luna", "max"),
            )

    def test_model_assignment_invariant_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "ECONOMY_REASONING_EFFORT_REQUIRED"):
            validate_model_assignment("impact_mapper", "gpt-5.6-luna", "high")
        with self.assertRaisesRegex(ValueError, "DESIGN_MODEL_REQUIRED"):
            validate_model_assignment("tech_lead", "gpt-5.6-luna", "max")
        with self.assertRaisesRegex(ValueError, "HOST_UNSUPPORTED"):
            validate_model_assignment("tech_lead", "gpt-5.6-sol", "medium", host="unknown")
        self.assertEqual(dispatch_weight_for("gpt-5.6-luna", "max"), 3)
        self.assertEqual(dispatch_weight_for("gpt-5.6-sol", "high"), 3)
        self.assertEqual(dispatch_weight_for("gpt-5.6-sol", "xhigh"), 4)
        self.assertEqual(dispatch_weight_for("gpt-5.6-sol", "max"), 5)
        self.assertIsNone(dispatch_weight_for("gpt-5.6-luna", "high"))

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
