"""Local, provider-neutral execution and verification of required checks."""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .contracts import ContractError, bounded_string, digest, opaque, require_keys
from .ids import canonical_bytes, sha256_bytes
from .state import StateError, current_actor, current_host_identity, utc_now


def repository_worktree_digest(repo: Path) -> str:
    """Return a compact digest of the Git state used by a local check."""
    values: Dict[str, Any] = {"git": True}
    for name, arguments in (
        ("head", ["rev-parse", "HEAD"]),
        ("status", ["status", "--porcelain=v1"]),
        ("diff", ["diff", "--binary", "HEAD", "--"]),
    ):
        try:
            result = subprocess.run(
                ["git"] + arguments,
                cwd=str(repo),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            values["git"] = False
            values[name] = None
            continue
        if result.returncode != 0:
            values["git"] = False
            values[name] = None
        elif name == "diff":
            values[name] = sha256_bytes(result.stdout)
        else:
            values[name] = result.stdout.decode("utf-8", errors="replace")
    return sha256_bytes(canonical_bytes(values))


def configured_check(policy: Mapping[str, Any], check_id: str) -> Mapping[str, Any]:
    check = policy.get("required_checks", {}).get(check_id)
    if not isinstance(check, dict):
        raise StateError("UNKNOWN_CHECK")
    if not isinstance(check.get("argv"), list) or not check["argv"]:
        raise StateError("CHECK_COMMAND_NOT_CONFIGURED")
    return check


def run_check(
    repo: Path,
    run_id: str,
    check_id: str,
    command_id: str,
    argv: Sequence[str],
    timeout_seconds: int,
) -> Dict[str, Any]:
    started_at = utc_now()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
        exit_code = int(completed.returncode)
        timed_out = False
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        exit_code = 124
        timed_out = True
        stdout = error.stdout or b""
        stderr = error.stderr or b""
    except OSError as error:
        exit_code = 127
        timed_out = False
        stdout = b""
        stderr = str(error).encode("utf-8", errors="replace")
    finished_at = utc_now()
    return {
        "schema_version": 1,
        "kind": "check_receipt",
        "run_id": opaque(run_id, "run_id"),
        "check_id": opaque(check_id, "check_id"),
        "command_id": opaque(command_id, "command_id"),
        "argv": [bounded_string(item, "argv", 1024) for item in argv],
        "outcome": "PASS" if exit_code == 0 else "FAIL",
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_sha256": sha256_bytes(stdout),
        "stderr_sha256": sha256_bytes(stderr),
        "repo_worktree_sha256": repository_worktree_digest(repo),
        "started_at": started_at,
        "finished_at": finished_at,
        "producer_actor": current_actor(),
        "producer_host_identity": current_host_identity(),
    }


def validate_check_receipt(
    receipt: Any,
    run_id: str,
    check_id: str,
    expected: Mapping[str, Any],
    repo: Path,
) -> Dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ContractError("check_receipt", "INVALID_OBJECT")
    allowed = {
        "schema_version", "kind", "run_id", "check_id", "command_id", "argv", "outcome",
        "exit_code", "timed_out", "stdout_sha256", "stderr_sha256", "repo_worktree_sha256",
        "started_at", "finished_at", "producer_actor", "producer_host_identity",
    }
    require_keys(receipt, allowed, allowed, "check_receipt")
    if receipt["schema_version"] != 1 or receipt["kind"] != "check_receipt":
        raise ContractError("check_receipt", "SCHEMA_MISMATCH")
    if receipt["run_id"] != run_id or receipt["check_id"] != check_id:
        raise ContractError("check_receipt", "IDENTITY_MISMATCH")
    if receipt["command_id"] != expected["command_id"]:
        raise ContractError("command_id", "COMMAND_MISMATCH")
    if receipt.get("argv") != expected.get("argv"):
        raise ContractError("argv", "COMMAND_MISMATCH")
    if receipt["outcome"] not in {"PASS", "FAIL"} or not isinstance(receipt["exit_code"], int) or isinstance(receipt["exit_code"], bool):
        raise ContractError("check_receipt", "OUTCOME_INVALID")
    if receipt["outcome"] == "PASS" and receipt["exit_code"] != 0:
        raise ContractError("outcome", "OUTCOME_MISMATCH")
    if receipt["outcome"] == "FAIL" and receipt["exit_code"] == 0:
        raise ContractError("outcome", "OUTCOME_MISMATCH")
    if not isinstance(receipt["timed_out"], bool):
        raise ContractError("timed_out", "INVALID_TYPE")
    if receipt["timed_out"] != (receipt["exit_code"] == 124):
        raise ContractError("timed_out", "OUTCOME_MISMATCH")
    for field in ("stdout_sha256", "stderr_sha256", "repo_worktree_sha256"):
        digest(receipt[field], "check_receipt." + field)
    for field in ("started_at", "finished_at", "producer_actor", "producer_host_identity"):
        bounded_string(receipt[field], "check_receipt." + field, 256)
    try:
        started = datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00"))
        finished = datetime.fromisoformat(receipt["finished_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ContractError("check_receipt", "TIMESTAMP_INVALID")
    if finished < started:
        raise ContractError("check_receipt", "TIMESTAMP_INVALID")
    if receipt["producer_actor"] != current_actor() or receipt["producer_host_identity"] != current_host_identity():
        raise ContractError("check_receipt", "PRODUCER_MISMATCH")
    if receipt["repo_worktree_sha256"] != repository_worktree_digest(repo):
        raise ContractError("repo_worktree_sha256", "REPOSITORY_CHANGED")
    return dict(receipt)
