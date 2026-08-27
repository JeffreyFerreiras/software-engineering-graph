import copy
import os
import json
from pathlib import Path

from graph_engine.config import (
    ENGINE_ARTIFACT_MAX, ENGINE_COLLECTION_MAX_BYTES, ENGINE_COLLECTION_MAX_MEMBERS,
    load_policy,
)
from graph_engine.contracts import ContractError, validate_impact_map, validate_ref, validate_task_brief
from graph_engine.ids import sha256_bytes

from test_support import GraphCase


class ContractTests(GraphCase):
    def setUp(self):
        super().setUp()
        self.policy, self.snapshot = load_policy(self.repo)

    def test_real_policy_and_task_validate(self):
        task = validate_task_brief(self.task(tags=["security_privacy"]), self.snapshot.digest, self.policy)
        self.assertEqual(task["mandatory_impact_tags"], ["security_privacy"])

    def test_mapper_cannot_downgrade_or_remove_tag(self):
        task = validate_task_brief(self.task(tags=["security_privacy"]), self.snapshot.digest, self.policy)
        with self.assertRaisesRegex(ContractError, "ROUTE_DOWNGRADE"):
            validate_impact_map({"schema_version": 1, "task_id": "TASK-1", "route_label": "fast_path", "impact_tags": ["security_privacy"], "evidence_refs": []}, task, self.policy)
        with self.assertRaisesRegex(ContractError, "MANDATORY_TAG_REMOVED"):
            validate_impact_map({"schema_version": 1, "task_id": "TASK-1", "route_label": "full_delivery", "impact_tags": [], "evidence_refs": []}, task, self.policy)
        fast_task = validate_task_brief(self.task(route="fast_path"), self.snapshot.digest, self.policy)
        with self.assertRaisesRegex(ContractError, "FAST_PATH_INVARIANT"):
            validate_impact_map({"schema_version": 1, "task_id": "TASK-1", "route_label": "fast_path", "impact_tags": ["security_privacy"], "evidence_refs": []}, fast_task, self.policy)

    def test_advisory_task_cannot_receive_write_authority(self):
        task = self.task("advisory", "advisory")
        task["authority"]["capabilities"] = [
            {"effect": "filesystem_write", "action": "edit", "target_ref": "repo:docs/"}
        ]
        with self.assertRaisesRegex(ContractError, "ADVISORY_MUST_BE_READ_ONLY"):
            validate_task_brief(task, self.snapshot.digest, self.policy)

    def test_secret_fields_and_urls_are_rejected_without_echo(self):
        task = self.task()
        task["password"] = "do-not-echo"
        with self.assertRaises(ContractError) as captured:
            validate_task_brief(task, self.snapshot.digest, self.policy)
        self.assertNotIn("do-not-echo", str(captured.exception))
        with self.assertRaisesRegex(ContractError, "URL_FORBIDDEN"):
            validate_ref("https://example.invalid/token", "ref")

    def test_policy_cannot_raise_loop_limit(self):
        policy = copy.deepcopy(self.policy)
        policy["limits"]["design_revisions"] = 4
        (self.repo / ".codex" / "engineering-graph.json").write_text(__import__("json").dumps(policy), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "LIMIT_MAY_NOT_INCREASE"):
            load_policy(self.repo)

    def test_policy_cannot_add_engine_authority(self):
        policy = copy.deepcopy(self.policy)
        policy["role_capabilities"]["senior_engineer"].append(
            {"effect": "external_write", "action": "deploy", "target_ref": "production"}
        )
        (self.repo / ".codex" / "engineering-graph.json").write_text(__import__("json").dumps(policy), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "ENGINE_AUTHORITY_EXCEEDED"):
            load_policy(self.repo)

    def test_repository_added_checks_cannot_expand_command_capabilities(self):
        policy = copy.deepcopy(self.policy)
        policy["required_checks"]["repo-added"] = {
            "command_id": "repository-added-command", "mandatory": True,
        }
        policy["role_capabilities"]["senior_engineer"].append({
            "effect": "command", "action": "run", "target_ref": "repository-added-command",
        })
        (self.repo / ".codex" / "engineering-graph.json").write_text(
            json.dumps(policy), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "ENGINE_COMMAND_SET_CHANGED"):
            load_policy(self.repo)
        from graph_engine.config import ENGINE_ROLE_CAPABILITIES
        self.assertNotIn(("command", "run", "*"), ENGINE_ROLE_CAPABILITIES["senior_engineer"])

    def test_oversized_manifest_is_rejected(self):
        self.initialize()
        branch = self.claim()
        oversized = self.store.inbox_root("albanian-live-translate", "RUN-1") / "oversized.json"
        oversized.write_text('{"padding":"' + ("x" * 270000) + '"}', encoding="utf-8")
        if os.name != "nt":
            os.chmod(oversized, 0o600)
        with self.assertRaisesRegex(ContractError, "FILE_TOO_LARGE"):
            self.graphctl("record", "branch-result", "--run-id", "RUN-1", "--branch-id", branch["branch_id"], "--result-manifest", str(oversized), "--op-id", "oversized-1")

    def test_repository_policy_reaches_required_roles_and_checks(self):
        roles = {item["role"] for item in self.policy["node_templates"].values()}
        self.assertTrue({"impact_mapper", "tech_lead", "software_architect", "senior_engineer", "code_reviewer", "test_engineer", "supervisor"}.issubset(roles))
        self.assertEqual(self.policy["required_checks"]["repo-check"]["command_id"], "npm-run-check")
        self.assertEqual(set(self.policy["specialists"]), {"audio_realtime_translation", "ios_webkit_native", "release_operations", "security_privacy"})
        schema = json.loads((Path(__file__).parents[1] / "references" / "repository-config.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), set(self.policy))
        self.assertFalse(schema["additionalProperties"])
        maximum_reviewers = 2 + len(self.policy["specialists"])
        self.assertEqual(ENGINE_COLLECTION_MAX_MEMBERS, maximum_reviewers)
        self.assertEqual(
            self.policy["artifact_kinds"]["collection"]["max_bytes"],
            ENGINE_COLLECTION_MAX_BYTES,
        )
        self.assertGreaterEqual(
            ENGINE_COLLECTION_MAX_BYTES,
            maximum_reviewers * ENGINE_ARTIFACT_MAX["branch_result"] + 64 * 1024,
        )

    def test_policy_topology_roots_contracts_and_targets_are_engine_bounded(self):
        mutations = [
            lambda p: p["routes"]["full_delivery"].update(entry_node="senior_engineer"),
            lambda p: p["artifact_roots"].update(repo=["src/"]),
            lambda p: p["node_templates"]["architect"]["output_contract"].update(artifact_kind="technical_design"),
            lambda p: p["specialists"]["security_privacy"].update(mandatory=False),
            lambda p: p["artifact_kinds"]["finding"].update(extensions=[".exe"]),
            lambda p: p["compatible_engine"].update(min="3.0.0"),
            lambda p: p["role_capabilities"]["senior_engineer"].append(
                {"effect": "filesystem_write", "action": "edit", "target_ref": "repo:.codex/"}
            ),
            lambda p: p["role_capabilities"]["senior_engineer"].append(
                {"effect": "command", "action": "run", "target_ref": "unknown-command"}
            ),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                policy = copy.deepcopy(self.policy)
                mutate(policy)
                (self.repo / ".codex" / "engineering-graph.json").write_text(json.dumps(policy), encoding="utf-8")
                with self.assertRaises(ContractError):
                    load_policy(self.repo)
                (self.repo / ".codex" / "engineering-graph.json").write_bytes(self.policy_bytes)

    def test_task_is_minimized_and_external_artifacts_are_reverified(self):
        task = self.task()
        task["scope"] = {
            "included": ["customer-private-project-name"],
            "excluded": ["confidential-future-acquisition"],
        }
        self.initialize_task(task)
        db = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(db) as connection:
            stored = json.loads(connection.execute("SELECT task_json FROM runs").fetchone()[0])
        self.assertNotIn("objective", stored)
        self.assertNotIn("user_outcome", stored)
        self.assertNotIn("constraints", stored)
        self.assertNotIn("scope_ids", stored)
        database_bytes = db.read_bytes()
        self.assertNotIn(b"customer-private-project-name", database_bytes)
        self.assertNotIn(b"confidential-future-acquisition", database_bytes)
        self.assertEqual(stored["acceptance_ids"], ["AC-001"])
        (self.repo / "docs" / "engineering-graph.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "INPUT_DIGEST_MISMATCH"):
            self.graphctl("resume", "--run-id", "RUN-1", "--ack-degraded-permissions", "--ack-degraded-durability")

    def test_nonexistent_and_digest_mismatched_artifacts_are_rejected(self):
        self.initialize(); self.impact("full_delivery")
        missing = "ledger:missing#sha256=" + ("a" * 64)
        with self.assertRaisesRegex(ContractError, "LEDGER_ARTIFACT_NOT_FOUND"):
            self.graphctl("record", "acceptance-evidence", "--run-id", "RUN-1", "--criterion-id", "AC-001", "--artifact-ref", missing, "--artifact-sha256", "a" * 64, "--op-id", "missing-evidence")
        artifact = self.repo_artifact("acceptance_evidence", "digest-mismatch")
        with self.assertRaisesRegex(ContractError, "DIGEST_DISAGREEMENT"):
            self.graphctl("record", "acceptance-evidence", "--run-id", "RUN-1", "--criterion-id", "AC-001", "--artifact-ref", artifact["ref"], "--artifact-sha256", "b" * 64, "--op-id", "mismatch-evidence")
