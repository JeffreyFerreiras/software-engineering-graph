import copy
import json
import os
from pathlib import Path

from graph_engine.contracts import ContractError
from graph_engine.reviewer_delegation import (
    consolidate_findings, validate_fanout_request, validate_policy_config,
    validate_findings, validate_preliminary, validate_task_config,
)
from graph_engine.state import StateError
from graph_engine.state import StateStore
from graph_engine.validator import validate_consolidation_manifest

from tests.test_contracts import _validate_json_schema
from tests.test_support import GraphCase


LIMITS = {
    "max_depth": 1,
    "max_children_per_request": 3,
    "max_children_per_run": 6,
    "max_request_rounds": 2,
    "max_weighted_dispatch_cost": 15,
}


def policy_config():
    return {
        "limits": dict(LIMITS),
        "assignments": [{
            "assignment_id": "correctness",
            "role": "code_reviewer",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "review_lens": "Cross-file correctness and concurrency",
            "prompt_template": "Review only the approved evidence and scope.",
            "allowed_reason_codes": ["CROSS_FILE"],
            "allowed_evidence_kinds": ["finding", "implementation_handoff"],
            "scope_refs": ["repo:docs/"],
            "max_instances": 2,
            "dispatch_weight": 3,
        }],
    }


def task_config():
    return {
        "limits": {**LIMITS, "max_request_rounds": 1},
        "assignments": [{
            "assignment_id": "correctness",
            "allowed_reason_codes": ["CROSS_FILE"],
            "allowed_acceptance_ids": ["AC-001"],
            "allowed_evidence_kinds": ["finding", "implementation_handoff"],
            "scope_refs": ["repo:docs/"],
            "max_instances": 2,
        }],
    }


class ReviewerDelegationContractTests(GraphCase):
    def _contracts(self):
        policy = validate_policy_config(policy_config())
        task = validate_task_config(task_config(), policy, ["AC-001"])
        preliminary = validate_preliminary({
            "schema_version": 1, "kind": "review_preliminary", "run_id": "RUN-1",
            "parent_branch_id": "parent", "parent_attempt_id": "attempt", "generation": 0,
            "findings": [],
            "evidence": [{"evidence_id": "E-1", "kind": "finding", "sha256": "a" * 64}],
        }, "RUN-1", "parent", "attempt", 0, approved_evidence=[{
            "kind": "finding", "ref": "repo:docs/evidence.json#sha256=" + "a" * 64,
            "sha256": "a" * 64,
        }])
        request = {
            "schema_version": 1, "kind": "review_fanout_request", "run_id": "RUN-1",
            "parent_branch_id": "parent", "parent_attempt_id": "attempt", "round": 1,
            "members": [{"assignment_id": "correctness", "ordinal": 1,
                         "reason_code": "CROSS_FILE", "acceptance_ids": ["AC-001"], "evidence_ids": ["E-1"]}],
        }
        return task, preliminary, request

    def test_request_contract_is_exhaustive_and_assignment_bounded(self):
        task, preliminary, request = self._contracts()
        normalized = validate_fanout_request(request, "RUN-1", "parent", "attempt", 1, task["assignments"], preliminary, task["limits"])
        self.assertEqual(normalized["members"][0]["assignment_id"], "correctness")
        forbidden = {
            "role": "code_reviewer", "model": "gpt-5.6-sol", "reasoning_effort": "high",
            "capability": "command", "scope": "repo:other/", "prompt": "override",
            "operation_id": "opaque", "path": "state.sqlite3", "authority_ref": "authority:test",
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(request)
                changed["members"][0][field] = value
                with self.assertRaisesRegex(ContractError, "UNKNOWN_FIELD"):
                    validate_fanout_request(changed, "RUN-1", "parent", "attempt", 1, task["assignments"], preliminary, task["limits"])

    def test_limits_and_undeclared_values_fail_closed(self):
        task, preliminary, request = self._contracts()
        cases = []
        for key, value in (("assignment_id", "undeclared"), ("reason_code", "OTHER")):
            changed = copy.deepcopy(request); changed["members"][0][key] = value; cases.append(changed)
        changed = copy.deepcopy(request); changed["members"][0]["acceptance_ids"] = ["AC-999"]; cases.append(changed)
        changed = copy.deepcopy(request); changed["members"][0]["evidence_ids"] = ["E-999"]; cases.append(changed)
        changed = copy.deepcopy(request); changed["members"] *= 4; cases.append(changed)
        for changed in cases:
            with self.assertRaises(ContractError):
                validate_fanout_request(changed, "RUN-1", "parent", "attempt", 1, task["assignments"], preliminary, task["limits"])
        with self.assertRaisesRegex(ContractError, "DELEGATION_DEPTH_EXCEEDED"):
            validate_fanout_request(request, "RUN-1", "parent", "attempt", 1, task["assignments"], preliminary, task["limits"], depth=1)
        unsupported = policy_config()
        unsupported["assignments"][0].update({"model": "gpt-5.6-luna", "reasoning_effort": "high", "dispatch_weight": 2})
        with self.assertRaisesRegex(ContractError, "DELEGATION_ASSIGNMENT_UNSUPPORTED"):
            validate_policy_config(unsupported)

    def test_finding_consolidation_deduplicates_and_preserves_conflicts(self):
        finding = {"finding_id": "REV-001", "acceptance_id": "AC-001", "location": "Src\\Cache.cs", "defect_id": "RACE", "summary": "race", "fix_variant": "Use lock", "evidence_ids": []}
        sources = [
            {"branch_id": "g2-b", "role": "security_reviewer", "model": "gpt-5.6-sol", "assignment_id": "security", "ordinal": 1, "review_lens": "security", "findings": [{**finding, "finding_id": "SEC-001", "location": "src/cache.cs", "fix_variant": "Use channel"}]},
            {"branch_id": "g2-a", "role": "code_reviewer", "model": "gpt-5.6-sol", "assignment_id": "correctness", "ordinal": 1, "review_lens": "correctness", "findings": [finding]},
            {"branch_id": "g2-c", "role": "code_reviewer", "model": "gpt-5.6-sol", "assignment_id": "correctness", "ordinal": 2, "review_lens": "correctness", "findings": [{**finding, "finding_id": "REV-001", "location": "./src/cache.cs", "fix_variant": " use   lock "}]},
        ]
        groups = consolidate_findings(sources)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["canonical_branch_id"], "g2-a")
        self.assertTrue(groups[0]["conflict"])
        self.assertEqual(len(groups[0]["provenance"]), 3)
        self.assertEqual({item["review_lens"] for item in groups[0]["provenance"]}, {"correctness", "security"})
        self.assertEqual(len(groups[0]["fix_variants"]), 2)

    def test_preliminary_registry_and_member_findings_fail_closed(self):
        approved = {"kind": "finding", "ref": "repo:docs/evidence.json#sha256=" + "a" * 64,
                    "sha256": "a" * 64, "size_bytes": 10}
        base = {
            "schema_version": 1, "kind": "review_preliminary", "run_id": "RUN-1",
            "parent_branch_id": "parent", "parent_attempt_id": "attempt", "generation": 0,
            "findings": [], "evidence": [{"evidence_id": "E-1", **{key: approved[key] for key in ("kind", "sha256")}}],
        }
        validate_preliminary(base, "RUN-1", "parent", "attempt", 0, approved_evidence=[approved])
        for forbidden_ref in ("repo:docs/other.json#sha256=" + "b" * 64, "ledger:private#sha256=" + "b" * 64):
            changed = copy.deepcopy(base)
            changed["evidence"][0].update({"ref": forbidden_ref, "sha256": "b" * 64})
            with self.assertRaises(ContractError):
                validate_preliminary(changed, "RUN-1", "parent", "attempt", 0, approved_evidence=[approved])

        finding = {"finding_id": "REV-201", "acceptance_id": "AC-001", "location": "docs/Cache.cs",
                   "defect_id": "RACE", "summary": "race", "fix_variant": "lock", "evidence_ids": ["E-1"]}
        validate_findings([finding], ["E-1"], acceptance_ids=["AC-001"], scope_refs=["repo:docs/"], exact_evidence=True)
        mutations = [
            {"acceptance_id": "AC-999"}, {"location": "src/Cache.cs"},
            {"evidence_ids": ["E-2"]}, {"finding_id": "invalid"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_findings([{**finding, **mutation}], ["E-1"], acceptance_ids=["AC-001"],
                                  scope_refs=["repo:docs/"], exact_evidence=True)
        with self.assertRaisesRegex(ContractError, "DUPLICATE_ID"):
            validate_findings([finding, finding], ["E-1"], acceptance_ids=["AC-001"],
                              scope_refs=["repo:docs/"], exact_evidence=True)

    def test_terminal_failure_or_timeout_cannot_be_accepted_away(self):
        parent = {
            "branch_id": "g2-parent", "status": "succeeded", "mandatory": True,
            "result_json": json.dumps({
                "decision": "BLOCK",
                "findings": [{"finding_id": "REV-901", "disposition": "block"}],
            }),
        }
        provenance = [{
            "request_slot_id": "slot-1", "branch_id": "g2-parent",
            "finding_id": "REV-901", "assignment_id": "primary-reviewer", "ordinal": 0,
        }]
        base_manifest = {
            "kind": "delivery_consolidation", "run_id": "RUN-1", "join_id": "join-1",
            "generation": 0, "source_branch_ids": ["g2-parent"],
            "finding_dispositions": [{"finding_id": "REV-901", "disposition": "block"}],
            "delegated_finding_dispositions": [{
                "issue_key": "issue-1", "source_identities": [["slot-1", "g2-parent", "REV-901"]],
                "disposition": "accept",
            }],
            "outcome": "BLOCK",
        }
        for status in ("failed", "timed_out"):
            with self.subTest(status=status):
                collection = {
                    "kind": "review_nested_collection", "request_slot_id": "slot-1",
                    "parent_branch_id": "g2-parent",
                    "members": [{"status": status, "terminal": {"result": {}}}],
                    "issues": [{"issue_key": "issue-1", "provenance": provenance}],
                }
                self.assertEqual(validate_consolidation_manifest(
                    base_manifest, "delivery", "RUN-1", "join-1", 0, [parent], [collection],
                ), "BLOCK")
                with self.assertRaisesRegex(ContractError, "OUTCOME_PRECEDENCE_MISMATCH"):
                    validate_consolidation_manifest(
                        {**base_manifest, "outcome": "ACCEPT"}, "delivery", "RUN-1", "join-1", 0,
                        [parent], [collection],
                    )

    def test_explicitly_skipped_delegated_member_keeps_accept_disposition(self):
        parent = {
            "branch_id": "g2-parent", "status": "succeeded", "mandatory": True,
            "result_json": json.dumps({
                "decision": "BLOCK",
                "findings": [{"finding_id": "REV-902", "disposition": "block"}],
            }),
        }
        collection = {
            "kind": "review_nested_collection", "request_slot_id": "slot-1",
            "parent_branch_id": "g2-parent",
            "members": [{"status": "skipped", "terminal": {"result": {}}}],
            "issues": [{"issue_key": "issue-1", "provenance": [{
                "request_slot_id": "slot-1", "branch_id": "g2-parent",
                "finding_id": "REV-902", "assignment_id": "primary-reviewer", "ordinal": 0,
            }]}],
        }
        manifest = {
            "kind": "delivery_consolidation", "run_id": "RUN-1", "join_id": "join-1",
            "generation": 0, "source_branch_ids": ["g2-parent"],
            "finding_dispositions": [{"finding_id": "REV-902", "disposition": "block"}],
            "delegated_finding_dispositions": [{
                "issue_key": "issue-1", "source_identities": [["slot-1", "g2-parent", "REV-902"]],
                "disposition": "accept",
            }],
            "outcome": "ACCEPT",
        }
        self.assertEqual(validate_consolidation_manifest(
            manifest, "delivery", "RUN-1", "join-1", 0, [parent], [collection],
        ), "ACCEPT")

    def test_csharp_fixture_is_executable_consolidation_evidence(self):
        fixture = Path(__file__).parent / "fixtures" / "reviewer-delegation-csharp"
        expected = json.loads((fixture / "expected-findings.json").read_text(encoding="utf-8"))
        for source_file in ("Cache.cs", "Worker.cs", "WorkerTests.cs"):
            self.assertTrue((fixture / source_file).read_text(encoding="utf-8").strip())
        scope = ["repo:tests/fixtures/reviewer-delegation-csharp/"]
        sources = []
        branch_index = 0
        for expected_finding in expected["supported_findings"]:
            evidence_ids = ["E-" + expected_finding["acceptance_id"]]
            variants = expected_finding["incompatible_fix_variants"] or ["add the missing assertion"]
            for source_index, finding_id in enumerate(expected_finding["duplicate_source_ids"]):
                lens = expected_finding["lenses"][min(source_index, len(expected_finding["lenses"]) - 1)]
                finding = validate_findings([{
                    "finding_id": finding_id, "acceptance_id": expected_finding["acceptance_id"],
                    "location": expected_finding["location"], "defect_id": expected_finding["defect_id"],
                    "summary": "fixture-supported defect", "fix_variant": variants[min(source_index, len(variants) - 1)],
                    "evidence_ids": evidence_ids,
                }], evidence_ids, acceptance_ids=[expected_finding["acceptance_id"]],
                    scope_refs=scope, exact_evidence=True)[0]
                sources.append({
                    "branch_id": "g2-{}".format(chr(ord("a") + branch_index)),
                    "role": "security_reviewer" if lens == "security" else "code_reviewer",
                    "model": "gpt-5.6-sol", "assignment_id": lens, "ordinal": source_index + 1,
                    "review_lens": lens, "findings": [finding],
                })
                branch_index += 1
        groups = consolidate_findings(sources)
        self.assertEqual(len(groups), len(expected["supported_findings"]))
        by_acceptance = {item["acceptance_id"]: item for item in groups}
        for expected_finding in expected["supported_findings"]:
            group = by_acceptance[expected_finding["acceptance_id"]]
            self.assertEqual({item["finding_id"] for item in group["provenance"]},
                             set(expected_finding["duplicate_source_ids"]))
            self.assertEqual({item["review_lens"] for item in group["provenance"]}, set(expected_finding["lenses"]))
            self.assertEqual(group["conflict"], bool(expected_finding["incompatible_fix_variants"]))
            self.assertEqual({item["text"] for item in group["fix_variants"]},
                             set(expected_finding["incompatible_fix_variants"] or ["add the missing assertion"]))
        baseline = json.dumps(groups, sort_keys=True)
        supported = expected["supported_findings"][1]
        base = {"finding_id": "REV-999", "acceptance_id": supported["acceptance_id"],
                "location": supported["location"], "defect_id": supported["defect_id"],
                "summary": "unsupported amplification", "fix_variant": "none",
                "evidence_ids": ["E-" + supported["acceptance_id"]]}
        for mutation, allowed_evidence in (
            ({"acceptance_id": "AC-UNSUPPORTED"}, base["evidence_ids"]),
            ({"evidence_ids": ["E-UNSUPPORTED"]}, base["evidence_ids"]),
            ({"location": "src/Outside.cs"}, base["evidence_ids"]),
        ):
            with self.assertRaises(ContractError):
                validate_findings([{**base, **mutation}], allowed_evidence,
                                  acceptance_ids=[supported["acceptance_id"]], scope_refs=scope,
                                  exact_evidence=True)
            self.assertEqual(json.dumps(consolidate_findings(sources), sort_keys=True), baseline)


class ReviewerDelegationFlowTests(GraphCase):
    def setUp(self):
        super().setUp()
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["reviewer_delegation"] = policy_config()
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.policy_bytes = policy_path.read_bytes()

    def _to_delivery_review(self, max_rounds=1, delegation_task=None, task=None):
        task = task or self.task()
        task["reviewer_delegation"] = delegation_task or task_config()
        task["reviewer_delegation"]["limits"]["max_request_rounds"] = max_rounds
        self.initialize_task(task)
        self.impact("full_delivery")
        tech = self.claim(); self.success(tech); self.advance("design_inputs")
        architect = self.claim(); self.success(architect, "APPROVE"); self.advance("design_collection")
        self.consolidation("design", "APPROVE"); self.advance("design_consolidation")
        engineer = self.claim(); self.success(engineer, "IMPLEMENTED"); self.advance("implementation")
        first = self.claim()
        if first["role"] == "code_reviewer":
            return first
        self.success(first, "APPROVE")
        reviewer = self.claim()
        self.assertEqual(reviewer["role"], "code_reviewer")
        return reviewer

    def _approved_evidence(self, parent):
        if parent.get("review_continuation"):
            context = parent["inputs"][0]["content"]
            return dict(context["preliminary"][0]["evidence"][0])
        approved = next(item for item in parent["inputs"] if item["kind"] == "implementation_handoff")
        return {key: approved[key] for key in ("kind", "sha256")}

    def _assert_dispatch_redacted(self, envelope, expected_capabilities=None):
        forbidden_keys = {"authority_ref", "actor", "host_identity", "operation_id", "budget",
                          "evidence_manifest_ref", "result_artifact", "attempts", "authority",
                          "capabilities"}
        forbidden_effects = {"filesystem_write", "command", "external_write", "destructive", "publish", "deploy"}
        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden_keys.intersection(value))
                if "effect" in value:
                    self.assertNotIn(value["effect"], forbidden_effects)
                    self.assertIn(value["effect"], {"filesystem_read", "external_read"})
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, str):
                self.assertFalse(value.startswith("ledger:"), value)
        visit(envelope)
        self.assertEqual({key: envelope[key] for key in (
            "artifact_ref", "decision", "failure_code", "started_at", "finished_at",
        )}, {
            "artifact_ref": None, "decision": None, "failure_code": None,
            "started_at": None, "finished_at": None,
        })
        self.assertEqual(envelope["evidence"], [])
        self.assertEqual((envelope["retry_count"], envelope["max_retries"]), (0, 0))
        self.assertEqual(envelope["stopping_condition"], {
            "kind": "valid_result_returned", "max_branch_attempts": 1,
        })
        schema = json.loads((Path(__file__).parents[1] / "references" / "branch-envelope.schema.json").read_text(
            encoding="utf-8"
        ))
        _validate_json_schema(envelope, schema, schema)
        context = envelope["inputs"][0]
        self.assertTrue(context["ref"].startswith("thread:review-context-"))
        self.assertEqual(context["content"]["kind"], "review_continuation_context")
        self.assertNotIn("capabilities", context["content"]["task_scope"])
        self.assertTrue(context["content"]["preliminary"])
        self.assertTrue(context["content"]["nested_collections"])
        if expected_capabilities is not None:
            self.assertEqual(envelope["effect_capabilities"], expected_capabilities)
        self.assertEqual(set(envelope), {
            "schema_version", "run_id", "branch_id", "node_instance_id", "node_key", "role",
            "model", "reasoning_effort", "mandatory", "generation", "status",
            "effect_capabilities", "output_contract", "stopping_condition", "inputs",
            "review_continuation", "attempt_id", "claim_digest", "lease_expires_at",
            "artifact_ref", "evidence", "decision", "retry_count", "max_retries",
            "failure_code", "started_at", "finished_at",
        } | ({"claim_token"} if "claim_token" in envelope else set()))

    def _delegate_round(self, parent, round_number, finding_id, claim_parent=True):
        evidence = self._approved_evidence(parent)
        preliminary = {
            "schema_version": 1, "kind": "review_preliminary", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"],
            "generation": 0, "findings": [], "evidence": [{"evidence_id": "E-1", **evidence}],
        }
        request = {
            "schema_version": 1, "kind": "review_fanout_request", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"], "round": round_number,
            "members": [{"assignment_id": "correctness", "ordinal": 1, "reason_code": "CROSS_FILE",
                         "acceptance_ids": ["AC-001"], "evidence_ids": ["E-1"]}],
        }
        prelim_path = self.inbox_manifest(preliminary, "preliminary-round-{}.json".format(round_number))
        request_path = self.inbox_manifest(request, "request-round-{}.json".format(round_number))
        recorded = self.graphctl(
            "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", parent["branch_id"],
            "--attempt-id", parent["attempt_id"], "--claim-token", parent["claim_token"],
            "--preliminary-manifest", str(prelim_path), "--request-manifest", str(request_path),
            "--authority-ref", "authority:test", "--op-id", "round-{}-request".format(round_number),
        )
        slot = recorded["request_slot_id"]
        assessment = {
            "schema_version": 1, "kind": "fanout_assessment", "run_id": "RUN-1", "fanout_id": slot,
            "members": [{"branch_id": recorded["child_branch_ids"][0], "resources": {
                "writable_paths": [], "mutable_state_refs": [], "exclusive_device_refs": [], "services": [],
            }}], "dependencies": [], "evidence": [self.repo_artifact("finding", "round-assessment-{}".format(round_number))],
        }
        self.graphctl(
            "record", "review-fanout-assessment", "--run-id", "RUN-1", "--request-slot-id", slot,
            "--assessment-manifest", str(self.inbox_manifest(assessment)), "--authority-ref", "authority:test",
            "--op-id", "round-{}-assessment".format(round_number),
        )
        child = self.claim()
        while child.get("depth") != 1:
            self.success(child, "APPROVE")
            child = self.claim()
        finding = {"finding_id": finding_id, "acceptance_id": "AC-001", "location": "docs/Cache.cs",
                   "defect_id": "RACE", "summary": "Cross-file race", "fix_variant": "Serialize updates",
                   "evidence_ids": ["E-1"]}
        self.record(child, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": child["branch_id"], "status": "succeeded",
            "output_kind": "delivery_review",
            "evidence": [], "decision": "REVISE", "findings": [finding],
        })
        if not claim_parent:
            return recorded, None, preliminary, request
        resumed = self.claim()
        while resumed["branch_id"] != parent["branch_id"]:
            self.success(resumed, "APPROVE")
            resumed = self.claim()
        return recorded, resumed, preliminary, request

    def test_resumed_reviewer_dispatch_uses_explicit_read_only_allowlist(self):
        policy = json.loads((self.repo / ".codex" / "engineering-graph.json").read_text(encoding="utf-8"))
        capabilities = {
            (item["effect"], item["action"], item["target_ref"])
            for role_capabilities in policy["role_capabilities"].values()
            for item in role_capabilities
        }
        self.assertTrue({"filesystem_read", "filesystem_write", "command", "external_read"}.issubset(
            {item[0] for item in capabilities}
        ))
        task = self.task()
        task["authority"]["capabilities"] = [
            {"effect": effect, "action": action, "target_ref": target}
            for effect, action, target in sorted(capabilities)
        ]
        parent = self._to_delivery_review(task=task)
        self._delegate_round(parent, 1, "REV-701", claim_parent=False)
        expected = [
            {"effect": "filesystem_read", "action": "read", "target_ref": "repo:docs/"},
            {"effect": "filesystem_read", "action": "read", "target_ref": "repo:src/"},
        ]
        for command in (("ready", "--all"), ("next", "--all")):
            visible = self.graphctl(*command, "--run-id", "RUN-1")["branches"]
            dispatch = next(item for item in visible if item["branch_id"] == parent["branch_id"])
            self._assert_dispatch_redacted(dispatch, expected)
            self.assertEqual(
                dispatch["inputs"][0]["content"]["assignments"][0]["effect_capabilities"],
                [{"effect": "filesystem_read", "action": "read", "target_ref": "repo:docs/"}],
            )
        self.store = StateStore(self.root / "codex")
        self.graphctl(
            "resume", "--run-id", "RUN-1",
            "--ack-degraded-permissions", "--ack-degraded-durability",
        )
        resumed = self.graphctl("next", "--all", "--run-id", "RUN-1")["branches"]
        self._assert_dispatch_redacted(
            next(item for item in resumed if item["branch_id"] == parent["branch_id"]), expected,
        )
        claimed = self.claim()
        while claimed["branch_id"] != parent["branch_id"]:
            self.success(claimed, "APPROVE")
            claimed = self.claim()
        self._assert_dispatch_redacted(claimed, expected)
        self.assertIsNotNone(claimed["attempt_id"])
        self.assertIsNotNone(claimed["claim_digest"])
        self.assertIsNotNone(claimed["lease_expires_at"])
        self.assertIn("claim_token", claimed)

    def test_supervisor_records_dispatches_and_settles_approved_request(self):
        parent = self._to_delivery_review()
        evidence = self._approved_evidence(parent)
        preliminary = {
            "schema_version": 1, "kind": "review_preliminary", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"], "generation": 0,
            "findings": [], "evidence": [{"evidence_id": "E-1", **evidence}],
        }
        request = {
            "schema_version": 1, "kind": "review_fanout_request", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"], "round": 1,
            "members": [{"assignment_id": "correctness", "ordinal": 1, "reason_code": "CROSS_FILE",
                         "acceptance_ids": ["AC-001"], "evidence_ids": ["E-1"]}],
        }
        preliminary_path = self.inbox_manifest(preliminary, "preliminary.json")
        request_path = self.inbox_manifest(request, "request.json")
        recorded = self.graphctl(
            "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", parent["branch_id"],
            "--attempt-id", parent["attempt_id"], "--claim-token", parent["claim_token"],
            "--preliminary-manifest", str(preliminary_path), "--request-manifest", str(request_path),
            "--authority-ref", "authority:test", "--op-id", "review-fanout-1",
        )
        slot = recorded["request_slot_id"]
        self.assertEqual(recorded["dispatch_cost"], 3)
        waiting = next(item for item in self.graphctl("status", "--run-id", "RUN-1")["branches"]
                       if item["branch_id"] == parent["branch_id"])
        self.assertEqual((waiting["status"], waiting.get("attempt_id"), waiting.get("claim_digest"), waiting.get("lease_expires_at")),
                         ("waiting_for_review_children", None, None, None))
        revision = recorded["state_revision"]
        replayed = self.graphctl(
            "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", parent["branch_id"],
            "--attempt-id", parent["attempt_id"], "--claim-token", parent["claim_token"],
            "--preliminary-manifest", str(preliminary_path), "--request-manifest", str(request_path),
            "--authority-ref", "authority:test", "--op-id", "review-fanout-1",
        )
        self.assertEqual((replayed["code"], replayed["state_revision"]), ("REPLAYED", revision))
        conflicts = [
            (preliminary_path, request_path, "authority:test"),
            (self.inbox_manifest({**preliminary, "findings": [{
                "finding_id": "REV-099", "acceptance_id": "AC-001", "location": "docs/Cache.cs",
                "defect_id": "PRELIM", "summary": "preliminary", "fix_variant": "inspect", "evidence_ids": ["E-1"],
            }]}, "changed-preliminary.json"), request_path, "authority:test"),
            (preliminary_path, self.inbox_manifest({**request, "members": [{**request["members"][0], "ordinal": 2}]}, "changed-request.json"), "authority:test"),
            (preliminary_path, request_path, "authority:other"),
        ]
        for index, (prelim, requested, authority) in enumerate(conflicts):
            with self.subTest(replay=index), self.assertRaisesRegex(StateError, "DELEGATION_SLOT_CONFLICT"):
                self.graphctl(
                    "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", parent["branch_id"],
                    "--attempt-id", parent["attempt_id"], "--claim-token", parent["claim_token"],
                    "--preliminary-manifest", str(prelim), "--request-manifest", str(requested),
                    "--authority-ref", authority, "--op-id", "review-fanout-fresh-" + str(index),
                )
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["state_revision"], revision)
        assessment_evidence = self.repo_artifact("finding", "review-assessment")
        assessment = {
            "schema_version": 1, "kind": "fanout_assessment", "run_id": "RUN-1", "fanout_id": slot,
            "members": [{"branch_id": recorded["child_branch_ids"][0], "resources": {
                "writable_paths": [], "mutable_state_refs": [], "exclusive_device_refs": [], "services": [],
            }}], "dependencies": [], "evidence": [assessment_evidence],
        }
        assessment_path = self.inbox_manifest(assessment, "review-assessment.json")
        self.graphctl(
            "record", "review-fanout-assessment", "--run-id", "RUN-1", "--request-slot-id", slot,
            "--assessment-manifest", str(assessment_path), "--authority-ref", "authority:test",
            "--op-id", "review-assessment-1",
        )
        child = self.claim()
        if child.get("depth") != 1:
            self.success(child, "APPROVE")
            child = self.claim()
        self.assertEqual((child["parent_branch_id"], child["depth"], child["effect_capabilities"]), (parent["branch_id"], 1, [{"effect": "filesystem_read", "action": "read", "target_ref": "repo:docs/"}]))
        self.assertEqual(child["inputs"], [])
        redacted = json.dumps(child["review_assignment"])
        for forbidden in ("repo:docs/artifacts", "ledger:", "authority_ref", "actor", "host_identity", "budget", "operation"):
            self.assertNotIn(forbidden, redacted)
        finding = {"finding_id": "REV-101", "acceptance_id": "AC-001", "location": "docs/Cache.cs", "defect_id": "RACE", "summary": "Cross-file race", "fix_variant": "Serialize updates", "evidence_ids": ["E-1"]}
        invalid_findings = [
            [{**finding, "acceptance_id": "AC-999"}],
            [{**finding, "evidence_ids": ["E-OTHER"]}],
            [{**finding, "location": "src/Cache.cs"}],
            [finding, finding],
            [{**finding, "finding_id": "invalid"}],
        ]
        for invalid in invalid_findings:
            before = self.graphctl("status", "--run-id", "RUN-1")["state_revision"]
            with self.assertRaises(ContractError):
                self.record(child, {
                    "schema_version": 1, "run_id": "RUN-1", "branch_id": child["branch_id"], "status": "succeeded",
                    "output_kind": "delivery_review", "evidence": [],
                    "decision": "REVISE", "findings": invalid,
                })
            self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["state_revision"], before)
        self.record(child, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": child["branch_id"], "status": "succeeded",
            "output_kind": "delivery_review", "evidence": [], "decision": "REVISE", "findings": [finding],
        })
        ready = self.graphctl("next", "--run-id", "RUN-1", "--all")
        ready_parent = next(item for item in ready["branches"] if item["branch_id"] == parent["branch_id"])
        self._assert_dispatch_redacted(ready_parent)
        resumed = self.claim()
        self.assertEqual(resumed["branch_id"], parent["branch_id"])
        self._assert_dispatch_redacted(resumed)
        continuation = resumed["review_continuation"]
        serialized_continuation = json.dumps(continuation)
        for forbidden in ("operation_id", "authority_ref", "host_identity", "actor", "ledger_path", "claim_token"):
            self.assertNotIn(forbidden, serialized_continuation)
        collection = resumed["inputs"][0]["content"]["nested_collections"][-1]
        sources = sorted([[provenance["request_slot_id"], issue["issue_key"], provenance["branch_id"],
                           provenance["finding_id"], provenance["assignment_id"], provenance["ordinal"]]
                          for issue in collection["issues"] for provenance in issue["provenance"]])
        final_artifact = self.repo_artifact("delivery_review", "parent-final")
        self.record(resumed, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": resumed["branch_id"], "status": "succeeded",
            "output_kind": "delivery_review", "artifact_ref": final_artifact, "evidence": [], "decision": "REVISE",
            "findings": [{"finding_id": "REV-101", "disposition": "repair"}],
            "review_request_slots": continuation["review_request_slots"],
            "child_members": continuation["child_members"], "terminal_non_successes": [], "finding_sources": sources,
        })
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(status["reviewer_delegations"][0]["status"], "sealed")
        self.assertEqual(status["reviewer_delegations"][0]["dispatch_cost"], 3)
        remaining = [item for item in status["branches"] if item["stage"] == "delivery" and item["status"] == "ready"]
        if remaining:
            self.success(self.claim(), "APPROVE")
        self.advance("delivery_collection")
        supervisor = self.claim()
        outer = next(item["content"] for item in supervisor["inputs"]
                     if item["kind"] == "collection" and item.get("content", {}).get("kind") == "collection")
        parent_member = next(item for item in outer["members"] if item["branch_id"] == parent["branch_id"])
        self.assertEqual(parent_member["result"]["review_request_slots"], continuation["review_request_slots"])
        nested = [item["content"] for item in supervisor["inputs"]
                  if item["kind"] == "collection" and item.get("content", {}).get("kind") == "review_nested_collection"]
        self.assertEqual([item["request_slot_id"] for item in nested], [slot])

    def test_old_parent_fence_is_rejected_atomically(self):
        parent = self._to_delivery_review()
        evidence = self._approved_evidence(parent)
        preliminary_path = self.inbox_manifest({
            "schema_version": 1, "kind": "review_preliminary", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"],
            "generation": 0, "findings": [], "evidence": [{"evidence_id": "E-1", **evidence}],
        })
        request_path = self.inbox_manifest({
            "schema_version": 1, "kind": "review_fanout_request", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"], "round": 1,
            "members": [{"assignment_id": "correctness", "ordinal": 1, "reason_code": "CROSS_FILE",
                         "acceptance_ids": ["AC-001"], "evidence_ids": ["E-1"]}],
        })
        before = self.graphctl("status", "--run-id", "RUN-1")["state_revision"]
        with self.assertRaisesRegex(StateError, "ATTEMPT_FENCE_MISMATCH"):
            self.graphctl(
                "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", parent["branch_id"],
                "--attempt-id", parent["attempt_id"], "--claim-token", "wrong",
                "--preliminary-manifest", str(preliminary_path), "--request-manifest", str(request_path),
                "--authority-ref", "authority:test", "--op-id", "old-fence",
            )
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["state_revision"], before)

    def test_two_rounds_bind_cumulative_raw_collections_and_round_three_is_rejected(self):
        parent = self._to_delivery_review(max_rounds=2)
        first, resumed, _, _ = self._delegate_round(parent, 1, "REV-301")
        second, resumed, preliminary, request = self._delegate_round(resumed, 2, "REV-301")
        self.store = StateStore(self.root / "codex")
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["status"], "active")
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            connection.execute("DROP TRIGGER review_request_update_guard")
            connection.execute(
                "UPDATE review_delegation_requests SET round_number=3 WHERE request_slot_id=?",
                (second["request_slot_id"],),
            )
            connection.commit()
        with self.assertRaisesRegex(StateError, "DELEGATION_ROUND_LIMIT"):
            self.graphctl("resume", "--run-id", "RUN-1")
        with self.store.connect(database) as connection:
            connection.execute(
                "UPDATE review_delegation_requests SET round_number=2 WHERE request_slot_id=?",
                (second["request_slot_id"],),
            )
            connection.commit()
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["status"], "active")
        continuation = resumed["review_continuation"]
        self.assertEqual([item[0] for item in continuation["review_request_slots"]],
                         [first["request_slot_id"], second["request_slot_id"]])
        self.assertEqual(len(continuation["child_members"]), 2)
        request3 = {**request, "parent_attempt_id": resumed["attempt_id"], "round": 3}
        preliminary3 = {**preliminary, "parent_attempt_id": resumed["attempt_id"]}
        with self.assertRaisesRegex(StateError, "DELEGATION_ROUND_LIMIT"):
            self.graphctl(
                "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", resumed["branch_id"],
                "--attempt-id", resumed["attempt_id"], "--claim-token", resumed["claim_token"],
                "--preliminary-manifest", str(self.inbox_manifest(preliminary3, "preliminary-round-3.json")),
                "--request-manifest", str(self.inbox_manifest(request3, "request-round-3.json")),
                "--authority-ref", "authority:test", "--op-id", "round-3-request",
            )
        self.record(resumed, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": resumed["branch_id"], "status": "succeeded",
            "output_kind": "delivery_review", "artifact_ref": self.repo_artifact("delivery_review", "two-round-final"),
            "evidence": [], "decision": "REVISE",
            "findings": [{"finding_id": "REV-301", "disposition": "repair"}],
            "review_request_slots": continuation["review_request_slots"],
            "child_members": continuation["child_members"], "terminal_non_successes": continuation["terminal_non_successes"],
            "finding_sources": continuation["finding_sources"],
        })
        self.advance("delivery_collection")
        supervisor = self.claim()
        nested = [item["content"] for item in supervisor["inputs"]
                  if item["kind"] == "collection" and item.get("content", {}).get("kind") == "review_nested_collection"]
        self.assertEqual(sorted(item["request_slot_id"] for item in nested),
                         sorted([first["request_slot_id"], second["request_slot_id"]]))

    def _delegated_supervisor(self, finding_id="REV-801"):
        parent = self._to_delivery_review()
        _, resumed, _, _ = self._delegate_round(parent, 1, finding_id)
        continuation = resumed["review_continuation"]
        self.record(resumed, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": resumed["branch_id"],
            "status": "succeeded", "output_kind": "delivery_review",
            "artifact_ref": self.repo_artifact("delivery_review", "supervisor-parent-final"),
            "evidence": [], "decision": "BLOCK",
            "findings": [{"finding_id": finding_id, "disposition": "block"}],
            "review_request_slots": continuation["review_request_slots"],
            "child_members": continuation["child_members"],
            "terminal_non_successes": continuation["terminal_non_successes"],
            "finding_sources": continuation["finding_sources"],
        })
        while True:
            status = self.graphctl("status", "--run-id", "RUN-1")
            ready = [item for item in status["branches"]
                     if item["stage"] == "delivery" and item["status"] == "ready"]
            if not ready:
                break
            self.success(self.claim(), "APPROVE")
        self.advance("delivery_collection")
        supervisor = self.claim()
        self.assertEqual(supervisor["node_key"], "supervisor_delivery_consolidation")
        outer = next(item["content"] for item in supervisor["inputs"]
                     if item["kind"] == "collection" and item["content"].get("kind") == "collection")
        nested = next(item["content"] for item in supervisor["inputs"]
                      if item["kind"] == "collection"
                      and item["content"].get("kind") == "review_nested_collection")
        issue = nested["issues"][0]
        source_identities = sorted([
            nested["request_slot_id"], item["branch_id"], item["finding_id"]
        ] for item in issue["provenance"])
        return supervisor, outer, issue["issue_key"], source_identities, finding_id

    def _record_delegated_supervisor_disposition(self, disposition, outcome):
        supervisor, outer, issue_key, source_identities, finding_id = self._delegated_supervisor()
        self.record(supervisor, {
            "schema_version": 1, "kind": "delivery_consolidation", "run_id": "RUN-1",
            "join_id": outer["join_id"], "generation": 0,
            "source_branch_ids": [item["branch_id"] for item in outer["members"]],
            "finding_dispositions": [{"finding_id": finding_id, "disposition": "block"}],
            "delegated_finding_dispositions": [{
                "issue_key": issue_key, "source_identities": source_identities,
                "disposition": disposition,
            }],
            "outcome": outcome,
        })
        return self.advance("delivery_consolidation")

    def test_supervisor_delegated_accept_controls_outcome(self):
        advanced = self._record_delegated_supervisor_disposition("accept", "ACCEPT")
        self.assertEqual(advanced["outcome"], "ACCEPT")
        self.assertTrue(any(item["join_key"] == "closure" for item in
                            self.graphctl("status", "--run-id", "RUN-1")["joins"]))

    def test_supervisor_delegated_repair_controls_outcome(self):
        advanced = self._record_delegated_supervisor_disposition("repair", "REPAIR")
        self.assertEqual(advanced["outcome"], "REPAIR")
        self.assertTrue(advanced["successor_branch_ids"])

    def test_supervisor_delegated_redesign_controls_outcome(self):
        advanced = self._record_delegated_supervisor_disposition("redesign", "REDESIGN")
        self.assertEqual(advanced["outcome"], "REDESIGN")
        self.assertTrue(advanced["successor_branch_ids"])

    def test_supervisor_delegated_block_controls_outcome(self):
        advanced = self._record_delegated_supervisor_disposition("block", "BLOCK")
        self.assertEqual(advanced["outcome"], "BLOCK")
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["status"], "blocked")

    def test_supervisor_delegated_outcome_contradiction_is_rejected(self):
        supervisor, outer, issue_key, source_identities, finding_id = self._delegated_supervisor()
        self.record(supervisor, {
            "schema_version": 1, "kind": "delivery_consolidation", "run_id": "RUN-1",
            "join_id": outer["join_id"], "generation": 0,
            "source_branch_ids": [item["branch_id"] for item in outer["members"]],
            "finding_dispositions": [{"finding_id": finding_id, "disposition": "block"}],
            "delegated_finding_dispositions": [{
                "issue_key": issue_key, "source_identities": source_identities,
                "disposition": "accept",
            }],
            "outcome": "BLOCK",
        })
        with self.assertRaisesRegex(ContractError, "OUTCOME_PRECEDENCE_MISMATCH"):
            self.advance("delivery_consolidation")

    def test_exact_request_cost_boundary_and_collected_skips(self):
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        assignment = policy["reviewer_delegation"]["assignments"][0]
        assignment.update({"model": "gpt-5.6-sol", "reasoning_effort": "max",
                           "dispatch_weight": 5, "max_instances": 3})
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.policy_bytes = policy_path.read_bytes()
        delegated_task = task_config()
        delegated_task["limits"]["max_request_rounds"] = 2
        delegated_task["assignments"][0]["max_instances"] = 3
        parent = self._to_delivery_review(max_rounds=2, delegation_task=delegated_task)
        evidence = self._approved_evidence(parent)
        preliminary = {
            "schema_version": 1, "kind": "review_preliminary", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"],
            "generation": 0, "findings": [], "evidence": [{"evidence_id": "E-1", **evidence}],
        }
        request = {
            "schema_version": 1, "kind": "review_fanout_request", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"], "round": 1,
            "members": [{"assignment_id": "correctness", "ordinal": ordinal, "reason_code": "CROSS_FILE",
                         "acceptance_ids": ["AC-001"], "evidence_ids": ["E-1"]} for ordinal in (1, 2, 3)],
        }
        recorded = self.graphctl(
            "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", parent["branch_id"],
            "--attempt-id", parent["attempt_id"], "--claim-token", parent["claim_token"],
            "--preliminary-manifest", str(self.inbox_manifest(preliminary)),
            "--request-manifest", str(self.inbox_manifest(request)), "--authority-ref", "authority:test",
            "--op-id", "boundary-request",
        )
        self.assertEqual((recorded["dispatch_cost"], len(recorded["child_branch_ids"])), (15, 3))
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertTrue(all(next(item for item in status["branches"] if item["branch_id"] == child)["status"] == "pending"
                            for child in recorded["child_branch_ids"]))
        assessment = {
            "schema_version": 1, "kind": "fanout_assessment", "run_id": "RUN-1",
            "fanout_id": recorded["request_slot_id"],
            "members": [{"branch_id": child, "resources": {"writable_paths": [], "mutable_state_refs": [],
                         "exclusive_device_refs": [], "services": []}} for child in recorded["child_branch_ids"]],
            "dependencies": [], "evidence": [self.repo_artifact("finding", "boundary-assessment")],
        }
        self.graphctl(
            "record", "review-fanout-assessment", "--run-id", "RUN-1",
            "--request-slot-id", recorded["request_slot_id"],
            "--assessment-manifest", str(self.inbox_manifest(assessment)), "--authority-ref", "authority:test",
            "--op-id", "boundary-assessment",
        )
        for index, child_id in enumerate(recorded["child_branch_ids"]):
            evidence_path = self.control_manifest("skip", "NOT_NEEDED", {"branch_id": child_id})
            self.graphctl(
                "record", "skip", "--run-id", "RUN-1", "--branch-id", child_id,
                "--reason-code", "NOT_NEEDED", "--evidence-manifest", str(evidence_path),
                "--op-id", "boundary-skip-{}".format(index),
            )
        resumed = self.claim()
        while resumed["branch_id"] != parent["branch_id"]:
            self.success(resumed, "APPROVE")
            resumed = self.claim()
        self.assertEqual([item["status"] for item in resumed["review_continuation"]["terminal_non_successes"]],
                         ["skipped", "skipped", "skipped"])
        preliminary2 = {**preliminary, "parent_attempt_id": resumed["attempt_id"]}
        request2 = {**request, "parent_attempt_id": resumed["attempt_id"], "round": 2,
                    "members": [request["members"][0]]}
        before = self.graphctl("status", "--run-id", "RUN-1")["state_revision"]
        with self.assertRaisesRegex(StateError, "DELEGATION_COST_LIMIT"):
            self.graphctl(
                "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", resumed["branch_id"],
                "--attempt-id", resumed["attempt_id"], "--claim-token", resumed["claim_token"],
                "--preliminary-manifest", str(self.inbox_manifest(preliminary2)),
                "--request-manifest", str(self.inbox_manifest(request2)), "--authority-ref", "authority:test",
                "--op-id", "boundary-over-cost",
            )
        self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["state_revision"], before)

    def test_review_assessment_reconstruction_rejects_invalid_and_tampered_state(self):
        parent = self._to_delivery_review()
        evidence = self._approved_evidence(parent)
        preliminary = {
            "schema_version": 1, "kind": "review_preliminary", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"],
            "generation": 0, "findings": [], "evidence": [{"evidence_id": "E-1", **evidence}],
        }
        request = {
            "schema_version": 1, "kind": "review_fanout_request", "run_id": "RUN-1",
            "parent_branch_id": parent["branch_id"], "parent_attempt_id": parent["attempt_id"], "round": 1,
            "members": [{"assignment_id": "correctness", "ordinal": ordinal, "reason_code": "CROSS_FILE",
                         "acceptance_ids": ["AC-001"], "evidence_ids": ["E-1"]} for ordinal in (1, 2)],
        }
        recorded = self.graphctl(
            "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", parent["branch_id"],
            "--attempt-id", parent["attempt_id"], "--claim-token", parent["claim_token"],
            "--preliminary-manifest", str(self.inbox_manifest(preliminary)),
            "--request-manifest", str(self.inbox_manifest(request)), "--authority-ref", "authority:test",
            "--op-id", "assessment-reconstruction-request",
        )
        children = recorded["child_branch_ids"]
        empty_resources = {"writable_paths": [], "mutable_state_refs": [], "exclusive_device_refs": [], "services": []}
        base = {
            "schema_version": 1, "kind": "fanout_assessment", "run_id": "RUN-1",
            "fanout_id": recorded["request_slot_id"],
            "members": [{"branch_id": child, "resources": dict(empty_resources)} for child in children],
            "dependencies": [], "evidence": [self.repo_artifact("finding", "reconstruction-assessment")],
        }
        path_name = "Docs/Shared.cs" if os.path.normcase("A") == os.path.normcase("a") else "docs/shared.cs"
        invalid = []
        invalid.append({**base, "kind": "wrong_kind"})
        invalid.append({**base, "members": base["members"][:1]})
        invalid.append({**base, "dependencies": [
            {"before_branch_id": children[0], "after_branch_id": children[1], "reason": "first"},
            {"before_branch_id": children[1], "after_branch_id": children[0], "reason": "cycle"},
        ]})
        conflict_members = copy.deepcopy(base["members"])
        conflict_members[0]["resources"]["writable_paths"] = [{"path": "docs/shared.cs", "scope": "exact"}]
        conflict_members[1]["resources"]["writable_paths"] = [{"path": path_name, "scope": "exact"}]
        invalid.append({**base, "members": conflict_members})
        before = self.graphctl("status", "--run-id", "RUN-1")["state_revision"]
        for index, manifest in enumerate(invalid):
            with self.assertRaises((ContractError, StateError)):
                self.graphctl(
                    "record", "review-fanout-assessment", "--run-id", "RUN-1",
                    "--request-slot-id", recorded["request_slot_id"],
                    "--assessment-manifest", str(self.inbox_manifest(manifest)),
                    "--authority-ref", "authority:test", "--op-id", "invalid-review-assessment-{}".format(index),
                )
            self.assertEqual(self.graphctl("status", "--run-id", "RUN-1")["state_revision"], before)
        self.graphctl(
            "record", "review-fanout-assessment", "--run-id", "RUN-1",
            "--request-slot-id", recorded["request_slot_id"],
            "--assessment-manifest", str(self.inbox_manifest(base)), "--authority-ref", "authority:test",
            "--op-id", "valid-review-assessment",
        )
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            connection.execute(
                "INSERT INTO review_delegation_dependencies VALUES(?,?,?,?)",
                (recorded["request_slot_id"], children[0], children[1], "tampered"),
            )
            connection.commit()
        with self.assertRaisesRegex(StateError, "DELEGATION_ASSESSMENT_INVALID"):
            self.graphctl("status", "--run-id", "RUN-1")
        with self.store.connect(database) as connection:
            connection.execute("DROP TRIGGER review_dependency_delete_guard")
            connection.execute("DELETE FROM review_delegation_dependencies WHERE request_slot_id=?",
                               (recorded["request_slot_id"],))
            connection.execute("DROP TRIGGER review_fanout_update_guard")
            connection.execute("UPDATE review_delegation_fanouts SET host_identity='tampered-host' WHERE request_slot_id=?",
                               (recorded["request_slot_id"],))
            connection.commit()
        with self.assertRaisesRegex(StateError, "DELEGATION_ASSESSMENT_INVALID"):
            self.graphctl("resume", "--run-id", "RUN-1")

    def test_mixed_terminal_raw_results_survive_restart_and_reach_supervisor(self):
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["reviewer_delegation"]["assignments"][0]["max_instances"] = 3
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.policy_bytes = policy_path.read_bytes()
        delegated_task = task_config()
        delegated_task["limits"]["max_request_rounds"] = 2
        delegated_task["assignments"][0]["max_instances"] = 3
        parent = self._to_delivery_review(max_rounds=2, delegation_task=delegated_task)

        def start_round(current_parent, round_number, count):
            evidence = self._approved_evidence(current_parent)
            preliminary = {
                "schema_version": 1, "kind": "review_preliminary", "run_id": "RUN-1",
                "parent_branch_id": current_parent["branch_id"],
                "parent_attempt_id": current_parent["attempt_id"], "generation": 0,
                "findings": [], "evidence": [{"evidence_id": "E-1", **evidence}],
            }
            request = {
                "schema_version": 1, "kind": "review_fanout_request", "run_id": "RUN-1",
                "parent_branch_id": current_parent["branch_id"],
                "parent_attempt_id": current_parent["attempt_id"], "round": round_number,
                "members": [{"assignment_id": "correctness", "ordinal": ordinal,
                             "reason_code": "CROSS_FILE", "acceptance_ids": ["AC-001"],
                             "evidence_ids": ["E-1"]} for ordinal in range(1, count + 1)],
            }
            recorded = self.graphctl(
                "record", "review-fanout", "--run-id", "RUN-1", "--branch-id", current_parent["branch_id"],
                "--attempt-id", current_parent["attempt_id"], "--claim-token", current_parent["claim_token"],
                "--preliminary-manifest", str(self.inbox_manifest(preliminary)),
                "--request-manifest", str(self.inbox_manifest(request)), "--authority-ref", "authority:test",
                "--op-id", "mixed-request-{}".format(round_number),
            )
            assessment = {
                "schema_version": 1, "kind": "fanout_assessment", "run_id": "RUN-1",
                "fanout_id": recorded["request_slot_id"],
                "members": [{"branch_id": child, "resources": {"writable_paths": [], "mutable_state_refs": [],
                             "exclusive_device_refs": [], "services": []}} for child in recorded["child_branch_ids"]],
                "dependencies": [], "evidence": [self.repo_artifact("finding", "mixed-assessment-{}".format(round_number))],
            }
            self.graphctl(
                "record", "review-fanout-assessment", "--run-id", "RUN-1",
                "--request-slot-id", recorded["request_slot_id"],
                "--assessment-manifest", str(self.inbox_manifest(assessment)), "--authority-ref", "authority:test",
                "--op-id", "mixed-assessment-{}".format(round_number),
            )
            return recorded

        def claim_delegated():
            branch = self.claim()
            while branch.get("depth") != 1:
                self.success(branch, "APPROVE")
                branch = self.claim()
            return branch

        first = start_round(parent, 1, 3)
        succeeded = claim_delegated()
        success_finding = {"finding_id": "REV-501", "acceptance_id": "AC-001",
                           "location": "docs/Cache.cs", "defect_id": "RACE", "summary": "race",
                           "fix_variant": "serialize", "evidence_ids": ["E-1"]}
        self.record(succeeded, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": succeeded["branch_id"],
            "status": "succeeded", "output_kind": "delivery_review", "evidence": [],
            "decision": "REVISE", "findings": [success_finding],
        })
        failed = claim_delegated()
        self.record(failed, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": failed["branch_id"],
            "status": "failed", "output_kind": "delivery_review", "evidence": [],
            "failure_code": "REVIEW_FAILED", "findings": [],
        })
        timed_out = claim_delegated()
        self.graphctl(
            "record", "timeout", "--run-id", "RUN-1", "--branch-id", timed_out["branch_id"],
            "--attempt-id", timed_out["attempt_id"], "--claim-token", timed_out["claim_token"],
            "--reason-code", "LEASE_TIMEOUT",
            "--evidence-manifest", str(self.control_manifest("timeout", "LEASE_TIMEOUT", timed_out)),
            "--op-id", "mixed-timeout-1",
        )
        for branch, label in ((failed, "failure"), (timed_out, "timeout")):
            self.graphctl(
                "record", "retry", "--run-id", "RUN-1", "--branch-id", branch["branch_id"],
                "--reason-code", "RETRY_REVIEW", "--op-id", "mixed-retry-" + label,
            )
        for _ in range(2):
            retried = claim_delegated()
            if retried["branch_id"] == failed["branch_id"]:
                self.record(retried, {
                    "schema_version": 1, "run_id": "RUN-1", "branch_id": retried["branch_id"],
                    "status": "failed", "output_kind": "delivery_review", "evidence": [],
                    "failure_code": "REVIEW_FAILED", "findings": [],
                })
            else:
                self.graphctl(
                    "record", "timeout", "--run-id", "RUN-1", "--branch-id", retried["branch_id"],
                    "--attempt-id", retried["attempt_id"], "--claim-token", retried["claim_token"],
                    "--reason-code", "LEASE_TIMEOUT",
                    "--evidence-manifest", str(self.control_manifest("timeout", "LEASE_TIMEOUT", retried)),
                    "--op-id", "mixed-timeout-2",
                )
        resumed = self.claim()
        while resumed["branch_id"] != parent["branch_id"]:
            self.success(resumed, "APPROVE")
            resumed = self.claim()
        second = start_round(resumed, 2, 1)
        skipped_id = second["child_branch_ids"][0]
        self.graphctl(
            "record", "skip", "--run-id", "RUN-1", "--branch-id", skipped_id,
            "--reason-code", "NOT_NEEDED",
            "--evidence-manifest", str(self.control_manifest("skip", "NOT_NEEDED", {"branch_id": skipped_id})),
            "--op-id", "mixed-skip",
        )
        ready = self.graphctl("next", "--run-id", "RUN-1", "--all")
        ready_parent = next(item for item in ready["branches"] if item["branch_id"] == parent["branch_id"])
        self._assert_dispatch_redacted(ready_parent)
        self.store = StateStore(self.root / "codex")
        resumed = self.claim()
        while resumed["branch_id"] != parent["branch_id"]:
            self.success(resumed, "APPROVE")
            resumed = self.claim()
        self._assert_dispatch_redacted(resumed)
        continuation = resumed["review_continuation"]
        self.record(resumed, {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": resumed["branch_id"],
            "status": "succeeded", "output_kind": "delivery_review",
            "artifact_ref": self.repo_artifact("delivery_review", "mixed-parent-final"),
            "evidence": [], "decision": "REVISE",
            "findings": [{"finding_id": "REV-501", "disposition": "repair"}],
            "review_request_slots": continuation["review_request_slots"],
            "child_members": continuation["child_members"],
            "terminal_non_successes": continuation["terminal_non_successes"],
            "finding_sources": continuation["finding_sources"],
        })
        status = self.graphctl("status", "--run-id", "RUN-1")
        for item in [branch for branch in status["branches"] if branch["stage"] == "delivery" and branch["status"] == "ready"]:
            self.success(self.claim(), "APPROVE")
        self.advance("delivery_collection")
        supervisor = self.claim()
        nested = [item["content"] for item in supervisor["inputs"]
                  if item["kind"] == "collection" and item.get("content", {}).get("kind") == "review_nested_collection"]
        self.assertEqual(len(nested), 2)
        raw_members = [member for collection in nested for member in collection["members"]]
        by_status = {member["status"]: member for member in raw_members}
        self.assertEqual(set(by_status), {"succeeded", "failed", "timed_out", "skipped"})
        self.assertEqual(by_status["succeeded"]["terminal"]["result"]["status"], "succeeded")
        self.assertEqual(by_status["failed"]["terminal"]["result"]["failure_code"], "REVIEW_FAILED")
        self.assertEqual(by_status["timed_out"]["terminal"]["result"]["kind"], "timeout")
        self.assertEqual(by_status["skipped"]["terminal"]["result"]["kind"], "skip")
        self.assertEqual(len(by_status["failed"]["terminal"]["attempts"]), 2)
        self.assertEqual(len(by_status["timed_out"]["terminal"]["attempts"]), 2)
        self.assertEqual(by_status["skipped"]["terminal"]["attempts"], [])
        for member in raw_members:
            terminal = member["terminal"]
            self.assertTrue(terminal["result_artifact"]["ref"].startswith("ledger:"))
            self.assertEqual(terminal["result_artifact"]["sha256"], terminal["result_digest"])
