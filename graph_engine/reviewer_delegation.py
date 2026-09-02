"""Bounded reviewer delegation contracts and deterministic consolidation."""

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .contracts import (
    FINDING_ID, ContractError, bounded_string, digest, opaque, require_keys, validate_ref,
)
from .ids import canonical_bytes, sha256_bytes


ENGINE_REVIEW_DELEGATION_LIMITS = {
    "max_depth": 1,
    "max_children_per_request": 3,
    "max_children_per_run": 6,
    "max_request_rounds": 2,
    "max_weighted_dispatch_cost": 15,
}
DEFAULT_REVIEW_DELEGATION_LIMITS = {
    **ENGINE_REVIEW_DELEGATION_LIMITS,
    "max_request_rounds": 1,
}
SUPPORTED_DISPATCH_WEIGHTS = {
    ("gpt-5.6-luna", "max"): 3,
    ("gpt-5.6-sol", "high"): 3,
    ("gpt-5.6-sol", "xhigh"): 4,
    ("gpt-5.6-sol", "max"): 5,
}
ELIGIBLE_ROLES = {"code_reviewer", "security_reviewer"}
READ_ONLY_EFFECTS = {"filesystem_read", "external_read"}
LOCATION_SLASHES = re.compile(r"/+" )


def _positive_limit(value: Any, name: str, ceiling: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ceiling:
        raise ContractError(name, "LIMIT_MAY_NOT_INCREASE")
    return value


def _limits(value: Any, field: str) -> Dict[str, int]:
    if not isinstance(value, dict):
        raise ContractError(field, "INVALID_OBJECT")
    keys = set(ENGINE_REVIEW_DELEGATION_LIMITS)
    require_keys(value, keys, keys, field)
    return {
        key: _positive_limit(value[key], field + "." + key, ceiling)
        for key, ceiling in ENGINE_REVIEW_DELEGATION_LIMITS.items()
    }


def _unique_ids(value: Any, field: str) -> List[str]:
    if not isinstance(value, list):
        raise ContractError(field, "INVALID_LIST")
    result = [opaque(item, field) for item in value]
    if len(result) != len(set(result)):
        raise ContractError(field, "DUPLICATE_VALUE")
    return sorted(result)


def validate_policy_config(value: Any) -> Optional[Dict[str, Any]]:
    """Validate an optional repository ceiling. Absence keeps delegation disabled."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ContractError("reviewer_delegation", "INVALID_OBJECT")
    required = {"limits", "assignments"}
    require_keys(value, required, required, "reviewer_delegation")
    limits = _limits(value["limits"], "reviewer_delegation.limits")
    if not isinstance(value["assignments"], list):
        raise ContractError("reviewer_delegation.assignments", "INVALID_LIST")
    assignments: List[Dict[str, Any]] = []
    seen = set()
    keys = {
        "assignment_id", "role", "model", "reasoning_effort", "review_lens",
        "prompt_template", "allowed_reason_codes", "allowed_evidence_kinds",
        "scope_refs", "max_instances", "dispatch_weight",
    }
    for index, item in enumerate(value["assignments"]):
        field = "reviewer_delegation.assignments[{}]".format(index)
        if not isinstance(item, dict):
            raise ContractError(field, "INVALID_OBJECT")
        require_keys(item, keys, keys, field)
        assignment_id = opaque(item["assignment_id"], field + ".assignment_id")
        if assignment_id in seen:
            raise ContractError(field, "DUPLICATE_VALUE")
        seen.add(assignment_id)
        role = opaque(item["role"], field + ".role")
        if role not in ELIGIBLE_ROLES:
            raise ContractError(field + ".role", "DELEGATION_ROLE_FORBIDDEN")
        model = bounded_string(item["model"], field + ".model", 128)
        effort = bounded_string(item["reasoning_effort"], field + ".reasoning_effort", 32)
        expected_weight = SUPPORTED_DISPATCH_WEIGHTS.get((model, effort))
        if expected_weight is None or (model == "gpt-5.6-luna" and effort != "max"):
            raise ContractError(field + ".model", "DELEGATION_ASSIGNMENT_UNSUPPORTED")
        weight = item["dispatch_weight"]
        if isinstance(weight, bool) or not isinstance(weight, int) or weight != expected_weight:
            raise ContractError(field + ".dispatch_weight", "DELEGATION_WEIGHT_INVALID")
        max_instances = item["max_instances"]
        if isinstance(max_instances, bool) or not isinstance(max_instances, int) or not 1 <= max_instances <= 3:
            raise ContractError(field + ".max_instances", "LIMIT_MAY_NOT_INCREASE")
        scope_refs = [validate_ref(ref, field + ".scope_refs") for ref in item["scope_refs"]]
        if len(scope_refs) != len(set(scope_refs)):
            raise ContractError(field + ".scope_refs", "DUPLICATE_VALUE")
        assignments.append({
            "assignment_id": assignment_id,
            "role": role,
            "model": model,
            "reasoning_effort": effort,
            "review_lens": bounded_string(item["review_lens"], field + ".review_lens", 1024),
            "prompt_template": bounded_string(item["prompt_template"], field + ".prompt_template", 4096),
            "allowed_reason_codes": _unique_ids(item["allowed_reason_codes"], field + ".allowed_reason_codes"),
            "allowed_evidence_kinds": _unique_ids(item["allowed_evidence_kinds"], field + ".allowed_evidence_kinds"),
            "scope_refs": sorted(scope_refs),
            "max_instances": max_instances,
            "dispatch_weight": weight,
        })
    return {"limits": limits, "assignments": sorted(assignments, key=lambda item: item["assignment_id"])}


def validate_task_config(
    value: Any, policy_config: Optional[Mapping[str, Any]], acceptance_ids: Sequence[str],
) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if policy_config is None:
        raise ContractError("reviewer_delegation", "DELEGATION_DISABLED")
    if not isinstance(value, dict):
        raise ContractError("reviewer_delegation", "INVALID_OBJECT")
    required = {"limits", "assignments"}
    require_keys(value, required, required, "reviewer_delegation")
    task_limits = _limits(value["limits"], "reviewer_delegation.limits")
    limits = {
        key: min(task_limits[key], policy_config["limits"][key], ENGINE_REVIEW_DELEGATION_LIMITS[key])
        for key in ENGINE_REVIEW_DELEGATION_LIMITS
    }
    policy_by_id = {item["assignment_id"]: item for item in policy_config["assignments"]}
    if not isinstance(value["assignments"], list):
        raise ContractError("reviewer_delegation.assignments", "INVALID_LIST")
    assignments: List[Dict[str, Any]] = []
    seen = set()
    keys = {
        "assignment_id", "allowed_reason_codes", "allowed_acceptance_ids",
        "allowed_evidence_kinds", "scope_refs", "max_instances",
    }
    for index, item in enumerate(value["assignments"]):
        field = "reviewer_delegation.assignments[{}]".format(index)
        if not isinstance(item, dict):
            raise ContractError(field, "INVALID_OBJECT")
        require_keys(item, keys, keys, field)
        assignment_id = opaque(item["assignment_id"], field + ".assignment_id")
        if assignment_id in seen:
            raise ContractError(field, "DUPLICATE_VALUE")
        seen.add(assignment_id)
        policy_assignment = policy_by_id.get(assignment_id)
        if policy_assignment is None:
            raise ContractError(field + ".assignment_id", "DELEGATION_ASSIGNMENT_UNDECLARED")
        reasons = _unique_ids(item["allowed_reason_codes"], field + ".allowed_reason_codes")
        if not set(reasons).issubset(policy_assignment["allowed_reason_codes"]):
            raise ContractError(field + ".allowed_reason_codes", "DELEGATION_REASON_FORBIDDEN")
        accepted = _unique_ids(item["allowed_acceptance_ids"], field + ".allowed_acceptance_ids")
        if not set(accepted).issubset(acceptance_ids):
            raise ContractError(field + ".allowed_acceptance_ids", "DELEGATION_ACCEPTANCE_FORBIDDEN")
        evidence_kinds = _unique_ids(item["allowed_evidence_kinds"], field + ".allowed_evidence_kinds")
        if not set(evidence_kinds).issubset(policy_assignment["allowed_evidence_kinds"]):
            raise ContractError(field + ".allowed_evidence_kinds", "DELEGATION_EVIDENCE_FORBIDDEN")
        scope_refs = [validate_ref(ref, field + ".scope_refs") for ref in item["scope_refs"]]
        if not set(scope_refs).issubset(policy_assignment["scope_refs"]):
            raise ContractError(field + ".scope_refs", "DELEGATION_SCOPE_FORBIDDEN")
        max_instances = item["max_instances"]
        if (isinstance(max_instances, bool) or not isinstance(max_instances, int)
                or not 1 <= max_instances <= policy_assignment["max_instances"]):
            raise ContractError(field + ".max_instances", "LIMIT_MAY_NOT_INCREASE")
        assignments.append({
            **policy_assignment,
            "allowed_reason_codes": reasons,
            "allowed_acceptance_ids": accepted,
            "allowed_evidence_kinds": evidence_kinds,
            "scope_refs": sorted(scope_refs),
            "max_instances": max_instances,
            "effect_capabilities": [],
        })
    return {"limits": limits, "assignments": sorted(assignments, key=lambda item: item["assignment_id"])}


def plan_fragment(config: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if config is None:
        return []
    return [dict(item) for item in config["assignments"]]


def _ref_within_scope(reference: str, scope_refs: Sequence[str]) -> bool:
    ref_path = reference.partition("#sha256=")[0].replace("\\", "/").rstrip("/").casefold()
    return any(
        ref_path == scope.replace("\\", "/").rstrip("/").casefold()
        or ref_path.startswith(scope.replace("\\", "/").rstrip("/").casefold() + "/")
        for scope in scope_refs
    )


def request_slot_id(
    run_id: str, policy_digest: str, plan_digest: str, parent_branch_id: str,
    parent_attempt_id: str, parent_claim_digest: str, generation: int, round_number: int,
) -> str:
    identity = [
        6, run_id, policy_digest, plan_digest, parent_branch_id, parent_attempt_id,
        parent_claim_digest, generation, round_number,
    ]
    return "g2-" + sha256_bytes(canonical_bytes(identity))[:24]


def delegated_identity(slot_id: str, assignment_id: str, ordinal: int, entity: str) -> str:
    return "g2-" + sha256_bytes(canonical_bytes([6, entity, slot_id, assignment_id, ordinal]))[:24]


def validate_preliminary(
    value: Any, run_id: str, branch_id: str, attempt_id: str, generation: int,
    approved_evidence: Optional[Sequence[Mapping[str, Any]]] = None, *, resolved: bool = False,
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("review_preliminary", "INVALID_OBJECT")
    required = {
        "schema_version", "kind", "run_id", "parent_branch_id", "parent_attempt_id",
        "generation", "findings", "evidence",
    }
    require_keys(value, required, required, "review_preliminary")
    if (value["schema_version"] != 1 or value["kind"] != "review_preliminary"
            or value["run_id"] != run_id or value["parent_branch_id"] != branch_id
            or value["parent_attempt_id"] != attempt_id or value["generation"] != generation):
        raise ContractError("review_preliminary", "PRELIMINARY_FENCE_MISMATCH")
    registry: Dict[Tuple[str, str], List[str]] = {}
    if approved_evidence is not None:
        for item in approved_evidence:
            if isinstance(item, Mapping) and str(item.get("ref", "")).startswith(("repo:", "profile:")):
                registry.setdefault((item["kind"], item["sha256"]), []).append(item["ref"])
    evidence: List[Dict[str, str]] = []
    evidence_ids = set()
    for index, item in enumerate(value["evidence"]):
        field = "review_preliminary.evidence[{}]".format(index)
        if not isinstance(item, dict):
            raise ContractError(field, "INVALID_OBJECT")
        keys = {"evidence_id", "kind", "sha256"} | ({"ref"} if resolved else set())
        require_keys(item, keys, keys, field)
        evidence_id = opaque(item["evidence_id"], field + ".evidence_id")
        if evidence_id in evidence_ids:
            raise ContractError(field, "DUPLICATE_VALUE")
        evidence_ids.add(evidence_id)
        kind = opaque(item["kind"], field + ".kind")
        sha256 = digest(item["sha256"], field + ".sha256")
        matches = registry.get((kind, sha256), [])
        if len(matches) != 1:
            raise ContractError(field, "DELEGATION_EVIDENCE_UNAPPROVED")
        resolved_ref = validate_ref(item["ref"], field + ".ref", content_required=True) if resolved else matches[0]
        if resolved_ref != matches[0]:
            raise ContractError(field, "DELEGATION_EVIDENCE_UNAPPROVED")
        normalized = {
            "evidence_id": evidence_id,
            "kind": kind, "ref": resolved_ref, "sha256": sha256,
        }
        evidence.append(normalized)
    findings = validate_findings(value["findings"], evidence_ids, "review_preliminary.findings")
    return {**value, "evidence": sorted(evidence, key=lambda item: item["evidence_id"]), "findings": findings}


def validate_fanout_request(
    value: Any, run_id: str, parent_branch_id: str, parent_attempt_id: str,
    round_number: int, plan_assignments: Sequence[Mapping[str, Any]],
    preliminary: Mapping[str, Any], limits: Mapping[str, int], depth: int = 0,
) -> Dict[str, Any]:
    if depth >= limits["max_depth"]:
        raise ContractError("review_fanout_request", "DELEGATION_DEPTH_EXCEEDED")
    if not isinstance(value, dict):
        raise ContractError("review_fanout_request", "INVALID_OBJECT")
    required = {
        "schema_version", "kind", "run_id", "parent_branch_id", "parent_attempt_id",
        "round", "members",
    }
    require_keys(value, required, required, "review_fanout_request")
    if (value["schema_version"] != 1 or value["kind"] != "review_fanout_request"
            or value["run_id"] != run_id or value["parent_branch_id"] != parent_branch_id
            or value["parent_attempt_id"] != parent_attempt_id or value["round"] != round_number):
        raise ContractError("review_fanout_request", "REQUEST_FENCE_MISMATCH")
    members = value["members"]
    if (not isinstance(members, list) or not members
            or len(members) > limits["max_children_per_request"]):
        raise ContractError("review_fanout_request.members", "DELEGATION_REQUEST_LIMIT")
    assignment_by_id = {item["assignment_id"]: item for item in plan_assignments}
    preliminary_evidence = {item["evidence_id"]: item for item in preliminary["evidence"]}
    normalized: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    member_keys = set()
    keys = {"assignment_id", "ordinal", "reason_code", "acceptance_ids", "evidence_ids"}
    for index, member in enumerate(members):
        field = "review_fanout_request.members[{}]".format(index)
        if not isinstance(member, dict):
            raise ContractError(field, "INVALID_OBJECT")
        require_keys(member, keys, keys, field)
        assignment_id = opaque(member["assignment_id"], field + ".assignment_id")
        assignment = assignment_by_id.get(assignment_id)
        if assignment is None:
            raise ContractError(field + ".assignment_id", "DELEGATION_ASSIGNMENT_UNDECLARED")
        ordinal = member["ordinal"]
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            raise ContractError(field + ".ordinal", "INVALID_ORDINAL")
        member_key = (assignment_id, ordinal)
        if member_key in member_keys:
            raise ContractError(field, "DUPLICATE_VALUE")
        member_keys.add(member_key)
        counts[assignment_id] = counts.get(assignment_id, 0) + 1
        if counts[assignment_id] > assignment["max_instances"]:
            raise ContractError(field, "DELEGATION_INSTANCE_LIMIT")
        reason = opaque(member["reason_code"], field + ".reason_code")
        if reason not in assignment["allowed_reason_codes"]:
            raise ContractError(field + ".reason_code", "DELEGATION_REASON_FORBIDDEN")
        acceptance_ids = _unique_ids(member["acceptance_ids"], field + ".acceptance_ids")
        if not acceptance_ids or not set(acceptance_ids).issubset(assignment["allowed_acceptance_ids"]):
            raise ContractError(field + ".acceptance_ids", "DELEGATION_ACCEPTANCE_FORBIDDEN")
        evidence_ids = _unique_ids(member["evidence_ids"], field + ".evidence_ids")
        if not evidence_ids or not set(evidence_ids).issubset(preliminary_evidence):
            raise ContractError(field + ".evidence_ids", "DELEGATION_EVIDENCE_FORBIDDEN")
        if any(preliminary_evidence[item]["kind"] not in assignment["allowed_evidence_kinds"] for item in evidence_ids):
            raise ContractError(field + ".evidence_ids", "DELEGATION_EVIDENCE_FORBIDDEN")
        if any(not _ref_within_scope(preliminary_evidence[item]["ref"], assignment["scope_refs"])
               for item in evidence_ids):
            raise ContractError(field + ".evidence_ids", "DELEGATION_SCOPE_FORBIDDEN")
        normalized.append({
            "assignment_id": assignment_id, "ordinal": ordinal, "reason_code": reason,
            "acceptance_ids": acceptance_ids, "evidence_ids": evidence_ids,
        })
    if normalized != sorted(normalized, key=lambda item: (item["assignment_id"], item["ordinal"])):
        raise ContractError("review_fanout_request.members", "NON_CANONICAL_ORDER")
    return {**value, "members": normalized}


def normalize_location(value: Any) -> str:
    location = bounded_string(value, "finding.location", 1024).replace("\\", "/").strip()
    location = LOCATION_SLASHES.sub("/", location).removeprefix("./").rstrip("/")
    if not location or location.startswith("/") or ".." in location.split("/"):
        raise ContractError("finding.location", "INVALID_LOCATION")
    return location.casefold()


def location_within_scope(location: str, scope_refs: Sequence[str]) -> bool:
    normalized = normalize_location(location)
    for reference in scope_refs:
        if not reference.startswith("repo:"):
            continue
        path = reference[5:].partition("#sha256=")[0].replace("\\", "/").strip("/").casefold()
        if normalized == path or normalized.startswith(path + "/"):
            return True
    return False


def validate_findings(
    value: Any, evidence_ids: Sequence[str], field: str = "findings",
    *, acceptance_ids: Optional[Sequence[str]] = None,
    scope_refs: Optional[Sequence[str]] = None, exact_evidence: bool = False,
) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError(field, "INVALID_LIST")
    allowed_evidence = set(evidence_ids)
    findings: List[Dict[str, Any]] = []
    seen_finding_ids = set()
    keys = {
        "finding_id", "acceptance_id", "location", "defect_id", "summary",
        "fix_variant", "evidence_ids",
    }
    for index, item in enumerate(value):
        item_field = "{}[{}]".format(field, index)
        if not isinstance(item, dict):
            raise ContractError(item_field, "INVALID_OBJECT")
        require_keys(item, keys, keys, item_field)
        evidence = _unique_ids(item["evidence_ids"], item_field + ".evidence_ids")
        if (exact_evidence and set(evidence) != allowed_evidence) or (
            not exact_evidence and not set(evidence).issubset(allowed_evidence)
        ):
            raise ContractError(item_field + ".evidence_ids", "FINDING_EVIDENCE_MISSING")
        finding_id = item["finding_id"]
        if not isinstance(finding_id, str) or not FINDING_ID.fullmatch(finding_id):
            raise ContractError(item_field + ".finding_id", "INVALID_ID")
        if finding_id in seen_finding_ids:
            raise ContractError(item_field + ".finding_id", "DUPLICATE_ID")
        seen_finding_ids.add(finding_id)
        acceptance_id = opaque(item["acceptance_id"], item_field + ".acceptance_id")
        if acceptance_ids is not None and acceptance_id not in set(acceptance_ids):
            raise ContractError(item_field + ".acceptance_id", "DELEGATION_ACCEPTANCE_FORBIDDEN")
        location = normalize_location(item["location"])
        if scope_refs is not None and not location_within_scope(location, scope_refs):
            raise ContractError(item_field + ".location", "DELEGATION_SCOPE_FORBIDDEN")
        findings.append({
            "finding_id": finding_id,
            "acceptance_id": acceptance_id,
            "location": location,
            "defect_id": opaque(item["defect_id"], item_field + ".defect_id"),
            "summary": bounded_string(item["summary"], item_field + ".summary", 4096),
            "fix_variant": bounded_string(item["fix_variant"], item_field + ".fix_variant", 4096).strip(),
            "evidence_ids": evidence,
        })
    return findings


def consolidate_findings(sources: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Group exact issues while preserving every source and incompatible fix variant."""
    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for source in sorted(sources, key=lambda item: item["branch_id"]):
        provenance = {
            key: source[key]
            for key in ("branch_id", "role", "model", "assignment_id", "ordinal", "review_lens")
        }
        if "request_slot_id" in source:
            provenance["request_slot_id"] = source["request_slot_id"]
        for finding in source.get("findings", []):
            key = (finding["acceptance_id"], normalize_location(finding["location"]), finding["defect_id"])
            group = groups.setdefault(key, {
                "issue_key": ":".join(key),
                "acceptance_id": key[0], "location": key[1], "defect_id": key[2],
                "canonical_branch_id": source["branch_id"], "provenance": [], "fix_variants": [],
            })
            group["canonical_branch_id"] = min(group["canonical_branch_id"], source["branch_id"])
            group["provenance"].append({**provenance, "finding_id": finding["finding_id"]})
            normalized_fix = " ".join(finding["fix_variant"].casefold().split())
            variant = next((item for item in group["fix_variants"] if item["normalized"] == normalized_fix), None)
            if variant is None:
                variant = {"normalized": normalized_fix, "text": finding["fix_variant"], "sources": []}
                group["fix_variants"].append(variant)
            variant["sources"].append({**provenance, "finding_id": finding["finding_id"]})
    result = []
    for key in sorted(groups):
        group = groups[key]
        group["provenance"] = sorted(group["provenance"], key=lambda item: (item["branch_id"], item["finding_id"]))
        group["fix_variants"] = sorted(group["fix_variants"], key=lambda item: item["normalized"])
        for variant in group["fix_variants"]:
            variant["sources"] = sorted(variant["sources"], key=lambda item: (item["branch_id"], item["finding_id"]))
        group["conflict"] = len(group["fix_variants"]) > 1
        result.append(group)
    return result


def freeze_terminal_member(
    member: Mapping[str, Any], envelope: Mapping[str, Any], result: Mapping[str, Any],
    result_artifact: Mapping[str, Any], attempts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Freeze the complete typed terminal record without summarizing control outcomes."""
    findings = list(result.get("findings", [])) if member["status"] == "succeeded" else []
    return {
        "branch_id": member["branch_id"], "assignment_id": member["assignment_id"],
        "ordinal": member["ordinal"], "role": member["role"], "status": member["status"],
        "findings": findings,
        "terminal": {
            "result": dict(result),
            "result_artifact": dict(result_artifact),
            "artifact_ref": envelope.get("artifact_ref"),
            "evidence": list(envelope.get("evidence", [])),
            "decision": envelope.get("decision"),
            "reason_code": member["reason_code"],
            "failure_code": member["failure_code"],
            "result_digest": member["result_digest"],
            "retry_count": member["retry_count"], "max_retries": member["max_retries"],
            "started_at": member["started_at"], "finished_at": member["finished_at"],
            "attempts": [dict(item) for item in attempts],
        },
    }
