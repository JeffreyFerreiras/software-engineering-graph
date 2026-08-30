"""Scope sizing and immutable model/effort assignments for graph runs."""

from typing import Any, Dict, Mapping, Optional, Tuple

from .ids import canonical_bytes, sha256_bytes


TSHIRT_SIZES = ("small", "medium", "large")

# These are the model choices exposed by the approved role profiles. A run may
# select a size-specific assignment, but it may not invent a model or effort.
SIZE_ASSIGNMENTS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "small": {
        "impact_mapper": ("gpt-5.6-luna", "low"),
        "advisory_reviewer": ("gpt-5.6-luna", "low"),
        "tech_lead": ("gpt-5.6-luna", "medium"),
        "architect": ("gpt-5.6-luna", "high"),
        "senior_engineer": ("gpt-5.6-luna", "medium"),
        "code_reviewer": ("gpt-5.6-luna", "high"),
        "test_engineer": ("gpt-5.6-luna", "high"),
        "audio_realtime_specialist": ("gpt-5.6-luna", "high"),
        "ios_platform_specialist": ("gpt-5.6-luna", "high"),
        "release_operations_reviewer": ("gpt-5.6-sol", "high"),
        "security_reviewer": ("gpt-5.6-sol", "high"),
        "supervisor": ("primary-thread", "inherited"),
    },
    "medium": {
        "impact_mapper": ("gpt-5.6-luna", "medium"),
        "advisory_reviewer": ("gpt-5.6-sol", "xhigh"),
        "tech_lead": ("gpt-5.6-sol", "high"),
        "architect": ("gpt-5.6-sol", "xhigh"),
        "senior_engineer": ("gpt-5.6-sol", "high"),
        "code_reviewer": ("gpt-5.6-sol", "xhigh"),
        "test_engineer": ("gpt-5.6-luna", "max"),
        "audio_realtime_specialist": ("gpt-5.6-sol", "high"),
        "ios_platform_specialist": ("gpt-5.6-sol", "high"),
        "release_operations_reviewer": ("gpt-5.6-sol", "high"),
        "security_reviewer": ("gpt-5.6-sol", "high"),
        "supervisor": ("primary-thread", "inherited"),
    },
    "large": {
        "impact_mapper": ("gpt-5.6-sol", "high"),
        "advisory_reviewer": ("gpt-5.6-sol", "xhigh"),
        "tech_lead": ("gpt-5.6-sol", "xhigh"),
        "architect": ("gpt-5.6-sol", "max"),
        "senior_engineer": ("gpt-5.6-sol", "xhigh"),
        "code_reviewer": ("gpt-5.6-sol", "max"),
        "test_engineer": ("gpt-5.6-sol", "xhigh"),
        "audio_realtime_specialist": ("gpt-5.6-sol", "xhigh"),
        "ios_platform_specialist": ("gpt-5.6-sol", "xhigh"),
        "release_operations_reviewer": ("gpt-5.6-sol", "xhigh"),
        "security_reviewer": ("gpt-5.6-sol", "xhigh"),
        "supervisor": ("primary-thread", "inherited"),
    },
}

NODE_ROLES = {
    "impact_mapper": "impact_mapper",
    "advisory_reviewer": "code_reviewer",
    "tech_lead": "tech_lead",
    "architect": "software_architect",
    "senior_engineer": "senior_engineer",
    "code_reviewer": "code_reviewer",
    "test_engineer": "test_engineer",
    "audio_realtime_specialist": "audio_realtime_specialist",
    "ios_platform_specialist": "ios_platform_specialist",
    "release_operations_reviewer": "release_operations_reviewer",
    "security_reviewer": "security_reviewer",
    "supervisor_design_consolidation": "supervisor",
    "supervisor_delivery_consolidation": "supervisor",
}

DISPATCH_WHEN = {
    "impact_mapper": "always, before route selection",
    "advisory_reviewer": "advisory route",
    "tech_lead": "design_only or full_delivery route",
    "architect": "design_only or full_delivery route",
    "senior_engineer": "fast_path or full_delivery route",
    "code_reviewer": "fast_path or full_delivery route",
    "test_engineer": "fast_path or full_delivery route",
    "audio_realtime_specialist": "matching impact tag at design or delivery",
    "ios_platform_specialist": "matching impact tag at design or delivery",
    "release_operations_reviewer": "matching impact tag at design or delivery",
    "security_reviewer": "matching impact tag at design or delivery",
    "supervisor_design_consolidation": "design consolidation",
    "supervisor_delivery_consolidation": "delivery consolidation",
}


def recommend_size(task: Mapping[str, Any]) -> Tuple[str, str]:
    if task["risk_level"] == "critical" or task["minimum_route"] == "full_delivery":
        return "large", "critical risk or full-delivery route floor"
    if task["risk_level"] == "high" or task["mandatory_impact_tags"] or task["minimum_route"] in {"design_only", "fast_path"}:
        return "medium", "elevated risk, impact tags, or a delivery/design route"
    return "small", "low-risk advisory work with no mandatory impact tags"


def build_execution_plan(
    run_id: str, task: Mapping[str, Any], requested_size: Optional[str] = None,
) -> Dict[str, Any]:
    recommended, recommendation_reason = recommend_size(task)
    size = requested_size or recommended
    if size not in TSHIRT_SIZES:
        raise ValueError("invalid execution size")
    assignments = []
    for node_key in sorted(NODE_ROLES):
        role = NODE_ROLES[node_key]
        model, effort = SIZE_ASSIGNMENTS[size][role if role in SIZE_ASSIGNMENTS[size] else node_key]
        assignments.append({
            "node_key": node_key,
            "role": role,
            "model": model,
            "reasoning_effort": effort,
            "dispatch_when": DISPATCH_WHEN[node_key],
        })
    plan = {
        "schema_version": 1,
        "run_id": run_id,
        "task_id": task["task_id"],
        "size": size,
        "size_source": "supervisor_override" if requested_size else "supervisor_recommendation",
        "size_recommendation": recommended,
        "size_recommendation_reason": recommendation_reason,
        "minimum_route": task["minimum_route"],
        "mandatory_impact_tags": list(task["mandatory_impact_tags"]),
        "assignments": assignments,
        "approval_id": "execution_plan",
        "approval_required": True,
    }
    plan["plan_digest"] = sha256_bytes(canonical_bytes(plan))
    return plan


def assignment_for(plan: Mapping[str, Any], node_key: str) -> Mapping[str, str]:
    for assignment in plan["assignments"]:
        if assignment["node_key"] == node_key:
            return assignment
    raise ValueError("missing execution assignment")


def plan_approval_digest(
    run_id: str, plan_digest: str, decision: str, authority_ref: str,
    actor: str, host_identity: str, approved_at: str,
) -> str:
    return sha256_bytes(canonical_bytes({
        "run_id": run_id,
        "approval_id": "execution_plan",
        "plan_digest": plan_digest,
        "decision": decision,
        "authority_ref": authority_ref,
        "actor": actor,
        "host_identity": host_identity,
        "approved_at": approved_at,
    }))
