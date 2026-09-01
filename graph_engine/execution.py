"""Scope sizing and immutable model/effort assignments for graph runs."""

from typing import Any, Dict, Mapping, Optional, Tuple

from .ids import canonical_bytes, sha256_bytes


TSHIRT_SIZES = ("small", "medium", "large")

# These are the model choices exposed by the approved role profiles. A run may
# select a size-specific assignment, but it may not invent a model or effort.
SIZE_ASSIGNMENTS: Dict[str, Dict[str, Tuple[str, str]]] = {
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

NODE_ROLES = {
    "impact_mapper": "impact_mapper",
    "design_research_architecture": "impact_mapper",
    "design_research_validation": "impact_mapper",
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
    "design_research_architecture": "design route, before each Tech Lead generation",
    "design_research_validation": "design route, before each Tech Lead generation",
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


def validate_model_assignment(node_key: str, model: str, reasoning_effort: str) -> None:
    """Fail closed on the graph's model and reasoning-effort invariants."""
    if model not in {"gpt-5.6-luna", "gpt-5.6-sol", "primary-thread"}:
        raise ValueError("MODEL_ASSIGNMENT_INVALID")
    if model == "primary-thread" and reasoning_effort != "inherited":
        raise ValueError("SUPERVISOR_EFFORT_INVALID")
    if model == "gpt-5.6-luna" and reasoning_effort != "max":
        raise ValueError("LUNA_REASONING_EFFORT_REQUIRED")
    if node_key in {"tech_lead", "architect"} and model != "gpt-5.6-sol":
        raise ValueError("DESIGN_MODEL_REQUIRED")
    if NODE_ROLES.get(node_key) == "impact_mapper" and model != "gpt-5.6-luna":
        raise ValueError("IMPACT_MAPPER_ASSIGNMENT_REQUIRED")


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
        assignment_key = node_key if node_key in SIZE_ASSIGNMENTS[size] else role
        model, effort = SIZE_ASSIGNMENTS[size][assignment_key]
        validate_model_assignment(node_key, model, effort)
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
            validate_model_assignment(
                node_key, assignment["model"], assignment["reasoning_effort"]
            )
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
