"""Transition, consolidation, and exhaustive persisted-state validation."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from . import STATE_SCHEMA_VERSION
from .contracts import (
    ContractError, authoritative_task_subset, safe_json_snapshot, validate_impact_map,
    validate_result_manifest, validate_task_brief,
)
from .config import engine_version_compatible
from .evidence import reverify_artifact
from .ids import canonical_bytes, sha256_bytes, stable_id
from .planner import NodeSpec, envelope
from .state import StateError, current_host_identity, repository_identity


TERMINAL = {"succeeded", "failed", "timed_out", "skipped"}
BRANCH_STATES = {"pending", "ready", "running"} | TERMINAL
RUN_STATES = {"initialized", "active", "blocked", "complete", "aborted"}
DESIGN_PRECEDENCE = {"APPROVE": 0, "REVISE": 1, "BLOCK": 2}
DELIVERY_PRECEDENCE = {"accept": 0, "repair": 1, "redesign": 2, "block": 3}
DELIVERY_OUTCOMES = {0: "ACCEPT", 1: "REPAIR", 2: "REDESIGN", 3: "BLOCK"}
JOIN_BINDINGS = {
    "design_inputs": ("dependency", "design"),
    "implementation": ("dependency", "delivery"),
    "design_collection": ("collection", "design"),
    "delivery_collection": ("collection", "delivery"),
    "design_consolidation": ("consolidation", "design"),
    "delivery_consolidation": ("consolidation", "delivery"),
    "closure": ("closure", "closure"),
}


def join_members(connection: sqlite3.Connection, join_id: str) -> List[sqlite3.Row]:
    return connection.execute(
        """SELECT n.*,jm.mandatory AS join_mandatory FROM join_members jm
        JOIN nodes n ON n.branch_id=jm.branch_id WHERE jm.join_id=? ORDER BY n.branch_id""",
        (join_id,),
    ).fetchall()


def canonical_collection_members(
    connection: sqlite3.Connection, members: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    frozen: List[Dict[str, Any]] = []
    for member in members:
        result = json.loads(member["result_json"]) if member["result_json"] else None
        result_ref = None
        result_kind = None
        if member["result_digest"]:
            result_ref = f"ledger:{member['branch_id']}#sha256={member['result_digest']}"
            artifact = connection.execute("SELECT * FROM artifacts WHERE ref=?", (result_ref,)).fetchone()
            if artifact is None or artifact["sha256"] != member["result_digest"]:
                raise StateError("COLLECTION_ARTIFACT_INVALID")
            result_kind = artifact["kind"]
        frozen.append({
            "branch_id": member["branch_id"],
            "mandatory": bool(member["join_mandatory"]),
            "status": member["status"],
            "result_ref": result_ref,
            "result_kind": result_kind,
            "result_digest": member["result_digest"],
            "result": result,
            "failure_code": member["failure_code"],
            "reason_code": member["reason_code"],
        })
    return frozen


def validate_join(connection: sqlite3.Connection, run: Mapping[str, Any], join: Mapping[str, Any]) -> Dict[str, Any]:
    if join["status"] == "sealed":
        return {"join_status": "INVALID_STATE", "groups": {"sealed": [join["join_id"]]}}
    members = join_members(connection, join["join_id"])
    expected = connection.execute("SELECT COUNT(*) FROM join_members WHERE join_id=?", (join["join_id"],)).fetchone()[0]
    if len(members) != expected or not members:
        return {"join_status": "INVALID_STATE", "groups": {"missing": [join["join_id"]]}}
    groups: Dict[str, List[str]] = {}
    for member in members:
        groups.setdefault(member["status"], []).append(member["branch_id"])
        if member["join_mandatory"] and member["status"] == "skipped":
            return {"join_status": "INVALID_STATE", "groups": groups}
    if join["kind"] == "collection":
        result = "READY" if all(member["status"] in TERMINAL for member in members) else "NOT_READY"
        return {"join_status": result, "groups": groups}
    if any(member["status"] in {"pending", "ready", "running"} for member in members):
        return {"join_status": "NOT_READY", "groups": groups}
    retryable = [
        member for member in members
        if member["join_mandatory"] and member["status"] in {"failed", "timed_out"}
        and member["retry_count"] < member["max_retries"]
    ]
    if retryable:
        return {"join_status": "RETRY_REQUIRED", "groups": groups}
    exhausted = [
        member for member in members
        if member["join_mandatory"] and member["status"] in {"failed", "timed_out"}
    ]
    if exhausted:
        return {"join_status": "BLOCKED", "groups": groups}
    return {"join_status": "READY", "groups": groups}


def compute_design_outcome(source_members: Sequence[Mapping[str, Any]]) -> Tuple[str, List[str]]:
    outcome = "APPROVE"
    findings: List[str] = []
    for member in source_members:
        if member["status"] != "succeeded":
            decision = "BLOCK" if member["mandatory"] else "APPROVE"
        else:
            result = json.loads(member["result_json"])
            decision = result.get("decision", "BLOCK" if member["mandatory"] else "APPROVE")
            findings.extend(item["finding_id"] for item in result.get("findings", []))
        if member["mandatory"] and DESIGN_PRECEDENCE.get(decision, 2) > DESIGN_PRECEDENCE[outcome]:
            outcome = decision
    return outcome, sorted(set(findings))


def compute_delivery_outcome(source_members: Sequence[Mapping[str, Any]]) -> Tuple[str, List[str]]:
    precedence = 0
    findings: List[str] = []
    for member in source_members:
        if member["status"] != "succeeded":
            if member["mandatory"]:
                precedence = max(precedence, 3)
            continue
        result = json.loads(member["result_json"])
        if result.get("decision") == "BLOCK":
            precedence = max(precedence, 3)
        if result.get("decision") == "REDESIGN_REQUIRED":
            precedence = max(precedence, 2)
        for finding in result.get("findings", []):
            findings.append(finding["finding_id"])
            if member["mandatory"]:
                precedence = max(precedence, DELIVERY_PRECEDENCE.get(finding["disposition"], 0))
    return DELIVERY_OUTCOMES[precedence], sorted(set(findings))


def _source_finding_dispositions(source_members: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    dispositions: Dict[str, str] = {}
    for member in source_members:
        if member["status"] != "succeeded" or not member["result_json"]:
            continue
        result = json.loads(member["result_json"])
        for finding in result.get("findings", []):
            finding_id = finding["finding_id"]
            disposition = finding["disposition"]
            previous = dispositions.get(finding_id)
            if previous is not None:
                code = "CONFLICTING_FINDING_DISPOSITION" if previous != disposition else "DUPLICATE_FINDING_ID"
                raise ContractError("finding_dispositions", code)
            dispositions[finding_id] = disposition
    return dispositions


def validate_consolidation_manifest(
    manifest: Mapping[str, Any], stage: str, run_id: str, join_id: str, generation: int,
    source_members: Sequence[Mapping[str, Any]],
) -> str:
    expected_kind = stage + "_consolidation"
    if manifest.get("kind") != expected_kind or manifest.get("run_id") != run_id:
        raise ContractError("consolidation", "CONSOLIDATION_ID_MISMATCH")
    if manifest.get("join_id") != join_id or manifest.get("generation") != generation:
        raise ContractError("consolidation", "CONSOLIDATION_ID_MISMATCH")
    expected_sources = sorted(member["branch_id"] for member in source_members)
    if manifest.get("source_branch_ids") != expected_sources:
        raise ContractError("source_branch_ids", "SOURCE_SET_MISMATCH")
    expected_outcome, expected_findings = (
        compute_design_outcome(source_members) if stage == "design" else compute_delivery_outcome(source_members)
    )
    dispositions = manifest.get("finding_dispositions", [])
    actual = {item.get("finding_id"): item.get("disposition") for item in dispositions if isinstance(item, dict)}
    expected = _source_finding_dispositions(source_members)
    if len(actual) != len(dispositions) or actual != expected or sorted(expected) != expected_findings:
        raise ContractError("finding_dispositions", "FINDING_DISPOSITION_MISMATCH")
    if manifest.get("outcome") != expected_outcome:
        raise ContractError("outcome", "OUTCOME_PRECEDENCE_MISMATCH")
    return expected_outcome


def _validate_budget_state(connection: sqlite3.Connection, run: Mapping[str, Any], task: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    expected = {
        "design_revisions": policy["limits"]["design_revisions"],
        "delivery_repairs": policy["limits"]["delivery_repairs"],
        "file_reads": task["inspection_budget"]["file_reads"],
        "discovery_commands": task["inspection_budget"]["discovery_commands"],
    }
    rows = connection.execute("SELECT * FROM budgets WHERE run_id=?", (run["run_id"],)).fetchall()
    if len(rows) != len(expected) or {row["budget_id"] for row in rows} != set(expected):
        raise StateError("BUDGET_STATE_INVALID")
    for row in rows:
        if row["limit_value"] != expected[row["budget_id"]] or not 0 <= row["used"] <= row["limit_value"]:
            raise StateError("BUDGET_STATE_INVALID")
        consumed = connection.execute(
            "SELECT COALESCE(SUM(amount),0) FROM budget_consumptions WHERE run_id=? AND budget_id=?",
            (run["run_id"], row["budget_id"]),
        ).fetchone()[0]
        if row["budget_id"] in {"file_reads", "discovery_commands"} and consumed != row["used"]:
            raise StateError("BUDGET_STATE_INVALID")
        if row["budget_id"] in {"design_revisions", "delivery_repairs"} and consumed > row["used"]:
            raise StateError("BUDGET_STATE_INVALID")
    invalid_consumption = connection.execute(
        """SELECT 1 FROM budget_consumptions bc LEFT JOIN nodes n ON n.branch_id=bc.source_branch_id
        WHERE bc.run_id=? AND (bc.amount<=0 OR n.run_id IS NULL OR n.run_id<>bc.run_id) LIMIT 1""",
        (run["run_id"],),
    ).fetchone()
    if invalid_consumption:
        raise StateError("BUDGET_STATE_INVALID")


def _validate_operation_ledger(connection: sqlite3.Connection, run: Mapping[str, Any]) -> None:
    rows = connection.execute("SELECT * FROM operations WHERE run_id=? ORDER BY resulting_revision", (run["run_id"],)).fetchall()
    revisions = []
    for row in rows:
        if len(row["request_digest"]) != 64:
            raise StateError("OPERATION_LEDGER_INVALID")
        try:
            response = json.loads(row["response_json"])
        except json.JSONDecodeError:
            raise StateError("OPERATION_LEDGER_INVALID")
        if (response.get("state_revision") != row["resulting_revision"] or
                response.get("run_id") != run["run_id"] or response.get("schema_version") != 1 or
                response.get("ok") is not True or not isinstance(response.get("code"), str)):
            raise StateError("OPERATION_LEDGER_INVALID")
        revisions.append(row["resulting_revision"])
    if revisions != list(range(1, run["state_revision"] + 1)):
        raise StateError("OPERATION_LEDGER_INVALID")


def _validate_nodes(connection: sqlite3.Connection, run: Mapping[str, Any], task: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    specialist_by_node = {value["node_key"]: key for key, value in policy["specialists"].items()}
    for node in connection.execute("SELECT * FROM nodes WHERE run_id=?", (run["run_id"],)):
        template = policy["node_templates"].get(node["node_key"])
        if template is None or node["role"] != template["role"] or node["stage"] not in template["stages"] or not node["mandatory"]:
            raise StateError("NODE_BINDING_INVALID")
        spec = NodeSpec(node["node_key"], node["role"], node["stage"], node["generation"], True, node["specialist_tag"])
        expected_branch = stable_id(run["run_id"], run["policy_digest"], "branch", spec.key + "@" + spec.stage, spec.generation, spec.specialist_tag)
        expected_node = stable_id(run["run_id"], run["policy_digest"], "node", spec.key + "@" + spec.stage, spec.generation, spec.specialist_tag)
        if node["branch_id"] != expected_branch or node["node_instance_id"] != expected_node:
            raise StateError("STABLE_ID_INVALID")
        expected_tag = specialist_by_node.get(node["node_key"])
        if node["specialist_tag"] != expected_tag:
            raise StateError("NODE_BINDING_INVALID")
        if node["status"] not in BRANCH_STATES or not 0 <= node["retry_count"] <= node["max_retries"] or node["max_retries"] != template["max_retries"]:
            raise StateError("BRANCH_STATE_INVALID")
        try:
            stored_envelope = json.loads(node["envelope_json"])
        except json.JSONDecodeError:
            raise StateError("ENVELOPE_INVALID")
        expected_envelope = envelope(
            run["run_id"], run["policy_digest"], policy, task, spec, node["status"],
            stored_envelope.get("inputs", []), node["retry_count"],
        )
        immutable_keys = {
            "schema_version", "run_id", "branch_id", "node_instance_id", "node_key", "role",
            "mandatory", "generation", "inputs", "effect_capabilities", "output_contract",
            "stopping_condition", "retry_count", "max_retries",
        }
        if set(stored_envelope) != set(expected_envelope) or any(stored_envelope[key] != expected_envelope[key] for key in immutable_keys):
            raise StateError("ENVELOPE_INVALID")
        if stored_envelope["status"] != node["status"] or stored_envelope["failure_code"] != node["failure_code"]:
            raise StateError("ENVELOPE_STATE_INVALID")
        for input_item in stored_envelope["inputs"]:
            allowed_input_keys = {"kind", "ref", "sha256", "size_bytes", "content"}
            if (set(input_item) - allowed_input_keys or
                    not {"kind", "ref", "sha256", "size_bytes"}.issubset(input_item)):
                raise StateError("INPUT_ARTIFACT_INVALID")
            artifact = connection.execute("SELECT * FROM artifacts WHERE ref=?", (input_item["ref"],)).fetchone()
            if artifact is None or (artifact["kind"], artifact["sha256"], artifact["size_bytes"]) != (input_item["kind"], input_item["sha256"], input_item["size_bytes"]):
                raise StateError("INPUT_ARTIFACT_INVALID")
            if "content" in input_item:
                if artifact["source_type"] != "ledger" or artifact["content_json"] is None:
                    raise StateError("INPUT_ARTIFACT_INVALID")
                try:
                    artifact_content = json.loads(artifact["content_json"])
                except json.JSONDecodeError:
                    raise StateError("INPUT_ARTIFACT_INVALID")
                if input_item["content"] != artifact_content:
                    raise StateError("INPUT_ARTIFACT_INVALID")
        if node["status"] in TERMINAL:
            if not node["result_json"] or not node["result_digest"]:
                raise StateError("TERMINAL_RESULT_MISSING")
            try:
                result = json.loads(node["result_json"])
            except json.JSONDecodeError:
                raise StateError("TERMINAL_RESULT_INVALID")
            if sha256_bytes(canonical_bytes(result)) != node["result_digest"]:
                raise StateError("TERMINAL_RESULT_INVALID")
            ledger_ref = f"ledger:{node['branch_id']}#sha256={node['result_digest']}"
            ledger_artifact = connection.execute(
                "SELECT * FROM artifacts WHERE ref=? AND immutable=1", (ledger_ref,)
            ).fetchone()
            expected_wrapper_kind = {
                "succeeded": "branch_result", "failed": "failure",
                "timed_out": "timeout", "skipped": "skip",
            }[node["status"]]
            if ledger_artifact is None or ledger_artifact["kind"] != expected_wrapper_kind:
                raise StateError("TERMINAL_RESULT_INVALID")
            branch_contract = dict(node)
            branch_contract["run_id"] = run["run_id"]
            branch_contract["output_contract"] = stored_envelope["output_contract"]
            try:
                if node["node_key"] == "impact_mapper" and node["status"] == "succeeded":
                    validate_impact_map(result, task, policy)
                elif node["status"] in {"succeeded", "failed"}:
                    if node["node_key"].startswith("supervisor_"):
                        consolidation_keys = {
                            "schema_version", "kind", "run_id", "join_id", "generation",
                            "source_branch_ids", "finding_dispositions", "outcome",
                        }
                        validate_result_manifest(
                            {key: result[key] for key in consolidation_keys if key in result}, branch_contract
                        )
                    else:
                        validate_result_manifest(result, branch_contract)
                else:
                    if result.get("kind") != node["status"].replace("timed_out", "timeout"):
                        raise ContractError("result", "CONTROL_RESULT_MISMATCH")
            except ContractError:
                raise StateError("TERMINAL_RESULT_INVALID")
            artifact_ref = stored_envelope.get("artifact_ref")
            redesign_without_artifact = (
                node["node_key"] == "senior_engineer"
                and node["status"] == "succeeded"
                and result.get("decision") == "REDESIGN_REQUIRED"
            )
            if redesign_without_artifact:
                if artifact_ref is not None:
                    raise StateError("TERMINAL_RESULT_INVALID")
            else:
                if not isinstance(artifact_ref, dict):
                    raise StateError("TERMINAL_RESULT_INVALID")
                artifact = connection.execute("SELECT * FROM artifacts WHERE ref=?", (artifact_ref.get("ref"),)).fetchone()
                if artifact is None or (artifact["kind"], artifact["sha256"]) != (artifact_ref.get("kind"), artifact_ref.get("sha256")):
                    raise StateError("TERMINAL_RESULT_INVALID")
                if node["status"] == "succeeded" and artifact["kind"] != template["output_contract"]["artifact_kind"]:
                    raise StateError("TERMINAL_RESULT_INVALID")
                if node["status"] != "succeeded" and artifact["kind"] != expected_wrapper_kind:
                    raise StateError("TERMINAL_RESULT_INVALID")


def _expected_join_node_keys(join: Mapping[str, Any], run: Mapping[str, Any], policy: Mapping[str, Any]) -> set:
    key = join["join_key"]
    if key == "design_inputs":
        return {"tech_lead"}
    if key == "implementation":
        return {"senior_engineer"}
    if key == "design_collection":
        return {"architect"} | {
            policy["specialists"][tag]["node_key"] for tag in json.loads(run["selected_tags_json"] or "[]")
            if tag in policy["specialists"]
        }
    if key == "delivery_collection":
        return {"code_reviewer", "test_engineer"} | {
            policy["specialists"][tag]["node_key"] for tag in json.loads(run["selected_tags_json"] or "[]")
            if tag in policy["specialists"]
        }
    if key == "design_consolidation":
        return {"supervisor_design_consolidation"}
    if key == "delivery_consolidation":
        return {"supervisor_delivery_consolidation"}
    if key == "closure":
        return {
            "advisory_reviewer" if run["selected_route"] == "advisory"
            else "supervisor_design_consolidation" if run["selected_route"] == "design_only"
            else "supervisor_delivery_consolidation"
        }
    return set()


def _validate_joins(connection: sqlite3.Connection, run: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    for join in connection.execute("SELECT * FROM joins WHERE run_id=?", (run["run_id"],)):
        binding = JOIN_BINDINGS.get(join["join_key"])
        if binding != (join["kind"], join["stage"]) or join["status"] not in {"open", "sealed"}:
            raise StateError("JOIN_STATE_INVALID")
        expected_id = stable_id(run["run_id"], run["policy_digest"], "join", join["join_key"], join["generation"])
        if join["join_id"] != expected_id:
            raise StateError("STABLE_ID_INVALID")
        members = join_members(connection, join["join_id"])
        if not members or any(not member["join_mandatory"] for member in members):
            raise StateError("JOIN_MEMBERSHIP_INVALID")
        actual_keys = {member["node_key"] for member in members}
        expected_keys = _expected_join_node_keys(join, run, policy)
        senior_redesign_collection = False
        if join["join_key"] == "delivery_collection" and actual_keys == {"senior_engineer"} and len(members) == 1:
            try:
                senior_result = json.loads(members[0]["result_json"] or "{}")
            except json.JSONDecodeError:
                senior_result = {}
            senior_redesign_collection = (
                members[0]["status"] == "succeeded"
                and senior_result.get("decision") == "REDESIGN_REQUIRED"
            )
        if (actual_keys != expected_keys and not senior_redesign_collection) or any(
            member["generation"] != join["generation"] for member in members
        ):
            raise StateError("JOIN_MEMBERSHIP_INVALID")
        if join["status"] == "sealed":
            try:
                frozen = json.loads(join["result_json"])
            except (TypeError, json.JSONDecodeError):
                raise StateError("JOIN_RESULT_INVALID")
            if join["kind"] == "collection":
                expected = canonical_collection_members(connection, members)
                if frozen != expected:
                    raise StateError("COLLECTION_ARTIFACT_INVALID")
                serialized = canonical_bytes({"schema_version": 1, "kind": "collection", "join_id": join["join_id"], "members": expected})
                collection_ref = f"ledger:{join['join_id']}#sha256={sha256_bytes(serialized)}"
                if connection.execute("SELECT 1 FROM artifacts WHERE ref=?", (collection_ref,)).fetchone() is None:
                    raise StateError("COLLECTION_ARTIFACT_INVALID")


def _sealed_consolidation_outcomes(
    connection: sqlite3.Connection, run_id: str, stage: str
) -> List[Tuple[int, str, str]]:
    rows: List[Tuple[int, str, str]] = []
    joins = connection.execute(
        "SELECT * FROM joins WHERE run_id=? AND join_key=? AND status='sealed' ORDER BY generation",
        (run_id, stage + "_consolidation"),
    ).fetchall()
    for join in joins:
        members = join_members(connection, join["join_id"])
        if len(members) != 1 or not members[0]["result_json"]:
            raise StateError("TOPOLOGY_STATE_INVALID")
        result = json.loads(members[0]["result_json"])
        outcome = result.get("outcome")
        allowed = {"APPROVE", "REVISE", "BLOCK"} if stage == "design" else {"ACCEPT", "REPAIR", "REDESIGN", "BLOCK"}
        if outcome not in allowed:
            raise StateError("TOPOLOGY_STATE_INVALID")
        rows.append((join["generation"], outcome, members[0]["branch_id"]))
    return rows


def _validate_route_and_topology(
    connection: sqlite3.Connection,
    run: Mapping[str, Any],
    task: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    nodes = connection.execute(
        "SELECT * FROM nodes WHERE run_id=? ORDER BY branch_id", (run["run_id"],)
    ).fetchall()
    mappers = [node for node in nodes if node["node_key"] == "impact_mapper"]
    if len(mappers) != 1:
        raise StateError("TOPOLOGY_STATE_INVALID")
    mapper = mappers[0]
    if mapper["status"] != "succeeded":
        if run["selected_route"] is not None or run["selected_tags_json"] is not None:
            raise StateError("ROUTE_EVIDENCE_MISMATCH")
        if len(nodes) != 1 or connection.execute(
            "SELECT 1 FROM joins WHERE run_id=? LIMIT 1", (run["run_id"],)
        ).fetchone() is not None:
            raise StateError("TOPOLOGY_STATE_INVALID")
        if run["design_generation"] != 0 or run["implementation_generation"] != 0:
            raise StateError("GENERATION_STATE_INVALID")
        return
    try:
        classification = validate_impact_map(json.loads(mapper["result_json"]), task, policy)
        selected_tags = json.loads(run["selected_tags_json"] or "[]")
    except (ContractError, json.JSONDecodeError):
        raise StateError("ROUTE_EVIDENCE_MISMATCH")
    route = classification["route_label"]
    tags = classification["impact_tags"]
    if run["selected_route"] != route or selected_tags != tags:
        raise StateError("ROUTE_EVIDENCE_MISMATCH")

    design_outcomes = _sealed_consolidation_outcomes(connection, run["run_id"], "design")
    delivery_outcomes = _sealed_consolidation_outcomes(connection, run["run_id"], "delivery")
    fast_redesign = route == "fast_path" and any(outcome == "REDESIGN" for _, outcome, _ in delivery_outcomes)
    allowed_bindings = {("impact_mapper", "bootstrap")}
    if route == "advisory":
        allowed_bindings.add(("advisory_reviewer", "advisory"))
    if route in {"design_only", "full_delivery"} or fast_redesign:
        allowed_bindings.update({
            ("tech_lead", "design"), ("architect", "design"),
            ("supervisor_design_consolidation", "design"),
        })
        allowed_bindings.update(
            (policy["specialists"][tag]["node_key"], "design")
            for tag in tags if tag in policy["specialists"]
        )
    if route in {"fast_path", "full_delivery"}:
        allowed_bindings.update({
            ("senior_engineer", "implementation"), ("code_reviewer", "delivery"),
            ("test_engineer", "delivery"),
            ("supervisor_delivery_consolidation", "delivery"),
        })
        allowed_bindings.update(
            (policy["specialists"][tag]["node_key"], "delivery")
            for tag in tags if tag in policy["specialists"]
        )
    for node in nodes:
        if (node["node_key"], node["stage"]) not in allowed_bindings:
            raise StateError("TOPOLOGY_STATE_INVALID")
        if node["specialist_tag"] is not None and node["specialist_tag"] not in tags:
            raise StateError("TOPOLOGY_STATE_INVALID")

    tech_nodes = [node for node in nodes if node["node_key"] == "tech_lead"]
    senior_nodes = [node for node in nodes if node["node_key"] == "senior_engineer"]
    tech_generations = sorted({node["generation"] for node in tech_nodes})
    senior_generations = sorted({node["generation"] for node in senior_nodes})
    if route in {"design_only", "full_delivery"} and (not tech_generations or tech_generations[0] != 0):
        raise StateError("TOPOLOGY_STATE_INVALID")
    if route == "fast_path" and (not senior_generations or senior_generations[0] != 0):
        raise StateError("TOPOLOGY_STATE_INVALID")
    if route == "full_delivery" and senior_generations and senior_generations[0] != 0:
        raise StateError("TOPOLOGY_STATE_INVALID")
    if route == "fast_path" and tech_generations and tech_generations[0] != 1:
        raise StateError("TOPOLOGY_STATE_INVALID")
    if tech_generations:
        first_design = tech_generations[0]
        if tech_generations != list(range(first_design, tech_generations[-1] + 1)):
            raise StateError("GENERATION_STATE_INVALID")
    if senior_generations and senior_generations != list(range(0, senior_generations[-1] + 1)):
        raise StateError("GENERATION_STATE_INVALID")
    design_generation = tech_generations[-1] if tech_generations else 0
    if run["design_generation"] != design_generation:
        raise StateError("GENERATION_STATE_INVALID")

    reserved_implementation_generations: List[int] = []
    for generation, outcome, consolidation_branch_id in delivery_outcomes:
        if outcome != "REDESIGN":
            continue
        source_prefix = "ledger:" + consolidation_branch_id + "#sha256="
        if any(
            any(item["ref"].startswith(source_prefix) for item in json.loads(node["envelope_json"])["inputs"])
            for node in tech_nodes
        ):
            reserved_implementation_generations.append(generation + 1)
    expected_implementation_generation = max(
        [0] + senior_generations + reserved_implementation_generations
    )
    if run["implementation_generation"] != expected_implementation_generation:
        raise StateError("GENERATION_STATE_INVALID")

    design_generation_set = set(tech_generations)
    implementation_generation_set = set(senior_generations)
    for node in nodes:
        if node["stage"] == "design" and node["generation"] not in design_generation_set:
            raise StateError("GENERATION_STATE_INVALID")
        if node["stage"] == "delivery" and node["generation"] not in implementation_generation_set:
            raise StateError("GENERATION_STATE_INVALID")


def _verify_semantic_state(
    connection: sqlite3.Connection,
    run: Mapping[str, Any],
    repo: Path,
    current_policy_digest: str,
    policy: Mapping[str, Any],
    skill_root: Path,
) -> None:
    if run["state_schema_version"] != STATE_SCHEMA_VERSION:
        raise StateError("UNSUPPORTED_STATE_SCHEMA")
    try:
        compatible_engine = engine_version_compatible(run["engine_version"], policy)
    except ContractError:
        compatible_engine = False
    if not compatible_engine:
        raise StateError("ENGINE_VERSION_INCOMPATIBLE")
    if run["status"] not in RUN_STATES or run["authoritative"] != 1:
        raise StateError("RUN_STATE_INVALID")
    if run["policy_digest"] != current_policy_digest:
        raise StateError("CONFIG_CHANGED")
    if run["host_identity"] != current_host_identity():
        raise StateError("HOST_IDENTITY_MISMATCH")
    device, inode, display = repository_identity(repo)
    if (device, inode, display) != (run["repository_device"], run["repository_inode"], run["repository_path"]):
        raise StateError("REPOSITORY_IDENTITY_MISMATCH")
    task_path = Path(run["task_path"])
    roots = [repo / root for root in policy["artifact_roots"]["repo"]]
    snapshot = safe_json_snapshot(task_path, roots, policy["artifact_kinds"]["task_brief"]["max_bytes"])
    if snapshot.digest != run["task_digest"]:
        raise StateError("INPUT_DIGEST_MISMATCH")
    full_task = validate_task_brief(snapshot.parsed, run["policy_digest"], policy)
    task = json.loads(run["task_json"])
    expected_task = authoritative_task_subset(full_task)
    stored_evidence = task.get("evidence_paths", [])
    if [ref.split("#sha256=", 1)[0] for ref in stored_evidence] != sorted(full_task["evidence_paths"]):
        raise StateError("TASK_METADATA_INVALID")
    expected_task["evidence_paths"] = stored_evidence
    if task != expected_task:
        raise StateError("TASK_METADATA_INVALID")
    _validate_budget_state(connection, run, task, policy)
    _validate_operation_ledger(connection, run)
    _validate_nodes(connection, run, task, policy)
    _validate_joins(connection, run, policy)
    _validate_route_and_topology(connection, run, task, policy)
    try:
        stored_policy = json.loads(run["policy_json"])
    except json.JSONDecodeError:
        raise StateError("POLICY_STATE_INVALID")
    if stored_policy != policy:
        raise StateError("POLICY_STATE_INVALID")
    if (not isinstance(run["local_filesystem"], str) or not run["local_filesystem"]
            or run["design_generation"] < 0 or run["implementation_generation"] < 0):
        raise StateError("RUN_STATE_INVALID")
    if run["selected_route"] is not None:
        selected_tags = json.loads(run["selected_tags_json"] or "[]")
        if run["selected_route"] not in policy["routes"] or selected_tags != sorted(set(selected_tags)) or any(tag not in policy["impact_tags"] for tag in selected_tags):
            raise StateError("RUN_STATE_INVALID")
    for table, id_column, valid_ids, kind in (
        ("acceptance_evidence", "criterion_id", set(task["acceptance_ids"]), "acceptance_evidence"),
        ("check_evidence", "check_id", set(task["required_check_ids"]), "check_evidence"),
    ):
        for row in connection.execute(f"SELECT * FROM {table} WHERE run_id=?", (run["run_id"],)):
            artifact = connection.execute("SELECT * FROM artifacts WHERE ref=?", (row["artifact_ref"],)).fetchone()
            if row[id_column] not in valid_ids or artifact is None or artifact["kind"] != kind or artifact["sha256"] != row["artifact_sha256"]:
                raise StateError("EVIDENCE_STATE_INVALID")
    for row in connection.execute("SELECT * FROM approvals WHERE run_id=?", (run["run_id"],)):
        artifact = connection.execute("SELECT * FROM artifacts WHERE ref=?", (row["scope_ref"],)).fetchone()
        if (row["approval_id"] not in set(task["required_human_decisions"]) or row["decision"] not in {"APPROVE", "REJECT"}
                or artifact is None or artifact["kind"] != "acceptance_evidence" or artifact["sha256"] != row["artifact_sha256"]):
            raise StateError("APPROVAL_STATE_INVALID")
    artifacts = connection.execute("SELECT * FROM artifacts WHERE run_id=?", (run["run_id"],)).fetchall()
    if not artifacts or connection.execute("SELECT 1 FROM artifacts WHERE ref=?", (run["task_ref"],)).fetchone() is None:
        raise StateError("ARTIFACT_REGISTRY_INVALID")
    for artifact in artifacts:
        reverify_artifact(connection, artifact, repo, skill_root, policy)


def verify_semantic_state(
    connection: sqlite3.Connection,
    run: Mapping[str, Any],
    repo: Path,
    current_policy_digest: str,
    policy: Mapping[str, Any],
    skill_root: Path,
) -> None:
    try:
        _verify_semantic_state(connection, run, repo, current_policy_digest, policy, skill_root)
    except sqlite3.DatabaseError:
        raise StateError("DATABASE_STATE_INVALID")


def verify_resume(
    connection: sqlite3.Connection,
    run: Mapping[str, Any],
    repo: Path,
    current_policy_digest: str,
    policy: Mapping[str, Any],
    skill_root: Path,
) -> None:
    verify_semantic_state(connection, run, repo, current_policy_digest, policy, skill_root)
