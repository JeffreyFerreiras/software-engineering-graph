"""Verified authoritative artifact resolution and persistence."""

import fnmatch
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Optional, Sequence

from .config import ENGINE_ARTIFACT_MAX
from .contracts import ContractError, digest, lexical_relative, safe_file_snapshot, validate_ref
from .ids import canonical_bytes, sha256_bytes


@dataclass(frozen=True)
class VerifiedArtifact:
    ref: str
    kind: str
    sha256: str
    size_bytes: int
    source_type: str
    source_path: Optional[str]
    content_json: Optional[str]
    device: Optional[int]
    inode: Optional[int]

    def as_input(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def _within_roots(relative: str, roots: Sequence[str]) -> bool:
    path = PurePosixPath(relative)
    for configured in roots:
        root = PurePosixPath(configured.rstrip("/"))
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def policy_path_allowed(relative: str, policy: Mapping[str, Any]) -> None:
    lexical_relative(relative, "artifact_ref")
    normalized = relative.replace("\\", "/")
    for pattern in policy["denied_patterns"]:
        if fnmatch.fnmatchcase(normalized.lower(), pattern.lower()) or PurePosixPath(normalized.lower()).match(pattern.lower()):
            raise ContractError("artifact_ref", "SENSITIVE_PATH")


def _kind_policy(kind: str, policy: Mapping[str, Any]) -> Mapping[str, Any]:
    config = policy["artifact_kinds"].get(kind)
    if not isinstance(config, dict):
        raise ContractError("artifact_kind", "UNKNOWN_ARTIFACT_KIND")
    return config


def artifact_size_limit(kind: str, policy: Mapping[str, Any]) -> int:
    kind_policy = _kind_policy(kind, policy)
    engine_maximum = ENGINE_ARTIFACT_MAX.get(kind)
    if engine_maximum is None:
        raise ContractError("artifact_kind", "UNKNOWN_ARTIFACT_KIND")
    return min(
        int(kind_policy["max_bytes"]), int(policy["limits"]["artifact_bytes"]),
        engine_maximum, 4 * 1024 * 1024,
    )


def enforce_artifact_size(kind: str, size_bytes: Any, policy: Mapping[str, Any]) -> None:
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise ContractError("artifact_ref", "INVALID_SIZE")
    if size_bytes > artifact_size_limit(kind, policy):
        raise ContractError("artifact_ref", "FILE_TOO_LARGE")


def resolve_reference(
    ref: str,
    separate_digest: str,
    kind: str,
    repo: Path,
    skill_root: Path,
    policy: Mapping[str, Any],
    connection: Optional[sqlite3.Connection] = None,
) -> VerifiedArtifact:
    validate_ref(ref, "artifact_ref", content_required=True)
    expected = digest(separate_digest, "artifact_sha256")
    prefix, body = ref.split(":", 1)
    identity, marker, embedded = body.partition("#sha256=")
    if not marker or embedded != expected:
        raise ContractError("artifact_ref", "DIGEST_DISAGREEMENT")
    kind_policy = _kind_policy(kind, policy)
    maximum = artifact_size_limit(kind, policy)
    if prefix == "ledger":
        if connection is None:
            raise ContractError("artifact_ref", "LEDGER_CONTEXT_REQUIRED")
        row = connection.execute(
            "SELECT * FROM artifacts WHERE ref=? AND sha256=? AND immutable=1", (ref, expected)
        ).fetchone()
        if row is None or row["kind"] != kind:
            raise ContractError("artifact_ref", "LEDGER_ARTIFACT_NOT_FOUND")
        enforce_artifact_size(row["kind"], row["size_bytes"], policy)
        return VerifiedArtifact(
            row["ref"], row["kind"], row["sha256"], row["size_bytes"], row["source_type"],
            row["source_path"], row["content_json"], row["device"], row["inode"],
        )
    if prefix == "repo":
        relative = lexical_relative(identity, "artifact_ref")
        policy_path_allowed(relative, policy)
        if not _within_roots(relative, policy["artifact_roots"]["repo"]):
            raise ContractError("artifact_ref", "OUTSIDE_ALLOWED_ROOT")
        path = repo / relative
        roots = [repo / root for root in policy["artifact_roots"]["repo"]]
    elif prefix == "profile" and identity.startswith("software-engineering-graph/"):
        relative = lexical_relative(identity[len("software-engineering-graph/"):], "artifact_ref")
        policy_path_allowed(relative, policy)
        if not _within_roots(relative, policy["artifact_roots"]["profile"]):
            raise ContractError("artifact_ref", "OUTSIDE_ALLOWED_ROOT")
        path = skill_root / relative
        roots = [skill_root / root for root in policy["artifact_roots"]["profile"]]
    else:
        raise ContractError("artifact_ref", "AUTHORITATIVE_REF_REQUIRED")
    suffix = path.suffix.lower()
    if suffix not in set(kind_policy["extensions"]):
        raise ContractError("artifact_ref", "ARTIFACT_TYPE_MISMATCH")
    snapshot = safe_file_snapshot(path, roots, maximum)
    if snapshot.digest != expected:
        raise ContractError("artifact_ref", "INPUT_DIGEST_MISMATCH")
    return VerifiedArtifact(
        ref, kind, expected, snapshot.size, prefix, str(snapshot.path), None,
        snapshot.identity[0], snapshot.identity[1],
    )


def resolve_unhashed_reference(
    ref: str,
    kind: str,
    repo: Path,
    skill_root: Path,
    policy: Mapping[str, Any],
) -> VerifiedArtifact:
    validate_ref(ref, "artifact_ref", content_required=False)
    prefix, body = ref.split(":", 1)
    if "#" in body:
        raise ContractError("artifact_ref", "UNEXPECTED_DIGEST")
    kind_policy = _kind_policy(kind, policy)
    maximum = artifact_size_limit(kind, policy)
    if prefix == "repo":
        relative = lexical_relative(body, "artifact_ref")
        policy_path_allowed(relative, policy)
        if not _within_roots(relative, policy["artifact_roots"]["repo"]):
            raise ContractError("artifact_ref", "OUTSIDE_ALLOWED_ROOT")
        path = repo / relative
        roots = [repo / root for root in policy["artifact_roots"]["repo"]]
        normalized_prefix = "repo:"
    elif prefix == "profile" and body.startswith("software-engineering-graph/"):
        relative = lexical_relative(body[len("software-engineering-graph/"):], "artifact_ref")
        policy_path_allowed(relative, policy)
        if not _within_roots(relative, policy["artifact_roots"]["profile"]):
            raise ContractError("artifact_ref", "OUTSIDE_ALLOWED_ROOT")
        path = skill_root / relative
        roots = [skill_root / root for root in policy["artifact_roots"]["profile"]]
        normalized_prefix = "profile:software-engineering-graph/"
    else:
        raise ContractError("artifact_ref", "AUTHORITATIVE_REF_REQUIRED")
    if path.suffix.lower() not in set(kind_policy["extensions"]):
        raise ContractError("artifact_ref", "ARTIFACT_TYPE_MISMATCH")
    snapshot = safe_file_snapshot(path, roots, maximum)
    normalized_ref = normalized_prefix + relative + "#sha256=" + snapshot.digest
    return VerifiedArtifact(
        normalized_ref, kind, snapshot.digest, snapshot.size, prefix, str(snapshot.path), None,
        snapshot.identity[0], snapshot.identity[1],
    )


def canonical_ledger_artifact(identifier: str, kind: str, content: Mapping[str, Any]) -> VerifiedArtifact:
    serialized = canonical_bytes(content)
    artifact_digest = sha256_bytes(serialized)
    return VerifiedArtifact(
        f"ledger:{identifier}#sha256={artifact_digest}", kind, artifact_digest,
        len(serialized), "ledger", None, serialized.decode("utf-8"), None, None,
    )


def persist_artifact(connection: sqlite3.Connection, run_id: str, artifact: VerifiedArtifact) -> None:
    existing = connection.execute("SELECT * FROM artifacts WHERE ref=?", (artifact.ref,)).fetchone()
    values = (
        artifact.ref, run_id, artifact.kind, artifact.sha256, artifact.size_bytes,
        artifact.source_type, artifact.source_path, artifact.content_json,
        artifact.device, artifact.inode, 1,
    )
    if existing is None:
        connection.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)", values)
        return
    comparison = (
        existing["run_id"], existing["kind"], existing["sha256"], existing["size_bytes"],
        existing["source_type"], existing["source_path"], existing["content_json"],
        existing["device"], existing["inode"], existing["immutable"],
    )
    if comparison != values[1:]:
        raise ContractError("artifact_ref", "ARTIFACT_CONFLICT")


def reverify_artifact(
    connection: sqlite3.Connection,
    artifact: Mapping[str, Any],
    repo: Path,
    skill_root: Path,
    policy: Mapping[str, Any],
) -> None:
    enforce_artifact_size(artifact["kind"], artifact["size_bytes"], policy)
    if artifact["source_type"] == "ledger":
        if artifact["content_json"] is None:
            raise ContractError("artifact_ref", "LEDGER_CONTENT_MISSING")
        try:
            value = json.loads(artifact["content_json"])
        except json.JSONDecodeError:
            raise ContractError("artifact_ref", "LEDGER_CONTENT_INVALID")
        canonical = canonical_bytes(value)
        if sha256_bytes(canonical) != artifact["sha256"] or len(canonical) != artifact["size_bytes"]:
            raise ContractError("artifact_ref", "LEDGER_DIGEST_MISMATCH")
        return
    verified = resolve_reference(
        artifact["ref"], artifact["sha256"], artifact["kind"], repo, skill_root, policy, connection
    )
    if (verified.device, verified.inode) != (artifact["device"], artifact["inode"]):
        raise ContractError("artifact_ref", "ARTIFACT_IDENTITY_MISMATCH")
