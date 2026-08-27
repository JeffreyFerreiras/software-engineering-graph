"""Deterministic route expansion and loop generation planning."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .ids import stable_id
from .config import ENGINE_ROLE_CAPABILITIES


@dataclass(frozen=True)
class NodeSpec:
    key: str
    role: str
    stage: str
    generation: int
    mandatory: bool = True
    specialist_tag: Optional[str] = None


@dataclass(frozen=True)
class JoinSpec:
    key: str
    kind: str
    stage: str
    generation: int
    members: Tuple[NodeSpec, ...]


def node_id(run_id: str, policy_digest: str, spec: NodeSpec) -> str:
    return stable_id(run_id, policy_digest, "node", spec.key + "@" + spec.stage, spec.generation, spec.specialist_tag)


def branch_id(run_id: str, policy_digest: str, spec: NodeSpec) -> str:
    return stable_id(run_id, policy_digest, "branch", spec.key + "@" + spec.stage, spec.generation, spec.specialist_tag)


def join_id(run_id: str, policy_digest: str, spec: JoinSpec) -> str:
    return stable_id(run_id, policy_digest, "join", spec.key, spec.generation)


def _template(policy: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return policy["node_templates"][key]


def make_node(
    policy: Mapping[str, Any], key: str, stage: str, generation: int,
    mandatory: bool = True, specialist_tag: Optional[str] = None,
) -> NodeSpec:
    template = _template(policy, key)
    return NodeSpec(key, template["role"], stage, generation, mandatory, specialist_tag)


def selected_specialists(
    policy: Mapping[str, Any], tags: Sequence[str], stage: str, generation: int
) -> List[NodeSpec]:
    result: List[NodeSpec] = []
    for tag in sorted(tags):
        config = policy["specialists"].get(tag)
        if config and stage in config["stages"]:
            result.append(NodeSpec(config["node_key"], config["role"], stage, generation, bool(config["mandatory"]), tag))
    return result


def bootstrap(policy: Mapping[str, Any]) -> NodeSpec:
    return make_node(policy, "impact_mapper", "bootstrap", 0)


def initial_route_nodes(policy: Mapping[str, Any], route: str) -> List[NodeSpec]:
    if route in {"design_only", "full_delivery"}:
        return [make_node(policy, "tech_lead", "design", 0)]
    if route == "fast_path":
        return [make_node(policy, "senior_engineer", "implementation", 0)]
    return [make_node(policy, "advisory_reviewer", "advisory", 0)]


def next_join_for_success(
    policy: Mapping[str, Any], route: str, tags: Sequence[str], node: Mapping[str, Any]
) -> Optional[JoinSpec]:
    key = node["node_key"]
    generation = node["generation"]
    if key == "tech_lead":
        return JoinSpec("design_inputs", "dependency", "design", generation, (_as_spec(node),))
    if key == "senior_engineer":
        if route == "fast_path":
            return JoinSpec("implementation", "dependency", "delivery", generation, (_as_spec(node),))
        return JoinSpec("implementation", "dependency", "delivery", generation, (_as_spec(node),))
    if key == "advisory_reviewer":
        return JoinSpec("closure", "closure", "closure", generation, (_as_spec(node),))
    return None


def design_review_nodes(policy: Mapping[str, Any], tags: Sequence[str], generation: int) -> List[NodeSpec]:
    return [make_node(policy, "architect", "design", generation)] + selected_specialists(policy, tags, "design", generation)


def delivery_review_nodes(policy: Mapping[str, Any], tags: Sequence[str], generation: int) -> List[NodeSpec]:
    return [
        make_node(policy, "code_reviewer", "delivery", generation),
        make_node(policy, "test_engineer", "delivery", generation),
    ] + selected_specialists(policy, tags, "delivery", generation)


def consolidation_node(policy: Mapping[str, Any], stage: str, generation: int) -> NodeSpec:
    key = "supervisor_design_consolidation" if stage == "design" else "supervisor_delivery_consolidation"
    return make_node(policy, key, stage, generation)


def collection_join(stage: str, generation: int, members: Iterable[NodeSpec]) -> JoinSpec:
    return JoinSpec(stage + "_collection", "collection", stage, generation, tuple(members))


def consolidation_join(stage: str, generation: int, member: NodeSpec) -> JoinSpec:
    return JoinSpec(stage + "_consolidation", "consolidation", stage, generation, (member,))


def implementation_node(policy: Mapping[str, Any], generation: int) -> NodeSpec:
    return make_node(policy, "senior_engineer", "implementation", generation)


def revised_design_node(policy: Mapping[str, Any], generation: int) -> NodeSpec:
    return make_node(policy, "tech_lead", "design", generation)


def closure_join(member: NodeSpec, generation: int) -> JoinSpec:
    return JoinSpec("closure", "closure", "closure", generation, (member,))


def _as_spec(row: Mapping[str, Any]) -> NodeSpec:
    specialist_tag = row["specialist_tag"] if "specialist_tag" in row.keys() else None
    return NodeSpec(
        row["node_key"], row["role"], row["stage"], row["generation"],
        bool(row["mandatory"]), specialist_tag,
    )


def envelope(
    run_id: str,
    policy_digest: str,
    policy: Mapping[str, Any],
    task: Mapping[str, Any],
    spec: NodeSpec,
    status: str,
    inputs: Sequence[Mapping[str, Any]],
    retry_count: int = 0,
) -> Dict[str, Any]:
    template = _template(policy, spec.key)
    authority = task["authority"]["capabilities"]
    configured = {
        (cap["effect"], cap["action"], cap["target_ref"])
        for cap in policy["role_capabilities"].get(spec.role, [])
        if (cap["effect"], cap["action"], cap["target_ref"]) in ENGINE_ROLE_CAPABILITIES.get(spec.role, set())
    }
    capabilities = [
        cap for cap in authority
        if (cap["effect"], cap["action"], cap["target_ref"]) in configured
        and (spec.stage != "advisory" or cap["effect"] in {"filesystem_read", "external_read"})
    ]
    output_contract = dict(template["output_contract"])
    max_retries = int(template["max_retries"])
    return {
        "schema_version": 1,
        "run_id": run_id,
        "branch_id": branch_id(run_id, policy_digest, spec),
        "node_instance_id": node_id(run_id, policy_digest, spec),
        "node_key": spec.key,
        "role": spec.role,
        "mandatory": spec.mandatory,
        "generation": spec.generation,
        "status": status,
        "inputs": sorted([dict(item) for item in inputs], key=lambda item: (item["kind"], item["ref"])),
        "effect_capabilities": sorted(capabilities, key=lambda cap: (cap["effect"], cap["action"], cap["target_ref"])),
        "output_contract": output_contract,
        "stopping_condition": {
            "kind": "valid_result_returned",
            "max_branch_attempts": max_retries + 1,
        },
        "artifact_ref": None,
        "evidence": [],
        "decision": None,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "failure_code": None,
        "started_at": None,
        "finished_at": None,
    }
