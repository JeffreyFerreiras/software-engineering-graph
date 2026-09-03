"""Scope sizing and immutable model/effort assignments for graph runs."""

from typing import Any, Dict, Mapping, Optional, Tuple

from .hosts import (
    DEFAULT_HOST, catalog_for, dispatch_model, resolve_assignment,
)
from .ids import canonical_bytes, sha256_bytes
from .reviewer_delegation import plan_fragment


TSHIRT_SIZES = ("small", "medium", "large")

# Role intelligence is host-agnostic. Catalogs map these classes onto vendor IDs.
CLASS_ASSIGNMENTS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "small": {
        "impact_mapper": ("economy", "max"),
        "advisory_reviewer": ("economy", "max"),
        "tech_lead": ("reasoning", "medium"),
        "architect": ("reasoning", "medium"),
        "senior_engineer": ("economy", "max"),
        "code_reviewer": ("economy", "max"),
        "test_engineer": ("economy", "max"),
        "audio_realtime_specialist": ("economy", "max"),
        "ios_platform_specialist": ("economy", "max"),
        "release_operations_reviewer": ("reasoning", "medium"),
        "security_reviewer": ("reasoning", "high"),
        "supervisor": ("primary-thread", "inherited"),
    },
    "medium": {
        "impact_mapper": ("economy", "max"),
        "advisory_reviewer": ("reasoning", "medium"),
        "tech_lead": ("reasoning", "medium"),
        "architect": ("reasoning", "high"),
        "senior_engineer": ("reasoning", "medium"),
        "code_reviewer": ("reasoning", "high"),
        "test_engineer": ("economy", "max"),
        "audio_realtime_specialist": ("reasoning", "high"),
        "ios_platform_specialist": ("reasoning", "high"),
        "release_operations_reviewer": ("reasoning", "high"),
        "security_reviewer": ("reasoning", "high"),
        "supervisor": ("primary-thread", "inherited"),
    },
    "large": {
        "impact_mapper": ("economy", "max"),
        "advisory_reviewer": ("reasoning", "high"),
        "tech_lead": ("reasoning", "high"),
        "architect": ("reasoning", "xhigh"),
        "senior_engineer": ("reasoning", "high"),
        "code_reviewer": ("reasoning", "xhigh"),
        "test_engineer": ("reasoning", "high"),
        "audio_realtime_specialist": ("reasoning", "high"),
        "ios_platform_specialist": ("reasoning", "high"),
        "release_operations_reviewer": ("reasoning", "high"),
        "security_reviewer": ("reasoning", "xhigh"),
        "supervisor": ("primary-thread", "inherited"),
    },
}


def _resolved_size_assignments(host: str) -> Dict[str, Dict[str, Tuple[str, str]]]:
    return {
        size: {
            role: resolve_assignment(host, intelligence_class, effort)
            for role, (intelligence_class, effort) in roles.items()
        }
        for size, roles in CLASS_ASSIGNMENTS.items()
    }


# Codex-resolved view used by existing tests and default runs.
SIZE_ASSIGNMENTS: Dict[str, Dict[str, Tuple[str, str]]] = _resolved_size_assignments(DEFAULT_HOST)

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


def _class_for_node(node_key: str, size: str) -> Tuple[str, str]:
    assignment_key = node_key if node_key in CLASS_ASSIGNMENTS[size] else NODE_ROLES[node_key]
    return CLASS_ASSIGNMENTS[size][assignment_key]


def validate_model_assignment(
    node_key: str, model: str, reasoning_effort: str, host: str = DEFAULT_HOST,
) -> None:
    """Fail closed on the graph's model and reasoning-effort invariants."""
    catalog = catalog_for(host)
    intelligence_class = catalog.classify(model)
    if intelligence_class is None:
        raise ValueError("MODEL_ASSIGNMENT_INVALID")
    if intelligence_class == "primary-thread" and reasoning_effort != "inherited":
        raise ValueError("SUPERVISOR_EFFORT_INVALID")
    if intelligence_class == "economy" and reasoning_effort != catalog.economy_effort:
        raise ValueError("ECONOMY_REASONING_EFFORT_REQUIRED")
    if node_key in {"tech_lead", "architect"} and intelligence_class != "reasoning":
        raise ValueError("DESIGN_MODEL_REQUIRED")
    if NODE_ROLES.get(node_key) == "impact_mapper" and intelligence_class != "economy":
        raise ValueError("IMPACT_MAPPER_ASSIGNMENT_REQUIRED")


def recommend_size(task: Mapping[str, Any]) -> Tuple[str, str]:
    if task["risk_level"] == "critical" or task["minimum_route"] == "full_delivery":
        return "large", "critical risk or full-delivery route floor"
    if task["risk_level"] == "high" or task["mandatory_impact_tags"] or task["minimum_route"] in {"design_only", "fast_path"}:
        return "medium", "elevated risk, impact tags, or a delivery/design route"
    return "small", "low-risk advisory work with no mandatory impact tags"


def build_execution_plan(
    run_id: str, task: Mapping[str, Any], requested_size: Optional[str] = None,
    host: str = DEFAULT_HOST,
) -> Dict[str, Any]:
    catalog = catalog_for(host)
    recommended, recommendation_reason = recommend_size(task)
    size = requested_size or recommended
    if size not in TSHIRT_SIZES:
        raise ValueError("invalid execution size")
    assignments = []
    for node_key in sorted(NODE_ROLES):
        role = NODE_ROLES[node_key]
        intelligence_class, requested_effort = _class_for_node(node_key, size)
        model, effort = resolve_assignment(host, intelligence_class, requested_effort)
        validate_model_assignment(node_key, model, effort, host)
        assignments.append({
            "node_key": node_key,
            "role": role,
            "intelligence_class": intelligence_class,
            "model": model,
            "reasoning_effort": effort,
            "dispatch_model": dispatch_model(host, model, effort),
            "dispatch_when": DISPATCH_WHEN[node_key],
        })
    delegation = task.get("reviewer_delegation")
    supervisor_model, supervisor_effort = catalog.supervisor_recommendation
    publication_model, publication_effort = catalog.publication
    plan = {
        "schema_version": 2 if delegation is not None else 1,
        "run_id": run_id,
        "task_id": task["task_id"],
        "host": host,
        "size": size,
        "size_source": "supervisor_override" if requested_size else "supervisor_recommendation",
        "size_recommendation": recommended,
        "size_recommendation_reason": recommendation_reason,
        "minimum_route": task["minimum_route"],
        "mandatory_impact_tags": list(task["mandatory_impact_tags"]),
        "supervisor_recommendation": {
            "model": supervisor_model,
            "reasoning_effort": supervisor_effort,
            "dispatch_model": dispatch_model(host, supervisor_model, supervisor_effort),
        },
        "publication_assignment": {
            "model": publication_model,
            "reasoning_effort": publication_effort,
            "dispatch_model": dispatch_model(host, publication_model, publication_effort),
        },
        "assignments": assignments,
        "approval_id": "execution_plan",
        "approval_required": True,
    }
    if delegation is not None:
        plan["conditional_review_assignments"] = plan_fragment(delegation)
        plan["reviewer_delegation_limits"] = dict(delegation["limits"])
    plan["plan_digest"] = sha256_bytes(canonical_bytes(plan))
    return plan


def assignment_for(plan: Mapping[str, Any], node_key: str) -> Mapping[str, str]:
    host = plan.get("host", DEFAULT_HOST)
    for assignment in plan["assignments"]:
        if assignment["node_key"] == node_key:
            validate_model_assignment(
                node_key, assignment["model"], assignment["reasoning_effort"], host,
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
