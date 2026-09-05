import copy
import os
import json
import re
from pathlib import Path

from graph_engine.config import (
    ENGINE_ARTIFACT_MAX, ENGINE_COLLECTION_MAX_BYTES, ENGINE_COLLECTION_MAX_MEMBERS,
    load_policy,
)
from graph_engine.contracts import ContractError, validate_impact_map, validate_ref, validate_task_brief
from graph_engine.ids import sha256_bytes

from tests.test_support import GraphCase


def _validate_json_schema(value, schema, root, path="$", seen_refs=None):
    """Validate the repository fixture's schema subset with the standard library only."""
    seen_refs = set() if seen_refs is None else seen_refs
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise AssertionError("unsupported schema reference at " + path)
        target = root
        for part in ref[2:].split("/"):
            target = target[part]
        marker = (ref, path)
        if marker in seen_refs:
            raise AssertionError("recursive schema reference at " + path)
        return _validate_json_schema(value, target, root, path, seen_refs | {marker})

    if "anyOf" in schema or "oneOf" in schema:
        keyword = "anyOf" if "anyOf" in schema else "oneOf"
        errors = []
        matches = 0
        for candidate in schema[keyword]:
            try:
                _validate_json_schema(value, candidate, root, path, seen_refs)
                matches += 1
            except AssertionError as error:
                errors.append(str(error))
        if matches == 0:
            raise AssertionError("{}: no {} alternative matched ({})".format(path, keyword, "; ".join(errors)))
        if keyword == "oneOf" and matches != 1:
            raise AssertionError("{}: multiple oneOf alternatives matched".format(path))

    if "not" in schema:
        try:
            _validate_json_schema(value, schema["not"], root, path, seen_refs)
        except AssertionError:
            pass
        else:
            raise AssertionError("{}: forbidden schema matched".format(path))

    if "const" in schema and value != schema["const"]:
        raise AssertionError("{}: expected {!r}, got {!r}".format(path, schema["const"], value))
    if "enum" in schema and value not in schema["enum"]:
        raise AssertionError("{}: value is outside enum".format(path))

    expected_type = schema.get("type")
    if expected_type is not None:
        type_matches = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(item in type_matches and type_matches[item](value) for item in expected_types):
            raise AssertionError("{}: expected {}".format(path, expected_type))

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise AssertionError("{}: missing {}".format(path, ",".join(missing)))
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise AssertionError("{}: unknown {}".format(path, ",".join(sorted(unknown))))
        elif isinstance(schema.get("additionalProperties"), dict):
            additional_schema = schema["additionalProperties"]
            for key in sorted(set(value) - set(properties)):
                _validate_json_schema(
                    value[key], additional_schema, root, path + "." + key, seen_refs
                )
        for key, child_schema in properties.items():
            if key in value:
                _validate_json_schema(value[key], child_schema, root, path + "." + key, seen_refs)
        if len(value) < schema.get("minProperties", 0):
            raise AssertionError("{}: too few properties".format(path))
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            raise AssertionError("{}: invalid item count".format(path))
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(encoded) != len(set(encoded)):
                raise AssertionError("{}: duplicate items".format(path))
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_json_schema(item, schema["items"], root, "{}[{}]".format(path, index), seen_refs)
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            raise AssertionError("{}: invalid string length".format(path))
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise AssertionError("{}: pattern mismatch".format(path))
    elif isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise AssertionError("{}: number outside bounds".format(path))


class ContractTests(GraphCase):
    def setUp(self):
        super().setUp()
        self.policy, self.snapshot = load_policy(self.repo)

    def test_real_policy_and_task_validate(self):
        task = validate_task_brief(self.task(tags=["security_privacy"]), self.snapshot.digest, self.policy)
        self.assertEqual(task["mandatory_impact_tags"], ["security_privacy"])

    def test_v2_task_requires_exact_structured_model_sizing(self):
        task = validate_task_brief(self.task_v2(), self.snapshot.digest, self.policy)
        self.assertEqual(
            task["model_sizing"], {"scope_extent": "bounded", "uncertainty": "low"},
        )
        for mutation, code in (
            (lambda value: value.pop("model_sizing"), "MISSING_FIELD"),
            (lambda value: value["model_sizing"].update(extra="no"), "UNKNOWN_FIELD"),
            (lambda value: value["model_sizing"].update(scope_extent="global"), "UNKNOWN_VALUE"),
        ):
            with self.subTest(code=code):
                candidate = self.task_v2()
                mutation(candidate)
                with self.assertRaisesRegex(ContractError, code):
                    validate_task_brief(candidate, self.snapshot.digest, self.policy)

        legacy = self.task()
        legacy["model_sizing"] = {"scope_extent": "bounded", "uncertainty": "low"}
        with self.assertRaisesRegex(ContractError, "UNKNOWN_FIELD"):
            validate_task_brief(legacy, self.snapshot.digest, self.policy)

    def test_published_task_schema_accepts_exact_v1_and_v2_contracts(self):
        schema = json.loads(
            (Path(__file__).parents[1] / "references" / "task-brief.schema.json").read_text(
                encoding="utf-8"
            )
        )
        _validate_json_schema(self.task(), schema, schema)
        _validate_json_schema(self.task_v2(), schema, schema)
        legacy_with_v2_field = self.task()
        legacy_with_v2_field["model_sizing"] = {
            "scope_extent": "bounded", "uncertainty": "low",
        }
        with self.assertRaises(AssertionError):
            _validate_json_schema(legacy_with_v2_field, schema, schema)

    def test_mapper_cannot_downgrade_or_remove_tag(self):
        task = validate_task_brief(self.task(tags=["security_privacy"]), self.snapshot.digest, self.policy)
        with self.assertRaisesRegex(ContractError, "ROUTE_DOWNGRADE"):
            validate_impact_map({"schema_version": 1, "task_id": "TASK-1", "route_label": "fast_path", "impact_tags": ["security_privacy"], "evidence_refs": [], "attempt_id": "attempt", "claim_digest": "a" * 64}, task, self.policy)
        with self.assertRaisesRegex(ContractError, "MANDATORY_TAG_REMOVED"):
            validate_impact_map({"schema_version": 1, "task_id": "TASK-1", "route_label": "full_delivery", "impact_tags": [], "evidence_refs": [], "attempt_id": "attempt", "claim_digest": "a" * 64}, task, self.policy)
        fast_task = validate_task_brief(self.task(route="fast_path"), self.snapshot.digest, self.policy)
        with self.assertRaisesRegex(ContractError, "FAST_PATH_INVARIANT"):
            validate_impact_map({"schema_version": 1, "task_id": "TASK-1", "route_label": "fast_path", "impact_tags": ["security_privacy"], "evidence_refs": [], "attempt_id": "attempt", "claim_digest": "a" * 64}, fast_task, self.policy)

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
        with self.assertRaisesRegex(ContractError, "ENGINE_COMMAND_SET_CHANGED|ENGINE_AUTHORITY_EXCEEDED"):
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
            self.graphctl("record", "branch-result", "--run-id", "RUN-1", "--branch-id", branch["branch_id"], "--attempt-id", branch["attempt_id"], "--claim-token", branch["claim_token"], "--result-manifest", str(oversized), "--op-id", "oversized-1")

    def test_repository_policy_reaches_required_roles_and_checks(self):
        roles = {item["role"] for item in self.policy["node_templates"].values()}
        self.assertTrue({"impact_mapper", "tech_lead", "software_architect", "senior_engineer", "code_reviewer", "test_engineer", "supervisor"}.issubset(roles))
        for node_key in ("design_research_architecture", "design_research_validation"):
            template = self.policy["node_templates"][node_key]
            self.assertEqual(
                (template["role"], template["stages"], template["max_retries"]),
                ("impact_mapper", ["research"], 1),
            )
            self.assertEqual(
                {key: template["output_contract"][key] for key in (
                    "artifact_required", "evidence_required", "decision_forbidden", "findings_forbidden",
                )},
                {"artifact_required": True, "evidence_required": True,
                 "decision_forbidden": True, "findings_forbidden": True},
            )
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

    def test_repository_fixture_matches_published_schema(self):
        schema_path = Path(__file__).parents[1] / "references" / "repository-config.schema.json"
        fixture_path = Path(__file__).parent / "fixtures" / "engineering-graph.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        _validate_json_schema(fixture, schema, schema)

    def test_repository_fixture_rejects_schema_missing_research_flags(self):
        schema_path = Path(__file__).parents[1] / "references" / "repository-config.schema.json"
        fixture_path = Path(__file__).parent / "fixtures" / "engineering-graph.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for field in ("evidence_required", "decision_forbidden", "findings_forbidden"):
            with self.subTest(field=field):
                mutated = copy.deepcopy(schema)
                del mutated["$defs"]["outputContract"]["properties"][field]
                with self.assertRaisesRegex(AssertionError, "unknown"):
                    _validate_json_schema(fixture, mutated, mutated)

    def test_skill_dispatch_requirements_are_semantically_paired(self):
        roots = [
            Path(__file__).parents[1] / "SKILL.md",
            Path(__file__).parents[1] / ".agents" / "skills" / "software-engineering-graph" / "SKILL.md",
        ]
        blocks = []
        for path in roots:
            content = path.read_text(encoding="utf-8")
            start = "<!-- dispatch-transparency:start -->"
            end = "<!-- dispatch-transparency:end -->"
            self.assertEqual(content.count(start), 1, path)
            self.assertEqual(content.count(end), 1, path)
            blocks.append(content.split(start, 1)[1].split(end, 1)[0].strip())
        self.assertEqual(blocks[0], blocks[1])
        required_phrases = (
            "Immediately before every dispatch",
            "concrete agent or task name",
            "exact approved model",
            "exact approved reasoning effort",
            "bounded scope",
            "initial dispatch",
            "fan-out member",
            "retry",
            "replacement",
            "follow-up",
            "same-role continuation",
            "Refuse the dispatch",
            "unavailable, unverifiable, or mismatched",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, blocks[0], phrase)

    def test_policy_missing_research_template_fails_closed(self):
        policy = copy.deepcopy(self.policy)
        del policy["node_templates"]["design_research_validation"]
        (self.repo / ".codex" / "engineering-graph.json").write_text(
            json.dumps(policy), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "ENGINE_TOPOLOGY_CHANGED"):
            load_policy(self.repo)

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
