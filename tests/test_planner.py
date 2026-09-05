import json
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
    def _normalized_topology(self):
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            run = connection.execute("SELECT * FROM runs WHERE run_id='RUN-1'").fetchone()
            node_rows = connection.execute(
                "SELECT * FROM nodes WHERE run_id='RUN-1' ORDER BY branch_id"
            ).fetchall()
            node_identity = {
                row["branch_id"]: (
                    row["node_key"], row["role"], row["stage"], row["generation"],
                    row["specialist_tag"],
                )
                for row in node_rows
            }
            join_rows = connection.execute(
                "SELECT * FROM joins WHERE run_id='RUN-1' ORDER BY join_id"
            ).fetchall()
            join_identity = {
                row["join_id"]: (
                    row["join_key"], row["kind"], row["stage"], row["generation"],
                )
                for row in join_rows
            }
            fanout_rows = connection.execute(
                "SELECT * FROM fanouts WHERE run_id='RUN-1' ORDER BY fanout_id"
            ).fetchall()
            fanout_identity = {
                row["fanout_id"]: (row["stage"], row["generation"])
                for row in fanout_rows
            }
            plan_row = connection.execute(
                "SELECT * FROM execution_plans WHERE run_id='RUN-1'"
            ).fetchone()
            task = json.loads(run["task_json"])
            return {
                "run": {
                    "status": run["status"],
                    "request_mode": run["request_mode"],
                    "minimum_route": run["minimum_route"],
                    "selected_route": run["selected_route"],
                    "selected_tags": json.loads(run["selected_tags_json"] or "[]"),
                },
                "approval_barrier": {
                    "plan_schema_version": json.loads(plan_row["plan_json"])["schema_version"],
                    "approval_required": json.loads(plan_row["plan_json"])["approval_required"],
                    "status": plan_row["status"],
                    "approved": all(
                        plan_row[key] is not None
                        for key in ("authority_ref", "approved_at", "approved_by", "approval_digest")
                    ),
                },
                "closure_requirements": {
                    "acceptance_ids": task["acceptance_ids"],
                    "required_check_ids": task["required_check_ids"],
                    "required_human_decisions": task["required_human_decisions"],
                },
                "nodes": sorted((
                    node_identity[row["branch_id"]], bool(row["mandatory"]), row["status"],
                    row["retry_count"], row["max_retries"],
                    node_identity.get(row["parent_branch_id"]), row["depth"],
                ) for row in node_rows),
                "joins": sorted((
                    join_identity[row["join_id"]], row["status"], bool(row["degraded"]),
                ) for row in join_rows),
                "join_members": sorted((
                    join_identity[row["join_id"]], node_identity[row["branch_id"]],
                    bool(row["mandatory"]),
                ) for row in connection.execute(
                    "SELECT * FROM join_members ORDER BY join_id,branch_id"
                )),
                "fanouts": sorted((
                    fanout_identity[row["fanout_id"]], row["status"],
                    tuple(sorted(node_identity[item] for item in json.loads(row["member_branch_ids_json"]))),
                ) for row in fanout_rows),
                "fanout_dependencies": sorted((
                    fanout_identity[row["fanout_id"]], node_identity[row["before_branch_id"]],
                    node_identity[row["after_branch_id"]], row["reason"],
                ) for row in connection.execute(
                    "SELECT * FROM fanout_dependencies ORDER BY fanout_id,before_branch_id,after_branch_id"
                )),
            }

    def _full_delivery_topology_trace(self, size):
        initialized = self.initialize_task(self.task_v2(), size=size, approve=False)
        assignments = {
            item["node_key"]: (
                item["role"], item["intelligence_class"], item["model"],
                item["reasoning_effort"], item["dispatch_when"],
            )
            for item in initialized["execution_plan"]["assignments"]
        }
        trace = [self._normalized_topology()]
        self.graphctl(
            "record", "plan-approval", "--run-id", "RUN-1",
            "--plan-digest", initialized["execution_plan_digest"], "--decision", "APPROVE",
            "--authority-ref", "authority:test", "--op-id", "plan-approval-1",
        )
        trace.append(self._normalized_topology())

        specialist_tags = ["release_operations"]
        self.impact("full_delivery", specialist_tags)
        trace.append(self._normalized_topology())
        self._assess_current_fanout_in_order()
        trace.append(self._normalized_topology())
        for _ in range(2):
            self.success(self.claim_raw())
        self.advance("research_collection")
        trace.append(self._normalized_topology())

        tech_lead = self.claim_raw()
        self.assertEqual(tech_lead["node_key"], "tech_lead")
        self.success(tech_lead)
        self.advance("design_inputs")
        trace.append(self._normalized_topology())
        self._assess_current_fanout_in_order()
        trace.append(self._normalized_topology())
        for _ in range(2):
            self.success(self.claim_raw(), "APPROVE")
        self.advance("design_collection")
        trace.append(self._normalized_topology())
        self.consolidation("design", "APPROVE")
        self.advance("design_consolidation")
        trace.append(self._normalized_topology())

        engineer = self.claim_raw()
        self.assertEqual(engineer["node_key"], "senior_engineer")
        self.success(engineer, "IMPLEMENTED")
        self.advance("implementation")
        trace.append(self._normalized_topology())
        self._assess_current_fanout_in_order()
        trace.append(self._normalized_topology())
        for _ in range(3):
            self.success(self.claim_raw(), "APPROVE")
        self.advance("delivery_collection")
        trace.append(self._normalized_topology())
        self.consolidation("delivery", "ACCEPT")
        self.advance("delivery_consolidation")
        trace.append(self._normalized_topology())
        return trace, assignments

    def _assess_current_fanout_in_order(self):
        status = self.graphctl("status", "--run-id", "RUN-1")
        action = status["next_action"]
        fanout = next(
            item for item in status["fanouts"] if item["fanout_id"] == action["fanout_id"]
        )
        dependencies = [
            {
                "before_branch_id": before,
                "after_branch_id": after,
                "reason": "topology-order",
            }
            for before, after in zip(
                fanout["member_branch_ids"], fanout["member_branch_ids"][1:]
            )
        ]
        self.assess_fanout(action["fanout_id"], dependencies)

    def test_v1_plan_shape_and_digest_remain_frozen(self):
        plan = build_execution_plan("RUN-1", self.task())
        self.assertEqual(
            set(plan), {
                "approval_id", "approval_required", "assignments", "host",
                "mandatory_impact_tags", "minimum_route", "plan_digest",
                "publication_assignment", "run_id", "schema_version", "size",
                "size_recommendation", "size_recommendation_reason", "size_source",
                "supervisor_recommendation", "task_id",
            },
        )
        self.assertEqual(
            plan["plan_digest"],
            "4f1be289d36f4b025ab1a4e56d56cd1be6152246942e9a13370dd30f8be865f0",
        )
        self.assertEqual(
            build_execution_plan("RUN-1", self.task(), "small")["size"], "small",
        )

    def test_v2_full_delivery_uses_structured_size_policy(self):
        cases = (
            ({}, "small", ["bounded_low_risk_low_uncertainty"]),
            ({"risk": "medium"}, "medium", ["risk_medium"]),
            ({"scope_extent": "cross_file"}, "medium", ["scope_cross_file"]),
            ({"uncertainty": "medium"}, "medium", ["uncertainty_medium"]),
            ({"tags": ["release_operations"]}, "medium", ["mandatory_nonsecurity_impact_tag"]),
            ({"risk": "high"}, "large", ["risk_high_or_critical"]),
            ({"risk": "critical", "tags": ["security_privacy"]}, "large", ["risk_high_or_critical", "security_privacy_required"]),
            ({"tags": ["security_privacy"]}, "large", ["security_privacy_required"]),
            ({"uncertainty": "high"}, "large", ["uncertainty_high"]),
            ({"scope_extent": "broadly_cross_cutting"}, "large", ["scope_broadly_cross_cutting"]),
        )
        for arguments, expected_size, reasons in cases:
            with self.subTest(arguments=arguments):
                plan = build_execution_plan("RUN-1", self.task_v2(**arguments))
                self.assertEqual(plan["size"], expected_size)
                self.assertEqual(plan["size_policy_version"], 2)
                self.assertEqual(plan["size_recommendation_reason_codes"], reasons)
                self.assertEqual(
                    set(plan["size_recommendation_inputs"]),
                    {"risk_level", "mandatory_impact_tags", "model_sizing"},
                )
                self.assertEqual(plan["minimum_route"], "full_delivery")

    def test_v2_override_cannot_drop_below_safety_floor(self):
        with self.assertRaisesRegex(ValueError, "EXECUTION_SIZE_BELOW_SAFETY_FLOOR"):
            build_execution_plan("RUN-1", self.task_v2(risk="high"), "medium")
        with self.assertRaisesRegex(ValueError, "EXECUTION_SIZE_BELOW_SAFETY_FLOOR"):
            build_execution_plan("RUN-1", self.task_v2(scope_extent="cross_file"), "small")
        self.assertEqual(
            build_execution_plan("RUN-1", self.task_v2(), "large")["size"], "large",
        )

    def test_v2_sizes_change_assignments_without_changing_full_delivery_gates(self):
        traces = {}
        assignments = {}
        for index, size in enumerate(("small", "medium", "large")):
            if index:
                self.tearDown()
                self.setUp()
            traces[size], assignments[size] = self._full_delivery_topology_trace(size)
        self.assertEqual(traces["small"], traces["medium"])
        self.assertEqual(traces["small"], traces["large"])
        self.assertEqual(
            traces["small"][0]["approval_barrier"],
            {
                "plan_schema_version": 1, "approval_required": True,
                "status": "pending", "approved": False,
            },
        )
        self.assertEqual(
            traces["small"][1]["approval_barrier"]["status"], "approved",
        )
        self.assertTrue(traces["small"][1]["approval_barrier"]["approved"])

        final = traces["small"][-1]
        self.assertEqual(
            {item[0][0] for item in final["nodes"]},
            {
                "impact_mapper", "design_research_architecture", "design_research_validation",
                "tech_lead", "architect", "release_operations_reviewer", "senior_engineer",
                "code_reviewer", "test_engineer", "supervisor_design_consolidation",
                "supervisor_delivery_consolidation",
            },
        )
        self.assertTrue(all(item[1] for item in final["nodes"]))
        self.assertTrue(all(item[2] for item in final["join_members"]))
        self.assertEqual(
            {
                item[0][2] for item in final["nodes"]
                if item[0][0] == "release_operations_reviewer"
            },
            {"design", "delivery"},
        )
        self.assertEqual(
            {item[0][0] for item in final["joins"]},
            {
                "research_collection", "design_inputs", "design_collection",
                "design_consolidation", "implementation", "delivery_collection",
                "delivery_consolidation", "closure",
            },
        )
        self.assertEqual(
            {item[0][0] for item in final["fanouts"]},
            {"research", "design", "delivery"},
        )
        self.assertEqual(len(final["fanout_dependencies"]), 4)
        closure = next(item for item in final["joins"] if item[0][0] == "closure")
        self.assertEqual(closure[1], "open")
        self.assertEqual(final["run"]["selected_tags"], ["release_operations"])
        self.assertEqual(
            final["closure_requirements"],
            {
                "acceptance_ids": ["AC-001"], "required_check_ids": ["repo-check"],
                "required_human_decisions": [],
            },
        )
        engineer_assignments = {
            size: plan["senior_engineer"] for size, plan in assignments.items()
        }
        self.assertEqual(len(set(engineer_assignments.values())), 3)

    def test_host_and_supervisor_mappings_are_unchanged_for_v2(self):
        codex = build_execution_plan("RUN-1", self.task_v2(), host="codex")
        cursor = build_execution_plan("RUN-1", self.task_v2(), host="cursor")
        self.assertEqual(
            (codex["supervisor_recommendation"]["model"], codex["supervisor_recommendation"]["reasoning_effort"]),
            ("gpt-5.6-sol", "xhigh"),
        )
        self.assertEqual(
            (cursor["supervisor_recommendation"]["model"], cursor["supervisor_recommendation"]["reasoning_effort"]),
            ("cursor-grok-4.6", "high"),
        )
        cursor_assignments = {
            item["node_key"]: (item["model"], item["reasoning_effort"])
            for item in cursor["assignments"]
        }
        self.assertEqual(cursor_assignments["senior_engineer"], ("composer-2.5", "high"))
        self.assertEqual(cursor_assignments["tech_lead"], ("cursor-grok-4.6", "medium"))

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
