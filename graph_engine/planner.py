"""Deterministic route expansion and loop generation planning."""

from dataclasses import dataclass
import itertools
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .ids import stable_id
from .config import ENGINE_ROLE_CAPABILITIES
from .execution import assignment_for, build_execution_plan


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


def fanout_id(run_id: str, policy_digest: str, stage: str, generation: int) -> str:
    return stable_id(run_id, policy_digest, "fanout", stage, generation)


def _resource_name(value: str, case_sensitive: bool) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized if case_sensitive else normalized.casefold()


def _paths_overlap(left: Mapping[str, Any], right: Mapping[str, Any], case_sensitive: bool) -> bool:
    left_path = _resource_name(left["path"], case_sensitive)
    right_path = _resource_name(right["path"], case_sensitive)
    if left["scope"] == right["scope"] == "exact":
        return left_path == right_path
    if left["scope"] == "subtree":
        if right_path == left_path or right_path.startswith(left_path + "/"):
            return True
    if right["scope"] == "subtree":
        return left_path == right_path or left_path.startswith(right_path + "/")
    return False


def validate_fanout_ordering(
    members: Sequence[Mapping[str, Any]], dependencies: Sequence[Mapping[str, Any]],
    *, case_sensitive: bool,
) -> List[Dict[str, str]]:
    """Validate that an assessed fixed fan-out is safe without scheduling arbitrary work."""
    member_ids = [member["branch_id"] for member in members]
    member_set = set(member_ids)
    if len(member_set) != len(member_ids):
        raise ValueError("FANOUT_MEMBER_INVALID")
    edges: Set[Tuple[str, str]] = set()
    normalized_dependencies: List[Dict[str, str]] = []
    for dependency in dependencies:
        before, after = dependency["before_branch_id"], dependency["after_branch_id"]
        edge = (before, after)
        if before not in member_set or after not in member_set:
            raise ValueError("FANOUT_MEMBER_INVALID")
        if before == after:
            raise ValueError("FANOUT_DEPENDENCY_INVALID")
        if edge in edges:
            raise ValueError("FANOUT_DEPENDENCY_INVALID")
        edges.add(edge)
        normalized_dependencies.append({
            "before_branch_id": before, "after_branch_id": after, "reason": dependency["reason"],
        })
    reach = {member_id: set() for member_id in member_ids}
    for before, after in edges:
        reach[before].add(after)
    for pivot in member_ids:
        for before in member_ids:
            if pivot in reach[before]:
                reach[before].update(reach[pivot])
    if any(member_id in reach[member_id] for member_id in member_ids):
        raise ValueError("FANOUT_CYCLE")

    by_id = {member["branch_id"]: member for member in members}
    conflicts: Set[Tuple[str, str]] = set()
    service_capacities: Dict[str, int] = {}
    service_units: Dict[str, Dict[str, int]] = {}
    for member in members:
        resources = member["resources"]
        for service in resources["services"]:
            name = _resource_name(service["ref"], case_sensitive)
            capacity = service["capacity"]
            if name in service_capacities and service_capacities[name] != capacity:
                raise ValueError("FANOUT_CAPACITY_INVALID")
            service_capacities[name] = capacity
            service_units.setdefault(name, {})[member["branch_id"]] = service["units"]
    for left_id, right_id in itertools.combinations(member_ids, 2):
        left = by_id[left_id]["resources"]
        right = by_id[right_id]["resources"]
        path_conflict = any(
            _paths_overlap(a, b, case_sensitive)
            for a in left["writable_paths"] for b in right["writable_paths"]
        )
        mutable_conflict = bool(
            {_resource_name(item, case_sensitive) for item in left["mutable_state_refs"]}
            & {_resource_name(item, case_sensitive) for item in right["mutable_state_refs"]}
        )
        device_conflict = bool(
            {_resource_name(item, case_sensitive) for item in left["exclusive_device_refs"]}
            & {_resource_name(item, case_sensitive) for item in right["exclusive_device_refs"]}
        )
        if path_conflict or mutable_conflict or device_conflict:
            conflicts.add((left_id, right_id))
    if any(right not in reach[left] and left not in reach[right] for left, right in conflicts):
        raise ValueError("FANOUT_UNORDERED_CONFLICT")

    for size in range(1, len(member_ids) + 1):
        for subset in itertools.combinations(member_ids, size):
            if any(b in reach[a] or a in reach[b] for a, b in itertools.combinations(subset, 2)):
                continue
            for service, capacity in service_capacities.items():
                if sum(service_units.get(service, {}).get(member_id, 0) for member_id in subset) > capacity:
                    raise ValueError("FANOUT_CAPACITY_EXCEEDED")
    return sorted(normalized_dependencies, key=lambda item: (
        item["before_branch_id"], item["after_branch_id"], item["reason"],
    ))


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
    execution_plan: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    template = _template(policy, spec.key)
    plan = execution_plan or build_execution_plan(run_id, task)
    assignment = assignment_for(plan, spec.key)
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
        "model": assignment["model"],
        "reasoning_effort": assignment["reasoning_effort"],
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
        "attempt_id": None,
        "claim_digest": None,
        "lease_expires_at": None,
        "failure_code": None,
        "started_at": None,
        "finished_at": None,
    }
