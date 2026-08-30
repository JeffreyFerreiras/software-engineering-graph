"""Strict, bounded graph input contracts."""

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .ids import sha256_bytes


OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
FINDING_ID = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]{3,}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
CREDENTIAL_VALUE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:bearer\s+[A-Za-z0-9._~+/=-]+)|"
    r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)
SECRET_KEYS = {
    "token", "password", "secret", "authorization", "cookie", "private_key",
    "api_key", "access_key", "client_secret",
}
ROUTES = {"advisory", "design_only", "full_delivery", "fast_path"}
REQUEST_ROUTES = {
    "advisory": {"advisory"},
    "design_only": {"design_only"},
    "delivery": {"fast_path", "full_delivery"},
}
EFFECTS = {
    "filesystem_read", "filesystem_write", "command", "external_read",
    "external_write", "destructive", "publish", "deploy",
}
RISK_TAGS = {
    "production_behavior", "cross_layer", "dependency", "persistence",
    "security_privacy", "release_operations", "audio_realtime_translation",
    "ios_webkit_native",
}
DENIED_PARTS = {
    ".git", ".hg", ".svn", ".ssh", "secret", "secrets", "credential",
    "credentials", "keys", "graph-runs", "graph-inbox",
}
DENIED_NAMES = {".env", "id_rsa", "id_ed25519"}
DENIED_SUFFIXES = {".pem", ".key", ".pfx", ".p12"}


class ContractError(ValueError):
    def __init__(self, field: str, code: str):
        self.field = field
        self.code = code
        super().__init__(f"{field}:{code}")


@dataclass(frozen=True)
class Snapshot:
    path: Path
    data: bytes
    digest: str
    size: int
    parsed: Any
    identity: Tuple[int, int]


def require_keys(
    value: Mapping[str, Any], required: Iterable[str], allowed: Iterable[str], field: str
) -> None:
    required_set, allowed_set = set(required), set(allowed)
    missing = required_set - set(value)
    unknown = set(value) - allowed_set
    if missing:
        raise ContractError(field, "MISSING_FIELD")
    if unknown:
        raise ContractError(field, "UNKNOWN_FIELD")


def opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not OPAQUE_ID.fullmatch(value):
        raise ContractError(field, "INVALID_ID")
    return value


def digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ContractError(field, "INVALID_DIGEST")
    return value


def bounded_string(value: Any, field: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractError(field, "INVALID_STRING")
    if CONTROL.search(value):
        raise ContractError(field, "CONTROL_CHARACTER")
    if CREDENTIAL_VALUE.search(value):
        raise ContractError(field, "CREDENTIAL_VALUE")
    return value


def reject_sensitive(value: Any, field: str = "root", depth: int = 0) -> None:
    if depth > 24:
        raise ContractError(field, "MAX_DEPTH")
    if isinstance(value, dict):
        if len(value) > 4096:
            raise ContractError(field, "MAX_ITEMS")
        for key, item in value.items():
            if not isinstance(key, str) or CONTROL.search(key):
                raise ContractError(field, "INVALID_KEY")
            normalized = key.lower().replace("-", "_")
            if normalized in SECRET_KEYS or any(part in normalized.split("_") for part in SECRET_KEYS):
                raise ContractError(field + "." + key, "SECRET_FIELD")
            reject_sensitive(item, field + "." + key, depth + 1)
    elif isinstance(value, list):
        if len(value) > 4096:
            raise ContractError(field, "MAX_ITEMS")
        for index, item in enumerate(value):
            reject_sensitive(item, f"{field}[{index}]", depth + 1)
    elif isinstance(value, str):
        bounded_string(value, field)
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ContractError(field, "INVALID_TYPE")


def _is_reparse(path: Path) -> bool:
    if os.name != "nt":
        return False
    attrs = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def ensure_safe_components(path: Path, stop: Optional[Path] = None) -> None:
    current = path
    checked: List[Path] = []
    while True:
        checked.append(current)
        if stop is not None and current == stop:
            break
        if current.parent == current:
            break
        current = current.parent
    for component in reversed(checked):
        if component.exists() and (component.is_symlink() or _is_reparse(component)):
            raise ContractError("path", "LINK_OR_REPARSE_POINT")


def lexical_relative(path_text: str, field: str = "ref") -> str:
    bounded_string(path_text, field, 1024)
    text = path_text.replace("\\", "/")
    directory_root = text.endswith("/")
    text = text.rstrip("/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ContractError(field, "ABSOLUTE_PATH")
    parts = text.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ContractError(field, "PATH_TRAVERSAL")
    lowered = [part.lower() for part in parts]
    if any(part in DENIED_PARTS for part in lowered):
        raise ContractError(field, "SENSITIVE_PATH")
    name = lowered[-1]
    if name in DENIED_NAMES or name.startswith(".env.") or Path(name).suffix in DENIED_SUFFIXES:
        raise ContractError(field, "SENSITIVE_PATH")
    normalized = "/".join(parts)
    return normalized + "/" if directory_root else normalized


def safe_file_snapshot(path: Path, roots: Sequence[Path], maximum: int) -> Snapshot:
    candidate = path.absolute()
    allowed = False
    for root in roots:
        root_abs = root.absolute()
        try:
            relative = candidate.relative_to(root_abs)
            lexical_relative(relative.as_posix(), "path")
            allowed = True
            ensure_safe_components(candidate, root_abs)
            break
        except ValueError:
            continue
    if not allowed:
        raise ContractError("path", "OUTSIDE_ALLOWED_ROOT")
    pre = candidate.lstat()
    if not stat.S_ISREG(pre.st_mode) or candidate.is_symlink() or _is_reparse(candidate):
        raise ContractError("path", "NOT_REGULAR_FILE")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(candidate), flags)
    try:
        opened = os.fstat(fd)
        if (pre.st_dev, pre.st_ino) != (opened.st_dev, opened.st_ino):
            raise ContractError("path", "FILE_CHANGED")
        chunks: List[bytes] = []
        size = 0
        while True:
            chunk = os.read(fd, min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise ContractError("path", "FILE_TOO_LARGE")
        post = os.fstat(fd)
        if ((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) !=
                (post.st_dev, post.st_ino, post.st_size, post.st_mtime_ns)):
            raise ContractError("path", "FILE_CHANGED")
        final_path = candidate.lstat()
        if candidate.is_symlink() or _is_reparse(candidate) or (final_path.st_dev, final_path.st_ino) != (post.st_dev, post.st_ino):
            raise ContractError("path", "FILE_CHANGED")
    finally:
        os.close(fd)
    data = b"".join(chunks)
    return Snapshot(candidate, data, sha256_bytes(data), len(data), None, (pre.st_dev, pre.st_ino))


def safe_json_snapshot(path: Path, roots: Sequence[Path], maximum: int) -> Snapshot:
    snapshot = safe_file_snapshot(path, roots, maximum)
    try:
        parsed = json.loads(snapshot.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ContractError("path", "INVALID_JSON")
    reject_sensitive(parsed)
    return Snapshot(
        snapshot.path, snapshot.data, snapshot.digest, snapshot.size, parsed, snapshot.identity
    )


def validate_ref(value: Any, field: str, content_required: bool = False) -> str:
    text = bounded_string(value, field, 1200)
    if "://" in text or text.lower().startswith(("http:", "https:", "file:")):
        raise ContractError(field, "URL_FORBIDDEN")
    if text.startswith("repo:"):
        body = text[5:]
        path_part, marker, hash_part = body.partition("#sha256=")
        lexical_relative(path_part, field)
        if content_required and not marker:
            raise ContractError(field, "CONTENT_DIGEST_REQUIRED")
        if marker:
            digest(hash_part, field)
    elif text.startswith("profile:software-engineering-graph/"):
        body = text[len("profile:software-engineering-graph/"):]
        path_part, marker, hash_part = body.partition("#sha256=")
        lexical_relative(path_part, field)
        if not path_part.startswith("references/"):
            raise ContractError(field, "PROFILE_ROOT_FORBIDDEN")
        if content_required and not marker:
            raise ContractError(field, "CONTENT_DIGEST_REQUIRED")
        if marker:
            digest(hash_part, field)
    elif text.startswith("ledger:"):
        body = text[7:]
        identity, marker, hash_part = body.partition("#sha256=")
        opaque(identity, field)
        if content_required and not marker:
            raise ContractError(field, "CONTENT_DIGEST_REQUIRED")
        if marker:
            digest(hash_part, field)
    elif text.startswith(("thread:", "authority:")):
        prefix, identity = text.split(":", 1)
        opaque(identity, field)
        if content_required or "#" in identity or "?" in identity:
            raise ContractError(field, "AUDIT_REF_NOT_CONTENT")
    else:
        raise ContractError(field, "UNSUPPORTED_REFERENCE")
    return text


def _unique_strings(values: Any, field: str, allowed: Optional[Set[str]] = None) -> List[str]:
    if not isinstance(values, list):
        raise ContractError(field, "INVALID_LIST")
    result = [bounded_string(item, field, 1024) for item in values]
    if len(set(result)) != len(result):
        raise ContractError(field, "DUPLICATE_VALUE")
    if allowed is not None and any(item not in allowed for item in result):
        raise ContractError(field, "UNKNOWN_VALUE")
    return sorted(result)


def _validate_attempt(value: Mapping[str, Any], field: str) -> None:
    opaque(value.get("attempt_id"), field + ".attempt_id")
    digest(value.get("claim_digest"), field + ".claim_digest")


def validate_fanout_assessment(
    value: Any, run_id: str, fanout_id: str, expected_members: Sequence[str],
) -> Dict[str, Any]:
    """Validate and canonicalize a Supervisor resource assessment manifest."""
    if not isinstance(value, dict):
        raise ContractError("assessment_manifest", "FANOUT_ASSESSMENT_INVALID")
    required = {"schema_version", "kind", "run_id", "fanout_id", "members", "dependencies", "evidence"}
    require_keys(value, required, required, "assessment_manifest")
    if (value["schema_version"] != 1 or value["kind"] != "fanout_assessment"
            or value["run_id"] != run_id or value["fanout_id"] != fanout_id):
        raise ContractError("assessment_manifest", "FANOUT_ASSESSMENT_INVALID")
    if not isinstance(value["members"], list):
        raise ContractError("members", "FANOUT_MEMBER_INVALID")
    normalized_members: List[Dict[str, Any]] = []
    for index, member in enumerate(value["members"]):
        field = "members[{}]".format(index)
        if not isinstance(member, dict):
            raise ContractError(field, "FANOUT_MEMBER_INVALID")
        require_keys(member, {"branch_id", "resources"}, {"branch_id", "resources"}, field)
        branch = opaque(member["branch_id"], field + ".branch_id")
        resources = member["resources"]
        if not isinstance(resources, dict):
            raise ContractError(field + ".resources", "FANOUT_RESOURCE_INVALID")
        resource_keys = {"writable_paths", "mutable_state_refs", "exclusive_device_refs", "services"}
        require_keys(resources, resource_keys, resource_keys, field + ".resources")
        writable_paths: List[Dict[str, str]] = []
        if not isinstance(resources["writable_paths"], list):
            raise ContractError(field + ".writable_paths", "FANOUT_RESOURCE_INVALID")
        for path_index, item in enumerate(resources["writable_paths"]):
            path_field = "{}.writable_paths[{}]".format(field, path_index)
            if not isinstance(item, dict):
                raise ContractError(path_field, "FANOUT_RESOURCE_INVALID")
            require_keys(item, {"path", "scope"}, {"path", "scope"}, path_field)
            if item["scope"] not in {"exact", "subtree"}:
                raise ContractError(path_field + ".scope", "FANOUT_RESOURCE_INVALID")
            path = lexical_relative(item["path"], path_field + ".path").rstrip("/")
            writable_paths.append({"path": path, "scope": item["scope"]})
        if len({(item["path"], item["scope"]) for item in writable_paths}) != len(writable_paths):
            raise ContractError(field + ".writable_paths", "FANOUT_RESOURCE_INVALID")
        mutable = _unique_strings(resources["mutable_state_refs"], field + ".mutable_state_refs")
        devices = _unique_strings(resources["exclusive_device_refs"], field + ".exclusive_device_refs")
        if not isinstance(resources["services"], list):
            raise ContractError(field + ".services", "FANOUT_RESOURCE_INVALID")
        services: List[Dict[str, Any]] = []
        for service_index, service in enumerate(resources["services"]):
            service_field = "{}.services[{}]".format(field, service_index)
            if not isinstance(service, dict):
                raise ContractError(service_field, "FANOUT_RESOURCE_INVALID")
            require_keys(service, {"ref", "units", "capacity"}, {"ref", "units", "capacity"}, service_field)
            ref = bounded_string(service["ref"], service_field + ".ref", 1024)
            if (not isinstance(service["units"], int) or isinstance(service["units"], bool)
                    or not isinstance(service["capacity"], int) or isinstance(service["capacity"], bool)
                    or service["units"] <= 0 or service["capacity"] <= 0
                    or service["units"] > service["capacity"]):
                raise ContractError(service_field, "FANOUT_CAPACITY_INVALID")
            services.append({"ref": ref, "units": service["units"], "capacity": service["capacity"]})
        if len({item["ref"] for item in services}) != len(services):
            raise ContractError(field + ".services", "FANOUT_RESOURCE_INVALID")
        normalized_members.append({
            "branch_id": branch,
            "resources": {
                "writable_paths": sorted(writable_paths, key=lambda item: (item["path"], item["scope"])),
                "mutable_state_refs": mutable, "exclusive_device_refs": devices,
                "services": sorted(services, key=lambda item: item["ref"]),
            },
        })
    actual_members = [member["branch_id"] for member in normalized_members]
    if len(set(actual_members)) != len(actual_members) or set(actual_members) != set(expected_members):
        raise ContractError("members", "FANOUT_MEMBER_INVALID")
    if not isinstance(value["dependencies"], list):
        raise ContractError("dependencies", "FANOUT_DEPENDENCY_INVALID")
    dependencies: List[Dict[str, str]] = []
    for index, dependency in enumerate(value["dependencies"]):
        field = "dependencies[{}]".format(index)
        if not isinstance(dependency, dict):
            raise ContractError(field, "FANOUT_DEPENDENCY_INVALID")
        keys = {"before_branch_id", "after_branch_id", "reason"}
        require_keys(dependency, keys, keys, field)
        dependencies.append({
            "before_branch_id": opaque(dependency["before_branch_id"], field + ".before_branch_id"),
            "after_branch_id": opaque(dependency["after_branch_id"], field + ".after_branch_id"),
            "reason": bounded_string(dependency["reason"], field + ".reason", 1024),
        })
    if not isinstance(value["evidence"], list) or not value["evidence"]:
        raise ContractError("evidence", "FANOUT_EVIDENCE_REQUIRED")
    evidence: List[Dict[str, str]] = []
    for index, item in enumerate(value["evidence"]):
        field = "evidence[{}]".format(index)
        if not isinstance(item, dict):
            raise ContractError(field, "FANOUT_EVIDENCE_REQUIRED")
        require_keys(item, {"kind", "ref", "sha256"}, {"kind", "ref", "sha256"}, field)
        evidence.append({
            "kind": opaque(item["kind"], field + ".kind"),
            "ref": validate_ref(item["ref"], field + ".ref", content_required=True),
            "sha256": digest(item["sha256"], field + ".sha256"),
        })
    if len({item["ref"] for item in evidence}) != len(evidence):
        raise ContractError("evidence", "FANOUT_EVIDENCE_REQUIRED")
    return {
        "schema_version": 1, "kind": "fanout_assessment", "run_id": run_id,
        "fanout_id": fanout_id,
        "members": sorted(normalized_members, key=lambda item: item["branch_id"]),
        "dependencies": sorted(dependencies, key=lambda item: (
            item["before_branch_id"], item["after_branch_id"], item["reason"],
        )),
        "evidence": sorted(evidence, key=lambda item: (item["kind"], item["ref"])),
    }


def validate_task_brief(value: Any, policy_digest: str, policy: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("task_brief", "INVALID_OBJECT")
    required = {
        "schema_version", "task_id", "objective", "user_outcome", "request_mode",
        "minimum_route", "mandatory_impact_tags", "scope", "constraints",
        "acceptance_criteria", "risk_level", "authority", "policy_approval",
        "evidence_paths", "inspection_budget", "required_check_ids",
        "required_human_decisions",
    }
    require_keys(value, required, required, "task_brief")
    if value["schema_version"] != 1:
        raise ContractError("schema_version", "UNSUPPORTED_SCHEMA")
    opaque(value["task_id"], "task_id")
    bounded_string(value["objective"], "objective")
    bounded_string(value["user_outcome"], "user_outcome")
    mode = value["request_mode"]
    minimum = value["minimum_route"]
    if mode not in REQUEST_ROUTES or minimum not in REQUEST_ROUTES[mode]:
        raise ContractError("minimum_route", "ROUTE_MODE_MISMATCH")
    tags = _unique_strings(value["mandatory_impact_tags"], "mandatory_impact_tags", set(policy["impact_tags"]))
    if mode == "delivery" and minimum == "fast_path" and set(tags) & RISK_TAGS:
        raise ContractError("minimum_route", "FAST_PATH_INVARIANT")
    scope = value["scope"]
    if not isinstance(scope, dict):
        raise ContractError("scope", "INVALID_OBJECT")
    require_keys(scope, {"included", "excluded"}, {"included", "excluded"}, "scope")
    _unique_strings(scope["included"], "scope.included")
    _unique_strings(scope["excluded"], "scope.excluded")
    _unique_strings(value["constraints"], "constraints")
    criteria = value["acceptance_criteria"]
    if not isinstance(criteria, list) or not criteria:
        raise ContractError("acceptance_criteria", "INVALID_LIST")
    criterion_ids = []
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise ContractError("acceptance_criteria", "INVALID_OBJECT")
        require_keys(criterion, {"id", "text"}, {"id", "text"}, "acceptance_criteria")
        criterion_ids.append(opaque(criterion["id"], "acceptance_criteria.id"))
        bounded_string(criterion["text"], "acceptance_criteria.text")
    if len(set(criterion_ids)) != len(criterion_ids):
        raise ContractError("acceptance_criteria", "DUPLICATE_ID")
    if value["risk_level"] not in {"low", "medium", "high", "critical"}:
        raise ContractError("risk_level", "UNKNOWN_VALUE")
    if value["risk_level"] == "critical" and mode == "delivery":
        if minimum != "full_delivery":
            raise ContractError("minimum_route", "CRITICAL_REQUIRES_FULL_DELIVERY")
        if "security_privacy" not in tags:
            raise ContractError("mandatory_impact_tags", "CRITICAL_REQUIRES_SECURITY_REVIEW")
    authority = value["authority"]
    if not isinstance(authority, dict):
        raise ContractError("authority", "INVALID_OBJECT")
    require_keys(authority, {"capabilities"}, {"capabilities"}, "authority")
    capabilities = authority["capabilities"]
    if not isinstance(capabilities, list):
        raise ContractError("authority.capabilities", "INVALID_LIST")
    canonical_capabilities = []
    command_ids = {check["command_id"] for check in policy["required_checks"].values()}
    policy_capabilities = {
        (cap["effect"], cap["action"], cap["target_ref"])
        for capabilities_for_role in policy["role_capabilities"].values()
        for cap in capabilities_for_role
    }
    for cap in capabilities:
        if not isinstance(cap, dict):
            raise ContractError("authority.capabilities", "INVALID_OBJECT")
        require_keys(cap, {"effect", "action", "target_ref"}, {"effect", "action", "target_ref"}, "capability")
        if cap["effect"] not in EFFECTS:
            raise ContractError("capability.effect", "UNKNOWN_VALUE")
        action = opaque(cap["action"], "capability.action")
        target = validate_ref(cap["target_ref"], "capability.target_ref") if cap["effect"].startswith("filesystem") else opaque(cap["target_ref"], "capability.target_ref")
        if cap["effect"] == "command" and target not in command_ids:
            raise ContractError("capability.target_ref", "UNKNOWN_COMMAND_TARGET")
        capability_tuple = (cap["effect"], action, target)
        if capability_tuple not in policy_capabilities:
            raise ContractError("authority.capabilities", "POLICY_AUTHORITY_EXCEEDED")
        if mode == "advisory" and cap["effect"] not in {"filesystem_read", "external_read"}:
            raise ContractError("authority.capabilities", "ADVISORY_MUST_BE_READ_ONLY")
        canonical_capabilities.append({"effect": cap["effect"], "action": action, "target_ref": target})
    keyed = {(c["effect"], c["action"], c["target_ref"]) for c in canonical_capabilities}
    if len(keyed) != len(canonical_capabilities):
        raise ContractError("authority.capabilities", "DUPLICATE_VALUE")
    approval = value["policy_approval"]
    if not isinstance(approval, dict):
        raise ContractError("policy_approval", "INVALID_OBJECT")
    require_keys(approval, {"sha256", "authority_ref"}, {"sha256", "authority_ref"}, "policy_approval")
    if digest(approval["sha256"], "policy_approval.sha256") != policy_digest:
        raise ContractError("policy_approval.sha256", "POLICY_DIGEST_MISMATCH")
    validate_ref(approval["authority_ref"], "policy_approval.authority_ref")
    for ref in value["evidence_paths"]:
        validate_ref(ref, "evidence_paths")
    budget = value["inspection_budget"]
    if not isinstance(budget, dict):
        raise ContractError("inspection_budget", "INVALID_OBJECT")
    require_keys(budget, {"file_reads", "discovery_commands"}, {"file_reads", "discovery_commands"}, "inspection_budget")
    for key in ("file_reads", "discovery_commands"):
        amount = budget[key]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0 or amount > policy["limits"]["inspection"][key]:
            raise ContractError("inspection_budget." + key, "BUDGET_LIMIT")
    check_ids = _unique_strings(value["required_check_ids"], "required_check_ids")
    required_policy_checks = {key for key, cfg in policy["required_checks"].items() if cfg["mandatory"]}
    if not required_policy_checks.issubset(check_ids):
        raise ContractError("required_check_ids", "MISSING_REQUIRED_CHECK")
    _unique_strings(value["required_human_decisions"], "required_human_decisions")
    result = dict(value)
    result["mandatory_impact_tags"] = tags
    result["authority"] = {"capabilities": sorted(canonical_capabilities, key=lambda c: (c["effect"], c["action"], c["target_ref"]))}
    return result


def authoritative_task_subset(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Return only approved structured task metadata suitable for the ledger."""
    return {
        "schema_version": value["schema_version"],
        "task_id": value["task_id"],
        "request_mode": value["request_mode"],
        "minimum_route": value["minimum_route"],
        "mandatory_impact_tags": list(value["mandatory_impact_tags"]),
        "risk_level": value["risk_level"],
        "acceptance_ids": [item["id"] for item in value["acceptance_criteria"]],
        "authority": value["authority"],
        "policy_approval": value["policy_approval"],
        "evidence_paths": list(value["evidence_paths"]),
        "inspection_budget": dict(value["inspection_budget"]),
        "required_check_ids": list(value["required_check_ids"]),
        "required_human_decisions": list(value["required_human_decisions"]),
    }


def validate_impact_map(value: Any, task: Mapping[str, Any], policy: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("impact_map", "INVALID_OBJECT")
    allowed = {"schema_version", "task_id", "route_label", "impact_tags", "evidence_refs", "attempt_id", "claim_digest"}
    require_keys(value, allowed, allowed, "impact_map")
    _validate_attempt(value, "impact_map")
    if value["schema_version"] != 1 or value["task_id"] != task["task_id"]:
        raise ContractError("impact_map", "TASK_OR_SCHEMA_MISMATCH")
    route = value["route_label"]
    if route not in ROUTES or route not in policy["routes"]:
        raise ContractError("route_label", "UNKNOWN_ROUTE")
    mode = task["request_mode"]
    if route not in REQUEST_ROUTES[mode]:
        raise ContractError("route_label", "ROUTE_MODE_MISMATCH")
    if mode == "delivery" and task["minimum_route"] == "full_delivery" and route != "full_delivery":
        raise ContractError("route_label", "ROUTE_DOWNGRADE")
    tags = _unique_strings(value["impact_tags"], "impact_tags", set(policy["impact_tags"]))
    if not set(task["mandatory_impact_tags"]).issubset(tags):
        raise ContractError("impact_tags", "MANDATORY_TAG_REMOVED")
    if task["request_mode"] == "delivery" and task["risk_level"] == "critical":
        if route != "full_delivery":
            raise ContractError("route_label", "CRITICAL_REQUIRES_FULL_DELIVERY")
        if "security_privacy" not in tags:
            raise ContractError("impact_tags", "CRITICAL_REQUIRES_SECURITY_REVIEW")
    if mode == "delivery" and route == "fast_path" and set(tags) & RISK_TAGS:
        raise ContractError("route_label", "FAST_PATH_INVARIANT")
    for ref in value["evidence_refs"]:
        validate_ref(ref, "evidence_refs")
    result = dict(value)
    result["impact_tags"] = tags
    return result


def validate_result_manifest(value: Any, branch: Mapping[str, Any]) -> Dict[str, Any]:
    if branch["node_key"] == "impact_mapper" and isinstance(value, dict) and "status" not in value:
        return value
    if branch["node_key"] in {"supervisor_design_consolidation", "supervisor_delivery_consolidation"}:
        if not isinstance(value, dict):
            raise ContractError("consolidation", "INVALID_OBJECT")
        allowed = {
            "schema_version", "kind", "run_id", "join_id", "generation",
            "source_branch_ids", "finding_dispositions", "outcome", "attempt_id", "claim_digest",
        }
        require_keys(value, allowed, allowed, "consolidation")
        _validate_attempt(value, "consolidation")
        if value["schema_version"] != 1 or value["run_id"] != branch["run_id"]:
            raise ContractError("consolidation", "RUN_OR_SCHEMA_MISMATCH")
        expected_kind = "design_consolidation" if branch["node_key"].startswith("supervisor_design") else "delivery_consolidation"
        if value["kind"] != expected_kind or value["generation"] != branch["generation"]:
            raise ContractError("consolidation", "KIND_OR_GENERATION_MISMATCH")
        opaque(value["join_id"], "join_id")
        sources = _unique_strings(value["source_branch_ids"], "source_branch_ids")
        dispositions = value["finding_dispositions"]
        if not isinstance(dispositions, list):
            raise ContractError("finding_dispositions", "INVALID_LIST")
        seen = set()
        for item in dispositions:
            if not isinstance(item, dict):
                raise ContractError("finding_dispositions", "INVALID_OBJECT")
            require_keys(item, {"finding_id", "disposition"}, {"finding_id", "disposition"}, "finding_dispositions")
            if not FINDING_ID.fullmatch(item["finding_id"]):
                raise ContractError("finding_id", "INVALID_ID")
            if item["disposition"] not in {"approve", "revise", "accept", "repair", "redesign", "block"}:
                raise ContractError("disposition", "UNKNOWN_VALUE")
            if item["finding_id"] in seen:
                raise ContractError("finding_id", "DUPLICATE_ID")
            seen.add(item["finding_id"])
        outcomes = {"APPROVE", "REVISE", "BLOCK"} if expected_kind.startswith("design") else {"ACCEPT", "REPAIR", "REDESIGN", "BLOCK"}
        if value["outcome"] not in outcomes:
            raise ContractError("outcome", "UNKNOWN_VALUE")
        normalized = dict(value)
        normalized.update({
            "branch_id": branch["branch_id"], "status": "succeeded",
            "output_kind": expected_kind, "evidence": [], "decision": value["outcome"],
        })
        return normalized
    if not isinstance(value, dict):
        raise ContractError("result", "INVALID_OBJECT")
    allowed = {
        "schema_version", "run_id", "branch_id", "status", "output_kind",
        "artifact_ref", "evidence", "decision", "findings", "failure_code",
        "kind", "join_id", "generation", "source_branch_ids", "finding_dispositions",
        "outcome", "attempt_id", "claim_digest",
    }
    required = {"schema_version", "run_id", "branch_id", "status", "output_kind", "evidence", "attempt_id", "claim_digest"}
    require_keys(value, required, allowed, "result")
    _validate_attempt(value, "result")
    if value["schema_version"] != 1 or value["run_id"] != branch["run_id"] or value["branch_id"] != branch["branch_id"]:
        raise ContractError("result", "BRANCH_MISMATCH")
    if value["status"] not in {"succeeded", "failed"}:
        raise ContractError("status", "INVALID_RESULT_STATUS")
    if value["output_kind"] != branch["output_contract"]["artifact_kind"]:
        raise ContractError("output_kind", "OUTPUT_CONTRACT_MISMATCH")
    evidence = value["evidence"]
    if not isinstance(evidence, list):
        raise ContractError("evidence", "INVALID_LIST")
    evidence_keys = []
    for item in evidence:
        if not isinstance(item, dict):
            raise ContractError("evidence", "INVALID_OBJECT")
        require_keys(item, {"kind", "ref", "sha256"}, {"kind", "ref", "sha256"}, "evidence")
        bounded_string(item["kind"], "evidence.kind", 64)
        validate_ref(item["ref"], "evidence.ref", content_required=True)
        digest(item["sha256"], "evidence.sha256")
        evidence_keys.append((item["kind"], item["ref"], item["sha256"]))
    if len(set(evidence_keys)) != len(evidence_keys):
        raise ContractError("evidence", "DUPLICATE_VALUE")
    if value["status"] == "failed":
        opaque(value.get("failure_code"), "failure_code")
        if not evidence:
            raise ContractError("evidence", "EVIDENCE_REQUIRED")
    else:
        artifact = value.get("artifact_ref")
        redesign_required = (
            branch["node_key"] == "senior_engineer"
            and value.get("decision") == "REDESIGN_REQUIRED"
        )
        if redesign_required and artifact is not None:
            raise ContractError("artifact_ref", "REDESIGN_ARTIFACT_FORBIDDEN")
        artifact_required_decisions = set(
            branch["output_contract"].get("artifact_required_for_decisions", [])
        )
        artifact_required = (
            branch["output_contract"].get("artifact_required", True)
            or value.get("decision") in artifact_required_decisions
        )
        if artifact_required and not redesign_required:
            if not isinstance(artifact, dict):
                raise ContractError("artifact_ref", "ARTIFACT_REQUIRED")
            require_keys(artifact, {"kind", "ref", "sha256"}, {"kind", "ref", "sha256"}, "artifact_ref")
            if artifact["kind"] != value["output_kind"]:
                raise ContractError("artifact_ref.kind", "OUTPUT_CONTRACT_MISMATCH")
            validate_ref(artifact["ref"], "artifact_ref.ref", content_required=True)
            digest(artifact["sha256"], "artifact_ref.sha256")
        decisions = branch["output_contract"].get("decision_values", [])
        if decisions and value.get("decision") not in decisions:
            raise ContractError("decision", "DECISION_CONTRACT_MISMATCH")
        if (value.get("decision") in set(branch["output_contract"].get("evidence_required_for_decisions", []))
                and not evidence):
            raise ContractError("evidence", "REDESIGN_EVIDENCE_REQUIRED")
    findings = value.get("findings", [])
    if not isinstance(findings, list):
        raise ContractError("findings", "INVALID_LIST")
    seen = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise ContractError("findings", "INVALID_OBJECT")
        require_keys(finding, {"finding_id", "disposition"}, {"finding_id", "disposition"}, "findings")
        if not FINDING_ID.fullmatch(finding["finding_id"]):
            raise ContractError("finding_id", "INVALID_ID")
        if finding["disposition"] not in {"approve", "revise", "accept", "repair", "redesign", "block"}:
            raise ContractError("disposition", "UNKNOWN_VALUE")
        if finding["finding_id"] in seen:
            raise ContractError("finding_id", "DUPLICATE_ID")
        seen.add(finding["finding_id"])
    decision = value.get("decision")
    stage = branch.get("stage")
    dispositions = {finding["disposition"] for finding in findings}
    if stage == "design" and branch["node_key"] not in {"tech_lead"}:
        if decision == "APPROVE" and dispositions - {"approve"}:
            raise ContractError("decision", "DECISION_FINDING_MISMATCH")
        if decision == "REVISE" and "revise" not in dispositions:
            raise ContractError("decision", "REVISION_FINDING_REQUIRED")
        if decision == "BLOCK" and "block" not in dispositions:
            raise ContractError("decision", "BLOCK_FINDING_REQUIRED")
    elif stage == "delivery":
        if decision == "APPROVE" and dispositions - {"accept"}:
            raise ContractError("decision", "DECISION_FINDING_MISMATCH")
        if decision == "REVISE" and not dispositions.intersection({"repair", "redesign"}):
            raise ContractError("decision", "REVISION_FINDING_REQUIRED")
        if decision == "BLOCK" and "block" not in dispositions:
            raise ContractError("decision", "BLOCK_FINDING_REQUIRED")
    elif branch["node_key"] == "senior_engineer":
        if decision == "IMPLEMENTED" and dispositions - {"accept"}:
            raise ContractError("decision", "DECISION_FINDING_MISMATCH")
        if decision == "REDESIGN_REQUIRED":
            if dispositions != {"redesign"}:
                raise ContractError("decision", "REDESIGN_FINDING_REQUIRED")
    elif findings:
        raise ContractError("findings", "FINDINGS_NOT_ALLOWED")
    return dict(value)
