"""Command-line contracts for the graph control ledger."""

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .config import load_policy
from .contracts import (
    ContractError, Snapshot, authoritative_task_subset, digest, opaque, require_keys,
    safe_json_snapshot, validate_impact_map, validate_ref, validate_result_manifest,
    validate_task_brief,
)
from .evidence import (
    VerifiedArtifact, canonical_ledger_artifact, enforce_artifact_size, persist_artifact,
    resolve_reference, resolve_unhashed_reference,
)
from .ids import canonical_bytes, sha256_bytes
from .planner import (
    JoinSpec, NodeSpec, bootstrap, branch_id, closure_join, collection_join,
    consolidation_join, consolidation_node, delivery_review_nodes, design_review_nodes,
    envelope, implementation_node, initial_route_nodes, join_id, next_join_for_success,
    revised_design_node,
)
from .state import StateError, StateStore, utc_now
from .validator import (
    canonical_collection_members, join_members, validate_consolidation_manifest,
    validate_join, verify_resume, verify_semantic_state,
)


EXIT_CODES = {"success": 0, "not_ready": 2, "blocked": 3, "invalid": 4, "conflict": 5}


def _json_result(ok: bool, code: str, run_id: Optional[str], revision: Optional[int], **data: Any) -> Dict[str, Any]:
    result = {"schema_version": 1, "ok": ok, "code": code, "run_id": run_id, "state_revision": revision}
    result.update(data)
    return result


def _emit(result: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")


def _task_roots(repo: Path, policy: Mapping[str, Any]) -> List[Path]:
    return [(repo / item).absolute() for item in policy["artifact_roots"]["repo"]]


def _node_row(spec: NodeSpec, graph_envelope: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "branch_id": graph_envelope["branch_id"],
        "node_instance_id": graph_envelope["node_instance_id"],
        "node_key": spec.key,
        "role": spec.role,
        "stage": spec.stage,
        "generation": spec.generation,
        "mandatory": spec.mandatory,
        "specialist_tag": spec.specialist_tag,
        "status": graph_envelope["status"],
        "retry_count": graph_envelope["retry_count"],
        "max_retries": graph_envelope["max_retries"],
        "envelope_json": json.dumps(graph_envelope, sort_keys=True, separators=(",", ":")),
    }


def _task_input(run: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "task_brief", "ref": run["task_ref"], "sha256": run["task_digest"],
        "size_bytes": Path(run["task_path"]).stat().st_size,
    }


def _ledger_input(connection: sqlite3.Connection, source: Mapping[str, Any]) -> Dict[str, Any]:
    result = json.loads(source["result_json"])
    data = canonical_bytes(result)
    ref = "ledger:" + source["branch_id"] + "#sha256=" + source["result_digest"]
    artifact = connection.execute("SELECT * FROM artifacts WHERE ref=?", (ref,)).fetchone()
    if artifact is None or artifact["sha256"] != source["result_digest"]:
        raise StateError("INPUT_ARTIFACT_INVALID")
    return {
        "kind": artifact["kind"],
        "ref": ref,
        "sha256": source["result_digest"],
        "size_bytes": len(data),
    }


def _artifact_input(connection: sqlite3.Connection, artifact_ref: Mapping[str, Any]) -> Dict[str, Any]:
    row = connection.execute("SELECT * FROM artifacts WHERE ref=?", (artifact_ref["ref"],)).fetchone()
    if row is None or row["kind"] != artifact_ref["kind"] or row["sha256"] != artifact_ref["sha256"]:
        raise StateError("INPUT_ARTIFACT_INVALID")
    return {"kind": row["kind"], "ref": row["ref"], "sha256": row["sha256"], "size_bytes": row["size_bytes"]}


def _context_inputs(
    connection: sqlite3.Connection,
    run: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    include_design: bool = False,
    include_implementation: bool = False,
) -> List[Dict[str, Any]]:
    inputs: List[Dict[str, Any]] = [_task_input(run)]
    for source in sources:
        if source["result_json"]:
            inputs.append(_ledger_input(connection, source))
            result = json.loads(source["result_json"])
            if isinstance(result.get("artifact_ref"), dict):
                inputs.append(_artifact_input(connection, result["artifact_ref"]))
    for node_key, enabled in (("tech_lead", include_design), ("senior_engineer", include_implementation)):
        if not enabled:
            continue
        context_node = connection.execute(
            "SELECT * FROM nodes WHERE run_id=? AND node_key=? AND status='succeeded' ORDER BY generation DESC LIMIT 1",
            (run["run_id"], node_key),
        ).fetchone()
        if context_node:
            result = json.loads(context_node["result_json"])
            if isinstance(result.get("artifact_ref"), dict):
                inputs.append(_artifact_input(connection, result["artifact_ref"]))
            inputs.append(_ledger_input(connection, context_node))
    unique = {item["ref"]: item for item in inputs}
    return sorted(unique.values(), key=lambda item: (item["kind"], item["ref"]))


def _insert_spec(
    store: StateStore, connection: sqlite3.Connection, run: Mapping[str, Any], policy: Mapping[str, Any],
    task: Mapping[str, Any], spec: NodeSpec, inputs: Sequence[Mapping[str, Any]], status: str = "ready",
) -> Dict[str, Any]:
    graph_envelope = envelope(run["run_id"], run["policy_digest"], policy, task, spec, status, inputs)
    row = _node_row(spec, graph_envelope)
    store._insert_node(connection, run["run_id"], row)
    return row


def _insert_join(
    store: StateStore, connection: sqlite3.Connection, run: Mapping[str, Any], spec: JoinSpec,
) -> Dict[str, Any]:
    row = {
        "join_id": join_id(run["run_id"], run["policy_digest"], spec),
        "join_key": spec.key,
        "kind": spec.kind,
        "stage": spec.stage,
        "generation": spec.generation,
    }
    members = []
    for member in spec.members:
        bid = branch_id(run["run_id"], run["policy_digest"], member)
        members.append({"branch_id": bid, "mandatory": member.mandatory})
    store.insert_join(connection, run["run_id"], row, members)
    return row


def _run_context(connection: sqlite3.Connection, run_id: str) -> Tuple[sqlite3.Row, Dict[str, Any], Dict[str, Any]]:
    run = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None:
        raise StateError("RUN_NOT_FOUND")
    return run, json.loads(run["policy_json"]), json.loads(run["task_json"])


def _manifest_snapshot(store: StateStore, policy: Mapping[str, Any], run_id: str, path: str, maximum: int = 256 * 1024) -> Snapshot:
    inbox = store.inbox_root(policy["repository_id"], run_id)
    manifest_path = Path(path)
    store.verify_inbox_manifest(policy["repository_id"], run_id, manifest_path)
    return safe_json_snapshot(manifest_path, [inbox], min(maximum, int(policy["limits"]["manifest_bytes"])))


def _validate_control_manifest(value: Any, kind: str, run_id: str, branch_id: Optional[str], reason_code: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("evidence_manifest", "INVALID_OBJECT")
    required = {"schema_version", "kind", "run_id", "reason_code", "evidence"}
    if branch_id is not None:
        required.add("branch_id")
    require_keys(value, required, required, "evidence_manifest")
    if value["schema_version"] != 1 or value["kind"] != kind or value["run_id"] != run_id or value["reason_code"] != reason_code:
        raise ContractError("evidence_manifest", "CONTROL_MANIFEST_MISMATCH")
    if branch_id is not None and value["branch_id"] != branch_id:
        raise ContractError("evidence_manifest", "CONTROL_MANIFEST_MISMATCH")
    if not isinstance(value["evidence"], list):
        raise ContractError("evidence", "INVALID_LIST")
    normalized = dict(value)
    return normalized


def command_init(args: argparse.Namespace, repo: Path, policy: Mapping[str, Any], policy_snapshot: Snapshot, store: StateStore) -> Dict[str, Any]:
    run_id, op_id = opaque(args.run_id, "run_id"), opaque(args.op_id, "op_id")
    task_snapshot = safe_json_snapshot(
        Path(args.task_brief), _task_roots(repo, policy), policy["artifact_kinds"]["task_brief"]["max_bytes"]
    )
    full_task = validate_task_brief(task_snapshot.parsed, policy_snapshot.digest, policy)
    task = authoritative_task_subset(full_task)
    skill_root = Path(__file__).resolve().parents[1]
    verified_evidence = [
        resolve_unhashed_reference(ref, "acceptance_evidence", repo, skill_root, policy)
        for ref in full_task["evidence_paths"]
    ]
    task["evidence_paths"] = sorted(artifact.ref for artifact in verified_evidence)
    spec = bootstrap(policy)
    task_ref = "repo:" + task_snapshot.path.relative_to(repo.absolute()).as_posix() + "#sha256=" + task_snapshot.digest
    task_artifact = VerifiedArtifact(
        task_ref, "task_brief", task_snapshot.digest, task_snapshot.size, "repo",
        str(task_snapshot.path), None, task_snapshot.identity[0], task_snapshot.identity[1],
    )
    graph_envelope = envelope(
        run_id, policy_snapshot.digest, policy, task, spec, "ready",
        [{"kind": "task_brief", "ref": task_ref, "sha256": task_snapshot.digest, "size_bytes": task_snapshot.size}],
    )
    request = {
        "command": "init", "run_id": run_id, "op_id": op_id,
        "policy_digest": policy_snapshot.digest, "task_digest": task_snapshot.digest,
        "evidence_digests": sorted((artifact.ref, artifact.sha256) for artifact in verified_evidence),
        "ack_permissions": bool(args.ack_degraded_permissions),
        "ack_durability": bool(args.ack_degraded_durability),
    }
    request_digest = sha256_bytes(canonical_bytes(request))
    return store.initialize(
        repo, policy, policy_snapshot.digest, task, task_snapshot.path, task_snapshot.digest,
        run_id, op_id, request_digest, bool(args.ack_degraded_permissions),
        bool(args.ack_degraded_durability), _node_row(spec, graph_envelope),
        task_ref, [asdict(task_artifact)] + [asdict(artifact) for artifact in verified_evidence],
    )


def _record_branch_result(
    args: argparse.Namespace, connection: sqlite3.Connection, run: sqlite3.Row,
    policy: Mapping[str, Any], task: Mapping[str, Any], store: StateStore,
) -> Dict[str, Any]:
    snapshot = _manifest_snapshot(store, policy, run["run_id"], args.result_manifest)
    request = {"command": "record.branch-result", "branch_id": args.branch_id, "manifest_digest": snapshot.digest}

    def action(conn: sqlite3.Connection, current: sqlite3.Row, revision: int) -> Dict[str, Any]:
        current_branch = conn.execute("SELECT * FROM nodes WHERE branch_id=?", (args.branch_id,)).fetchone()
        if current_branch is None:
            raise StateError("BRANCH_NOT_FOUND")
        if current_branch["status"] != "running":
            raise StateError("INVALID_BRANCH_TRANSITION")
        env = json.loads(current_branch["envelope_json"])
        branch_contract = dict(current_branch)
        branch_contract["run_id"] = current["run_id"]
        branch_contract["output_contract"] = env["output_contract"]
        repo_path = Path(current["repository_path"])
        skill_root = Path(__file__).resolve().parents[1]
        external_artifact = None
        verified_evidence = []
        if current_branch["node_key"] == "impact_mapper" and snapshot.parsed.get("status") != "failed":
            impact = validate_impact_map(snapshot.parsed, task, policy)
            normalized_refs = []
            for reference in impact["evidence_refs"]:
                if "#sha256=" in reference:
                    embedded = reference.rsplit("#sha256=", 1)[1]
                    verified = resolve_reference(reference, embedded, "finding", repo_path, skill_root, policy, conn)
                else:
                    verified = resolve_unhashed_reference(reference, "finding", repo_path, skill_root, policy)
                persist_artifact(conn, current["run_id"], verified)
                normalized_refs.append(verified.ref)
            impact["evidence_refs"] = sorted(normalized_refs)
            manifest = impact
            result_status, output_kind, decision, artifact, evidence, failure = "succeeded", "impact_map", None, None, [], None
            conn.execute(
                "UPDATE runs SET status='active',selected_route=?,selected_tags_json=? WHERE run_id=?",
                (impact["route_label"], json.dumps(impact["impact_tags"]), current["run_id"]),
            )
            fresh_run = conn.execute("SELECT * FROM runs WHERE run_id=?", (current["run_id"],)).fetchone()
            inputs = _context_inputs(conn, fresh_run, [])
            for spec in initial_route_nodes(policy, impact["route_label"]):
                _insert_spec(store, conn, fresh_run, policy, task, spec, inputs)
        else:
            validated = validate_result_manifest(snapshot.parsed, branch_contract)
            manifest = validated
            result_status = validated["status"]
            output_kind = validated["output_kind"]
            decision = validated.get("decision")
            artifact = validated.get("artifact_ref")
            evidence = validated.get("evidence", [])
            failure = validated.get("failure_code")
            if result_status == "succeeded" and isinstance(artifact, dict):
                external_artifact = resolve_reference(
                    artifact["ref"], artifact["sha256"], artifact["kind"],
                    repo_path, skill_root, policy, conn,
                )
                persist_artifact(conn, current["run_id"], external_artifact)
                artifact = {"kind": external_artifact.kind, "ref": external_artifact.ref, "sha256": external_artifact.sha256}
                manifest["artifact_ref"] = artifact
            for item in evidence:
                verified = resolve_reference(
                    item["ref"], item["sha256"], item["kind"], repo_path, skill_root, policy, conn,
                )
                persist_artifact(conn, current["run_id"], verified)
                verified_evidence.append({"kind": verified.kind, "ref": verified.ref, "sha256": verified.sha256})
            evidence = sorted(verified_evidence, key=lambda item: (item["kind"], item["ref"]))
            manifest["evidence"] = evidence
        redesign_required = (
            current_branch["node_key"] == "senior_engineer"
            and decision == "REDESIGN_REQUIRED"
        )
        if (result_status == "succeeded" and artifact is None and not redesign_required
                and not env["output_contract"].get("artifact_required", True)):
            substantive_artifact = canonical_ledger_artifact(
                current_branch["branch_id"] + "-output", output_kind, manifest
            )
            persist_artifact(conn, current["run_id"], substantive_artifact)
            artifact = {
                "kind": substantive_artifact.kind,
                "ref": substantive_artifact.ref,
                "sha256": substantive_artifact.sha256,
            }
        wrapper_kind = "branch_result" if result_status == "succeeded" else "failure"
        ledger_artifact = canonical_ledger_artifact(current_branch["branch_id"], wrapper_kind, manifest)
        persist_artifact(conn, current["run_id"], ledger_artifact)
        if artifact is None and result_status != "succeeded":
            artifact = {"kind": ledger_artifact.kind, "ref": ledger_artifact.ref, "sha256": ledger_artifact.sha256}
        env.update({
            "status": result_status, "artifact_ref": artifact, "evidence": evidence,
            "decision": decision, "failure_code": failure, "finished_at": utc_now(),
        })
        conn.execute(
            """UPDATE nodes SET status=?,envelope_json=?,result_json=?,result_digest=?,failure_code=?,finished_at=?
            WHERE branch_id=?""",
            (result_status, json.dumps(env, sort_keys=True), ledger_artifact.content_json,
             ledger_artifact.sha256, failure, env["finished_at"], args.branch_id),
        )
        if result_status == "succeeded" and current_branch["node_key"] != "impact_mapper":
            updated = conn.execute("SELECT * FROM nodes WHERE branch_id=?", (args.branch_id,)).fetchone()
            route = current["selected_route"]
            join_spec = next_join_for_success(policy, route, json.loads(current["selected_tags_json"] or "[]"), updated)
            if current_branch["node_key"] == "senior_engineer" and decision == "REDESIGN_REQUIRED":
                join_spec = collection_join("delivery", current_branch["generation"], [NodeSpec(
                    updated["node_key"], updated["role"], updated["stage"], updated["generation"],
                    bool(updated["mandatory"]), updated["specialist_tag"],
                )])
            if join_spec:
                _insert_join(store, conn, current, join_spec)
        return {"code": "BRANCH_RESULT_RECORDED", "branch_id": args.branch_id, "branch_status": result_status}

    return store.mutate(connection, run["run_id"], opaque(args.op_id, "op_id"), request, action)


def _record_control(
    args: argparse.Namespace, connection: sqlite3.Connection, run: sqlite3.Row,
    policy: Mapping[str, Any], task: Mapping[str, Any], store: StateStore,
) -> Dict[str, Any]:
    kind = args.record_kind
    op_id = opaque(args.op_id, "op_id")
    request: Dict[str, Any] = {"command": "record." + kind}
    if hasattr(args, "branch_id"):
        request["branch_id"] = args.branch_id
    if kind in {"timeout", "skip"}:
        snapshot = _manifest_snapshot(store, policy, run["run_id"], args.evidence_manifest, 128 * 1024)
        request.update({"reason_code": opaque(args.reason_code, "reason_code"), "evidence_digest": snapshot.digest})
    elif kind == "retry":
        request["reason_code"] = opaque(args.reason_code, "reason_code")
    elif kind == "approval":
        request.update({
            "approval_id": opaque(args.approval_id, "approval_id"),
            "scope_ref": validate_ref(args.scope_ref, "scope_ref", content_required=True), "decision": args.decision,
            "authority_ref": validate_ref(args.authority_ref, "authority_ref"),
            "artifact_sha256": digest(args.artifact_sha256, "artifact_sha256"),
        })
    elif kind == "budget-use":
        if args.amount <= 0:
            raise ContractError("amount", "POSITIVE_INTEGER_REQUIRED")
        request.update({"budget_id": opaque(args.budget_id, "budget_id"), "amount": args.amount, "source_branch_id": opaque(args.source_branch_id, "source_branch_id")})
    elif kind in {"acceptance-evidence", "check-evidence"}:
        request.update({
            "artifact_ref": validate_ref(args.artifact_ref, "artifact_ref", content_required=True),
            "artifact_sha256": digest(args.artifact_sha256, "artifact_sha256"),
        })
        if kind == "acceptance-evidence":
            request["criterion_id"] = opaque(args.criterion_id, "criterion_id")
        else:
            request.update({"check_id": opaque(args.check_id, "check_id"), "outcome": args.outcome})

    def action(conn: sqlite3.Connection, current: sqlite3.Row, revision: int) -> Dict[str, Any]:
        if kind in {"timeout", "skip", "retry"}:
            branch = conn.execute("SELECT * FROM nodes WHERE branch_id=?", (args.branch_id,)).fetchone()
            if not branch:
                raise StateError("BRANCH_NOT_FOUND")
            sealed = conn.execute(
                "SELECT 1 FROM join_members jm JOIN joins j ON j.join_id=jm.join_id WHERE jm.branch_id=? AND j.status='sealed'",
                (args.branch_id,),
            ).fetchone()
            if sealed:
                raise StateError("JOIN_ALREADY_SEALED")
            env = json.loads(branch["envelope_json"])
            if kind == "timeout":
                if branch["status"] != "running":
                    raise StateError("INVALID_BRANCH_TRANSITION")
                new_status = "timed_out"
            elif kind == "skip":
                if branch["mandatory"] or branch["status"] not in {"pending", "ready"}:
                    raise StateError("INVALID_BRANCH_TRANSITION")
                new_status = "skipped"
            else:
                if branch["status"] not in {"failed", "timed_out"}:
                    raise StateError("INVALID_BRANCH_TRANSITION")
                if branch["retry_count"] >= branch["max_retries"]:
                    if branch["mandatory"]:
                        conn.execute("UPDATE runs SET status='blocked',blocked_reason='RETRY_LIMIT' WHERE run_id=?", (current["run_id"],))
                    return {"code": "GRAPH_BLOCKED", "status": "blocked", "reason": "RETRY_LIMIT"}
                new_status = "ready"
                env["retry_count"] += 1
                env["started_at"] = env["finished_at"] = None
                env.update({"artifact_ref": None, "evidence": [], "decision": None, "failure_code": None})
                conn.execute(
                    "UPDATE nodes SET retry_count=retry_count+1,result_json=NULL,result_digest=NULL,failure_code=NULL,reason_code=NULL,finished_at=NULL WHERE branch_id=?",
                    (args.branch_id,),
                )
            env["status"] = new_status
            if kind != "retry":
                manifest = _validate_control_manifest(
                    snapshot.parsed, kind, current["run_id"], branch["branch_id"], request["reason_code"]
                )
                verified_items = []
                for item in manifest["evidence"]:
                    if not isinstance(item, dict):
                        raise ContractError("evidence", "INVALID_OBJECT")
                    require_keys(item, {"kind", "ref", "sha256"}, {"kind", "ref", "sha256"}, "evidence")
                    verified = resolve_reference(
                        item["ref"], item["sha256"], item["kind"], Path(current["repository_path"]),
                        Path(__file__).resolve().parents[1], policy, conn,
                    )
                    persist_artifact(conn, current["run_id"], verified)
                    verified_items.append({"kind": verified.kind, "ref": verified.ref, "sha256": verified.sha256})
                manifest["evidence"] = sorted(verified_items, key=lambda item: (item["kind"], item["ref"]))
                control_artifact = canonical_ledger_artifact("evidence-" + op_id, "evidence_manifest", manifest)
                persist_artifact(conn, current["run_id"], control_artifact)
                result = {
                    "schema_version": 1, "kind": kind, "run_id": current["run_id"],
                    "branch_id": branch["branch_id"], "reason_code": request["reason_code"],
                    "evidence_manifest_ref": control_artifact.ref,
                }
                branch_artifact = canonical_ledger_artifact(branch["branch_id"], kind, result)
                persist_artifact(conn, current["run_id"], branch_artifact)
                env["artifact_ref"] = {"kind": branch_artifact.kind, "ref": branch_artifact.ref, "sha256": branch_artifact.sha256}
                env["evidence"] = verified_items + [{"kind": control_artifact.kind, "ref": control_artifact.ref, "sha256": control_artifact.sha256}]
                env["finished_at"] = utc_now()
                conn.execute(
                    "UPDATE nodes SET status=?,reason_code=?,envelope_json=?,result_json=?,result_digest=?,finished_at=? WHERE branch_id=?",
                    (new_status, args.reason_code, json.dumps(env, sort_keys=True), branch_artifact.content_json,
                     branch_artifact.sha256, env.get("finished_at"), args.branch_id),
                )
            else:
                conn.execute(
                    "UPDATE nodes SET status=?,envelope_json=? WHERE branch_id=?",
                    (new_status, json.dumps(env, sort_keys=True), args.branch_id),
                )
            return {"code": kind.upper().replace("-", "_") + "_RECORDED", "branch_id": args.branch_id, "branch_status": new_status}
        if kind == "approval":
            if request["approval_id"] not in set(task["required_human_decisions"]):
                raise StateError("UNEXPECTED_APPROVAL")
            verified = resolve_reference(
                request["scope_ref"], request["artifact_sha256"], "acceptance_evidence",
                Path(current["repository_path"]), Path(__file__).resolve().parents[1], policy, conn,
            )
            persist_artifact(conn, current["run_id"], verified)
            existing = conn.execute("SELECT * FROM approvals WHERE run_id=? AND approval_id=?", (current["run_id"], request["approval_id"])).fetchone()
            values = (request["scope_ref"], request["decision"], request["authority_ref"], request["artifact_sha256"])
            if existing and (existing["scope_ref"], existing["decision"], existing["authority_ref"], existing["artifact_sha256"]) != values:
                raise StateError("APPROVAL_CONFLICT")
            if not existing:
                conn.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?)", (current["run_id"], request["approval_id"], *values))
        elif kind == "budget-use":
            budget = conn.execute("SELECT * FROM budgets WHERE run_id=? AND budget_id=?", (current["run_id"], request["budget_id"])).fetchone()
            if not budget or budget["used"] + request["amount"] > budget["limit_value"]:
                raise StateError("BUDGET_LIMIT")
            source = conn.execute("SELECT 1 FROM nodes WHERE branch_id=?", (request["source_branch_id"],)).fetchone()
            if not source:
                raise StateError("BRANCH_NOT_FOUND")
            duplicate = conn.execute(
                "SELECT 1 FROM budget_consumptions WHERE run_id=? AND budget_id=? AND source_branch_id=?",
                (current["run_id"], request["budget_id"], request["source_branch_id"]),
            ).fetchone()
            if duplicate:
                raise StateError("BUDGET_CONSUMPTION_CONFLICT")
            conn.execute("INSERT INTO budget_consumptions VALUES(?,?,?,?)", (current["run_id"], request["budget_id"], request["source_branch_id"], request["amount"]))
            conn.execute("UPDATE budgets SET used=used+? WHERE run_id=? AND budget_id=?", (request["amount"], current["run_id"], request["budget_id"]))
        elif kind == "acceptance-evidence":
            ids = set(task["acceptance_ids"])
            if request["criterion_id"] not in ids:
                raise StateError("UNKNOWN_CRITERION")
            verified = resolve_reference(
                request["artifact_ref"], request["artifact_sha256"], "acceptance_evidence",
                Path(current["repository_path"]), Path(__file__).resolve().parents[1], policy, conn,
            )
            persist_artifact(conn, current["run_id"], verified)
            existing = conn.execute("SELECT * FROM acceptance_evidence WHERE run_id=? AND criterion_id=?", (current["run_id"], request["criterion_id"])).fetchone()
            if existing and (existing["artifact_ref"], existing["artifact_sha256"]) != (verified.ref, verified.sha256):
                raise StateError("EVIDENCE_CONFLICT")
            if not existing:
                conn.execute("INSERT INTO acceptance_evidence VALUES(?,?,?,?)", (current["run_id"], request["criterion_id"], verified.ref, verified.sha256))
        else:
            if request["check_id"] not in task["required_check_ids"]:
                raise StateError("UNKNOWN_CHECK")
            verified = resolve_reference(
                request["artifact_ref"], request["artifact_sha256"], "check_evidence",
                Path(current["repository_path"]), Path(__file__).resolve().parents[1], policy, conn,
            )
            persist_artifact(conn, current["run_id"], verified)
            existing = conn.execute("SELECT * FROM check_evidence WHERE run_id=? AND check_id=?", (current["run_id"], request["check_id"])).fetchone()
            values = (request["outcome"], verified.ref, verified.sha256)
            if existing and (existing["outcome"], existing["artifact_ref"], existing["artifact_sha256"]) != values:
                raise StateError("EVIDENCE_CONFLICT")
            if not existing:
                conn.execute("INSERT INTO check_evidence VALUES(?,?,?,?,?)", (current["run_id"], request["check_id"], *values))
        return {"code": kind.upper().replace("-", "_") + "_RECORDED"}

    return store.mutate(connection, run["run_id"], op_id, request, action)


def command_record(args: argparse.Namespace, connection: sqlite3.Connection, run: sqlite3.Row, policy: Mapping[str, Any], task: Mapping[str, Any], store: StateStore) -> Dict[str, Any]:
    if args.record_kind == "branch-result":
        return _record_branch_result(args, connection, run, policy, task, store)
    return _record_control(args, connection, run, policy, task, store)


def _ready_envelopes(connection: sqlite3.Connection, run: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = connection.execute("SELECT envelope_json FROM nodes WHERE run_id=? AND status='ready' ORDER BY branch_id", (run["run_id"],)).fetchall()
    return [json.loads(row["envelope_json"]) for row in rows]


def command_next(
    args: argparse.Namespace, connection: sqlite3.Connection, run: sqlite3.Row,
    policy_digest: str, repo: Path, policy: Mapping[str, Any], store: StateStore,
) -> Dict[str, Any]:
    if not args.claim:
        verify_semantic_state(
            connection, run, repo, policy_digest, policy, Path(__file__).resolve().parents[1]
        )
        if run["status"] == "blocked":
            return _json_result(False, "GRAPH_BLOCKED", run["run_id"], run["state_revision"], branches=[])
        if run["status"] in {"complete", "aborted"}:
            return _json_result(False, "NOT_READY", run["run_id"], run["state_revision"], branches=[])
        ready = _ready_envelopes(connection, run)
        selected = ready if args.all else ready[:1]
        code = "READY" if selected else "NOT_READY"
        return _json_result(bool(selected), code, run["run_id"], run["state_revision"], branches=selected)
    op_id = opaque(args.op_id, "op_id")
    request = {"command": "next.claim"}

    def action(conn: sqlite3.Connection, current: sqlite3.Row, revision: int) -> Dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM nodes WHERE run_id=? AND status='ready' ORDER BY branch_id LIMIT 1",
            (current["run_id"],),
        ).fetchone()
        if not row:
            raise StateError("CLAIM_CONFLICT")
        env = json.loads(row["envelope_json"])
        env["status"] = "running"
        env["started_at"] = utc_now()
        conn.execute("UPDATE nodes SET status='running',started_at=?,envelope_json=? WHERE branch_id=?", (env["started_at"], json.dumps(env, sort_keys=True), row["branch_id"]))
        return {"code": "CLAIMED", "branch": env}

    return store.mutate(connection, run["run_id"], op_id, request, action)


def command_join_validate(args: argparse.Namespace, connection: sqlite3.Connection, run: sqlite3.Row) -> Dict[str, Any]:
    join = connection.execute("SELECT * FROM joins WHERE join_id=? AND run_id=?", (args.join_id, run["run_id"])).fetchone()
    if not join:
        raise StateError("JOIN_NOT_FOUND")
    result = validate_join(connection, run, join)
    return _json_result(result["join_status"] == "READY", result["join_status"], run["run_id"], run["state_revision"], join_id=args.join_id, groups=result["groups"])


def _consume_loop_budget(connection: sqlite3.Connection, run_id: str, budget_id: str) -> bool:
    budget = connection.execute("SELECT * FROM budgets WHERE run_id=? AND budget_id=?", (run_id, budget_id)).fetchone()
    if budget["used"] >= budget["limit_value"]:
        return False
    connection.execute("UPDATE budgets SET used=used+1 WHERE run_id=? AND budget_id=?", (run_id, budget_id))
    return True


def command_join_advance(args: argparse.Namespace, connection: sqlite3.Connection, run: sqlite3.Row, policy: Mapping[str, Any], task: Mapping[str, Any], store: StateStore) -> Dict[str, Any]:
    op_id = opaque(args.op_id, "op_id")
    request = {"command": "join.advance", "join_id": opaque(args.join_id, "join_id")}

    def action(conn: sqlite3.Connection, current: sqlite3.Row, revision: int) -> Dict[str, Any]:
        join = conn.execute("SELECT * FROM joins WHERE join_id=? AND run_id=?", (args.join_id, current["run_id"])).fetchone()
        if not join:
            raise StateError("JOIN_NOT_FOUND")
        validation = validate_join(conn, current, join)
        if validation["join_status"] != "READY":
            if validation["join_status"] == "BLOCKED":
                conn.execute("UPDATE runs SET status='blocked',blocked_reason='MANDATORY_BRANCH_FAILED' WHERE run_id=?", (current["run_id"],))
                return {"code": "GRAPH_BLOCKED", "status": "blocked", "reason": "MANDATORY_BRANCH_FAILED", "join_id": join["join_id"]}
            raise StateError(validation["join_status"])
        if join["kind"] == "closure":
            raise StateError("COMPLETE_COMMAND_REQUIRED")
        members = join_members(conn, join["join_id"])
        frozen = canonical_collection_members(conn, members)
        collection_artifact = None
        collection_manifest = None
        if join["kind"] == "collection":
            collection_manifest = {
                "schema_version": 1, "kind": "collection", "join_id": join["join_id"], "members": frozen,
            }
            collection_artifact = canonical_ledger_artifact(join["join_id"], "collection", collection_manifest)
            enforce_artifact_size(collection_artifact.kind, collection_artifact.size_bytes, policy)
        conn.execute("UPDATE joins SET status='sealed',result_json=? WHERE join_id=?", (json.dumps(frozen, sort_keys=True), join["join_id"]))
        route = current["selected_route"]
        tags = json.loads(current["selected_tags_json"] or "[]")
        successor_ids: List[str] = []
        outcome: Optional[str] = None
        if join["kind"] == "collection":
            if collection_artifact is None or collection_manifest is None:
                raise StateError("COLLECTION_ARTIFACT_INVALID")
            persist_artifact(conn, current["run_id"], collection_artifact)
            spec = consolidation_node(policy, join["stage"], join["generation"])
            inputs = _context_inputs(conn, current, [], include_design=join["stage"] == "delivery", include_implementation=join["stage"] == "delivery")
            collection_input = collection_artifact.as_input()
            collection_input["content"] = collection_manifest
            inputs.append(collection_input)
            node = _insert_spec(store, conn, current, policy, task, spec, inputs)
            successor_ids.append(node["branch_id"])
            _insert_join(store, conn, current, consolidation_join(join["stage"], join["generation"], spec))
        elif join["kind"] == "dependency":
            source = members[0]
            if join["stage"] == "design":
                inputs = _context_inputs(conn, current, [source])
                specs = design_review_nodes(policy, tags, join["generation"])
                stage = "design"
            else:
                inputs = _context_inputs(conn, current, [source], include_design=True, include_implementation=True)
                specs = delivery_review_nodes(policy, tags, join["generation"])
                stage = "delivery"
            for spec in specs:
                successor_ids.append(_insert_spec(store, conn, current, policy, task, spec, inputs)["branch_id"])
            _insert_join(store, conn, current, collection_join(stage, join["generation"], specs))
        elif join["kind"] == "consolidation":
            consolidation = members[0]
            manifest = json.loads(consolidation["result_json"])
            source_join = conn.execute(
                "SELECT * FROM joins WHERE run_id=? AND join_key=? AND generation=?",
                (current["run_id"], join["stage"] + "_collection", join["generation"]),
            ).fetchone()
            if not source_join or source_join["status"] != "sealed":
                raise StateError("SOURCE_COLLECTION_NOT_SEALED")
            source_members = join_members(conn, source_join["join_id"])
            outcome = validate_consolidation_manifest(
                manifest, join["stage"], current["run_id"], source_join["join_id"], join["generation"], source_members,
            )
            design_context = _context_inputs(conn, current, [consolidation], include_design=True)
            delivery_context = _context_inputs(
                conn, current, [consolidation], include_design=True, include_implementation=True
            )
            if outcome == "BLOCK":
                conn.execute("UPDATE runs SET status='blocked',blocked_reason='CONSOLIDATION_BLOCK' WHERE run_id=?", (current["run_id"],))
            elif join["stage"] == "design" and outcome == "REVISE":
                if not _consume_loop_budget(conn, current["run_id"], "design_revisions"):
                    conn.execute("UPDATE runs SET status='blocked',blocked_reason='DESIGN_REVISION_LIMIT' WHERE run_id=?", (current["run_id"],))
                    outcome = "BLOCK"
                else:
                    generation = join["generation"] + 1
                    spec = revised_design_node(policy, generation)
                    successor_ids.append(_insert_spec(store, conn, current, policy, task, spec, design_context)["branch_id"])
                    conn.execute("UPDATE runs SET design_generation=? WHERE run_id=?", (generation, current["run_id"]))
            elif join["stage"] == "design" and outcome == "APPROVE":
                if route == "design_only":
                    _insert_join(store, conn, current, closure_join(NodeSpec(
                        consolidation["node_key"], consolidation["role"], consolidation["stage"], consolidation["generation"],
                        bool(consolidation["mandatory"]), consolidation["specialist_tag"],
                    ), join["generation"]))
                elif route in {"full_delivery", "fast_path"}:
                    generation = current["implementation_generation"]
                    spec = implementation_node(policy, generation)
                    successor_ids.append(_insert_spec(store, conn, current, policy, task, spec, design_context)["branch_id"])
                else:
                    raise StateError("ROUTE_TRANSITION_INVALID")
            elif join["stage"] == "delivery" and outcome == "REPAIR":
                if not _consume_loop_budget(conn, current["run_id"], "delivery_repairs"):
                    conn.execute("UPDATE runs SET status='blocked',blocked_reason='DELIVERY_REPAIR_LIMIT' WHERE run_id=?", (current["run_id"],))
                    outcome = "BLOCK"
                else:
                    generation = current["implementation_generation"] + 1
                    spec = implementation_node(policy, generation)
                    successor_ids.append(_insert_spec(store, conn, current, policy, task, spec, delivery_context)["branch_id"])
                    conn.execute("UPDATE runs SET implementation_generation=? WHERE run_id=?", (generation, current["run_id"]))
            elif join["stage"] == "delivery" and outcome == "REDESIGN":
                if not _consume_loop_budget(conn, current["run_id"], "design_revisions"):
                    conn.execute("UPDATE runs SET status='blocked',blocked_reason='DESIGN_REVISION_LIMIT' WHERE run_id=?", (current["run_id"],))
                    outcome = "BLOCK"
                else:
                    design_generation = current["design_generation"] + 1
                    implementation_generation = current["implementation_generation"] + 1
                    spec = revised_design_node(policy, design_generation)
                    successor_ids.append(_insert_spec(store, conn, current, policy, task, spec, delivery_context)["branch_id"])
                    conn.execute("UPDATE runs SET design_generation=?,implementation_generation=? WHERE run_id=?", (design_generation, implementation_generation, current["run_id"]))
            elif join["stage"] == "delivery" and outcome == "ACCEPT":
                _insert_join(store, conn, current, closure_join(NodeSpec(
                    consolidation["node_key"], consolidation["role"], consolidation["stage"], consolidation["generation"],
                    bool(consolidation["mandatory"]), consolidation["specialist_tag"],
                ), join["generation"]))
        return {"code": "JOIN_ADVANCED", "join_id": join["join_id"], "outcome": outcome, "successor_branch_ids": sorted(successor_ids)}

    return store.mutate(connection, run["run_id"], op_id, request, action)


def _next_action(connection: sqlite3.Connection, run: Mapping[str, Any]) -> Dict[str, Any]:
    if run["status"] in {"blocked", "complete", "aborted"}:
        return {"kind": run["status"]}
    ready = connection.execute("SELECT branch_id FROM nodes WHERE run_id=? AND status='ready' ORDER BY branch_id LIMIT 1", (run["run_id"],)).fetchone()
    if ready:
        return {"kind": "claim", "branch_id": ready["branch_id"]}
    ready_join = []
    for join in connection.execute("SELECT * FROM joins WHERE run_id=? AND status='open' ORDER BY join_id", (run["run_id"],)):
        if validate_join(connection, run, join)["join_status"] == "READY":
            ready_join.append(join["join_id"])
    if ready_join:
        return {"kind": "advance_join", "join_id": ready_join[0]}
    running = connection.execute("SELECT branch_id FROM nodes WHERE run_id=? AND status='running' ORDER BY branch_id", (run["run_id"],)).fetchall()
    return {"kind": "await_result", "branch_ids": [row["branch_id"] for row in running]}


def command_status(connection: sqlite3.Connection, run: sqlite3.Row) -> Dict[str, Any]:
    branches = connection.execute("SELECT branch_id,node_key,role,generation,status,retry_count,max_retries FROM nodes WHERE run_id=? ORDER BY branch_id", (run["run_id"],)).fetchall()
    joins = connection.execute("SELECT join_id,join_key,kind,generation,status,degraded FROM joins WHERE run_id=? ORDER BY join_id", (run["run_id"],)).fetchall()
    budgets = connection.execute("SELECT budget_id,limit_value,used FROM budgets WHERE run_id=? ORDER BY budget_id", (run["run_id"],)).fetchall()
    approvals = connection.execute("SELECT approval_id,scope_ref,decision,authority_ref,artifact_sha256 FROM approvals WHERE run_id=? ORDER BY approval_id", (run["run_id"],)).fetchall()
    acceptance = connection.execute("SELECT criterion_id,artifact_ref,artifact_sha256 FROM acceptance_evidence WHERE run_id=? ORDER BY criterion_id", (run["run_id"],)).fetchall()
    checks = connection.execute("SELECT check_id,outcome,artifact_ref,artifact_sha256 FROM check_evidence WHERE run_id=? ORDER BY check_id", (run["run_id"],)).fetchall()
    return _json_result(
        True, "STATUS", run["run_id"], run["state_revision"], sensitive=True, status=run["status"],
        route=run["selected_route"], impact_tags=json.loads(run["selected_tags_json"] or "[]"),
        policy_digest=run["policy_digest"], engine_version=run["engine_version"],
        state_schema_version=run["state_schema_version"], local_filesystem=run["local_filesystem"],
        durability=run["durability"], durability_detail=run["durability_detail"],
        permission_verification=run["permission_verification"],
        acknowledgments={
            "host_identity": run["host_identity"],
            "degraded_permissions": bool(run["degraded_permissions_ack"]),
            "degraded_durability": bool(run["degraded_durability_ack"]),
        },
        branches=[dict(row) for row in branches], joins=[dict(row) for row in joins],
        budgets=[dict(row) for row in budgets], approvals=[dict(row) for row in approvals],
        acceptance_evidence=[dict(row) for row in acceptance], check_evidence=[dict(row) for row in checks],
        next_action=_next_action(connection, run), blocked_reason=run["blocked_reason"],
    )


def command_complete(args: argparse.Namespace, connection: sqlite3.Connection, run: sqlite3.Row, task: Mapping[str, Any], store: StateStore) -> Dict[str, Any]:
    request = {"command": "complete"}

    def action(conn: sqlite3.Connection, current: sqlite3.Row, revision: int) -> Dict[str, Any]:
        if current["status"] != "active":
            raise StateError("INVALID_RUN_TRANSITION")
        closure = conn.execute("SELECT * FROM joins WHERE run_id=? AND join_key='closure' AND status='open' ORDER BY generation DESC LIMIT 1", (current["run_id"],)).fetchone()
        if not closure or validate_join(conn, current, closure)["join_status"] != "READY":
            raise StateError("CLOSURE_NOT_READY")
        criteria = set(task["acceptance_ids"])
        evidenced = {row[0] for row in conn.execute("SELECT criterion_id FROM acceptance_evidence WHERE run_id=?", (current["run_id"],))}
        if criteria != evidenced:
            raise StateError("ACCEPTANCE_EVIDENCE_INCOMPLETE")
        passed = {row[0] for row in conn.execute("SELECT check_id FROM check_evidence WHERE run_id=? AND outcome='PASS'", (current["run_id"],))}
        if not set(task["required_check_ids"]).issubset(passed):
            raise StateError("REQUIRED_CHECKS_INCOMPLETE")
        rejected = conn.execute("SELECT 1 FROM approvals WHERE run_id=? AND decision='REJECT'", (current["run_id"],)).fetchone()
        if rejected:
            raise StateError("APPROVAL_REJECTED")
        approved = {row[0] for row in conn.execute("SELECT approval_id FROM approvals WHERE run_id=? AND decision='APPROVE'", (current["run_id"],))}
        if not set(task["required_human_decisions"]).issubset(approved):
            raise StateError("REQUIRED_APPROVALS_INCOMPLETE")
        conn.execute("UPDATE joins SET status='sealed',result_json=? WHERE join_id=?", (json.dumps({"complete": True}), closure["join_id"]))
        conn.execute("UPDATE runs SET status='complete' WHERE run_id=?", (current["run_id"],))
        return {"code": "COMPLETE", "status": "complete"}

    return store.mutate(connection, run["run_id"], opaque(args.op_id, "op_id"), request, action)


def command_run_control(args: argparse.Namespace, connection: sqlite3.Connection, run: sqlite3.Row, policy: Mapping[str, Any], task: Mapping[str, Any], store: StateStore) -> Dict[str, Any]:
    if args.command == "complete":
        return command_complete(args, connection, run, task, store)
    if args.command == "resume":
        if run["permission_verification"] == "DEGRADED_PERMISSION_VERIFICATION" and not args.ack_degraded_permissions:
            raise StateError("DEGRADED_PERMISSION_ACK_REQUIRED")
        if run["durability"] == "degraded" and not args.ack_degraded_durability:
            raise StateError("DEGRADED_DURABILITY_ACK_REQUIRED")
        verify_resume(
            connection, run, Path(run["repository_path"]), run["policy_digest"], policy,
            Path(__file__).resolve().parents[1],
        )
        result = command_status(connection, run)
        result["code"] = "RESUMED"
        result["acknowledgments"] = {
            "host_identity": run["host_identity"],
            "degraded_permissions": bool(args.ack_degraded_permissions),
            "degraded_durability": bool(args.ack_degraded_durability),
            "recorded_degraded_permissions": bool(run["degraded_permissions_ack"]),
            "recorded_degraded_durability": bool(run["degraded_durability_ack"]),
        }
        result["unresolved_running"] = [branch["branch_id"] for branch in result["branches"] if branch["status"] == "running"]
        return result
    if args.command == "block":
        snapshot = _manifest_snapshot(store, policy, run["run_id"], args.evidence_manifest, 128 * 1024)
        request = {"command": "block", "reason_code": opaque(args.reason_code, "reason_code"), "evidence_digest": snapshot.digest}
        target, code = "blocked", "GRAPH_BLOCKED"
    else:
        request = {"command": "abort", "reason_code": opaque(args.reason_code, "reason_code"), "authority_ref": validate_ref(args.authority_ref, "authority_ref")}
        target, code = "aborted", "ABORTED"

    def action(conn: sqlite3.Connection, current: sqlite3.Row, revision: int) -> Dict[str, Any]:
        if current["status"] not in ({"initialized", "active"} if target == "blocked" else {"initialized", "active", "blocked"}):
            raise StateError("INVALID_RUN_TRANSITION")
        if target == "blocked":
            manifest = _validate_control_manifest(snapshot.parsed, "block", current["run_id"], None, request["reason_code"])
            verified_items = []
            for item in manifest["evidence"]:
                if not isinstance(item, dict):
                    raise ContractError("evidence", "INVALID_OBJECT")
                require_keys(item, {"kind", "ref", "sha256"}, {"kind", "ref", "sha256"}, "evidence")
                verified = resolve_reference(
                    item["ref"], item["sha256"], item["kind"], Path(current["repository_path"]),
                    Path(__file__).resolve().parents[1], policy, conn,
                )
                persist_artifact(conn, current["run_id"], verified)
                verified_items.append({"kind": verified.kind, "ref": verified.ref, "sha256": verified.sha256})
            manifest["evidence"] = verified_items
            block_artifact = canonical_ledger_artifact("block-" + args.op_id, "evidence_manifest", manifest)
            persist_artifact(conn, current["run_id"], block_artifact)
        conn.execute("UPDATE runs SET status=?,blocked_reason=? WHERE run_id=?", (target, request["reason_code"], current["run_id"]))
        return {"code": code, "status": target}

    return store.mutate(connection, run["run_id"], opaque(args.op_id, "op_id"), request, action)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="graphctl")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--ack-degraded-permissions", action="store_true")
    parser.add_argument("--ack-degraded-durability", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--run-id", required=True); init.add_argument("--task-brief", required=True); init.add_argument("--op-id", required=True)
    init.add_argument("--ack-degraded-permissions", action="store_true", default=argparse.SUPPRESS)
    init.add_argument("--ack-degraded-durability", action="store_true", default=argparse.SUPPRESS)
    record = commands.add_parser("record")
    records = record.add_subparsers(dest="record_kind", required=True)
    branch = records.add_parser("branch-result"); branch.add_argument("--run-id", required=True); branch.add_argument("--branch-id", required=True); branch.add_argument("--result-manifest", required=True); branch.add_argument("--op-id", required=True)
    for name in ("timeout", "skip"):
        sub = records.add_parser(name); sub.add_argument("--run-id", required=True); sub.add_argument("--branch-id", required=True); sub.add_argument("--reason-code", required=True); sub.add_argument("--evidence-manifest", required=True); sub.add_argument("--op-id", required=True)
    retry = records.add_parser("retry"); retry.add_argument("--run-id", required=True); retry.add_argument("--branch-id", required=True); retry.add_argument("--reason-code", required=True); retry.add_argument("--op-id", required=True)
    approval = records.add_parser("approval"); approval.add_argument("--run-id", required=True); approval.add_argument("--approval-id", required=True); approval.add_argument("--scope-ref", required=True); approval.add_argument("--decision", choices=["APPROVE", "REJECT"], required=True); approval.add_argument("--authority-ref", required=True); approval.add_argument("--artifact-sha256", required=True); approval.add_argument("--op-id", required=True)
    budget = records.add_parser("budget-use"); budget.add_argument("--run-id", required=True); budget.add_argument("--budget-id", required=True); budget.add_argument("--amount", type=int, required=True); budget.add_argument("--source-branch-id", required=True); budget.add_argument("--op-id", required=True)
    acceptance = records.add_parser("acceptance-evidence"); acceptance.add_argument("--run-id", required=True); acceptance.add_argument("--criterion-id", required=True); acceptance.add_argument("--artifact-ref", required=True); acceptance.add_argument("--artifact-sha256", required=True); acceptance.add_argument("--op-id", required=True)
    check = records.add_parser("check-evidence"); check.add_argument("--run-id", required=True); check.add_argument("--check-id", required=True); check.add_argument("--outcome", choices=["PASS", "FAIL", "NOT_RUN"], required=True); check.add_argument("--artifact-ref", required=True); check.add_argument("--artifact-sha256", required=True); check.add_argument("--op-id", required=True)
    for name in ("next", "ready"):
        sub = commands.add_parser(name); sub.add_argument("--run-id", required=True); sub.add_argument("--all", action="store_true"); sub.add_argument("--claim", action="store_true"); sub.add_argument("--op-id")
    join = commands.add_parser("join"); joins = join.add_subparsers(dest="join_kind", required=True)
    validate = joins.add_parser("validate"); validate.add_argument("--run-id", required=True); validate.add_argument("--join-id", required=True)
    advance = joins.add_parser("advance"); advance.add_argument("--run-id", required=True); advance.add_argument("--join-id", required=True); advance.add_argument("--op-id", required=True)
    status = commands.add_parser("status"); status.add_argument("--run-id", required=True); status.add_argument("--json", action="store_true")
    complete = commands.add_parser("complete"); complete.add_argument("--run-id", required=True); complete.add_argument("--op-id", required=True)
    block = commands.add_parser("block"); block.add_argument("--run-id", required=True); block.add_argument("--reason-code", required=True); block.add_argument("--evidence-manifest", required=True); block.add_argument("--op-id", required=True)
    abort = commands.add_parser("abort"); abort.add_argument("--run-id", required=True); abort.add_argument("--reason-code", required=True); abort.add_argument("--authority-ref", required=True); abort.add_argument("--op-id", required=True)
    resume = commands.add_parser("resume"); resume.add_argument("--run-id", required=True)
    resume.add_argument("--ack-degraded-permissions", action="store_true", default=argparse.SUPPRESS)
    resume.add_argument("--ack-degraded-durability", action="store_true", default=argparse.SUPPRESS)
    return parser


def execute(argv: Optional[Sequence[str]] = None, store: Optional[StateStore] = None) -> Tuple[Dict[str, Any], int]:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve(strict=True)
    policy, policy_snapshot = load_policy(repo)
    state = store or StateStore()
    if args.command == "init":
        return command_init(args, repo, policy, policy_snapshot, state), 0
    run_id = opaque(args.run_id, "run_id")
    with state.open_run(policy["repository_id"], run_id) as connection:
        run, stored_policy, task = _run_context(connection, run_id)
        skill_root = Path(__file__).resolve().parents[1]
        state.semantic_validator = lambda conn, current: verify_semantic_state(
            conn, current, repo, policy_snapshot.digest, policy, skill_root
        )
        is_mutation = (
            args.command in {"record", "complete", "block", "abort"}
            or (args.command in {"next", "ready"} and args.claim)
            or (args.command == "join" and args.join_kind == "advance")
        )
        if not is_mutation:
            verify_semantic_state(connection, run, repo, policy_snapshot.digest, policy, skill_root)
        if args.command == "record":
            result = command_record(args, connection, run, stored_policy, task, state)
        elif args.command in {"next", "ready"}:
            if args.command == "ready":
                args.all = True; args.claim = False
            if args.claim and not args.op_id:
                raise ContractError("op_id", "MISSING_FIELD")
            result = command_next(args, connection, run, policy_snapshot.digest, repo, policy, state)
        elif args.command == "join":
            result = command_join_validate(args, connection, run) if args.join_kind == "validate" else command_join_advance(args, connection, run, stored_policy, task, state)
        elif args.command == "status":
            result = command_status(connection, run)
        else:
            result = command_run_control(args, connection, run, stored_policy, task, state)
    if result["code"] == "NOT_READY":
        return result, 2
    if result["code"] == "GRAPH_BLOCKED":
        return result, 3
    return result, 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        result, exit_code = execute(argv)
    except ContractError as error:
        result, exit_code = _json_result(False, error.code, None, None, field=error.field), 4
    except StateError as error:
        conflict = error.code in {
            "OPERATION_CONFLICT", "TRANSACTION_CONFLICT", "CLAIM_CONFLICT",
            "INITIALIZATION_CONFLICT", "RUN_ALREADY_EXISTS", "INCOMPLETE_INIT_CONFLICT",
        }
        blocked = error.code in {"GRAPH_BLOCKED", "RETRY_LIMIT", "BUDGET_LIMIT"}
        not_ready = error.code in {"NOT_READY", "RETRY_REQUIRED"}
        result = _json_result(False, error.code, None, None)
        exit_code = 5 if conflict else 3 if blocked else 2 if not_ready else 4
    except (OSError, sqlite3.Error):
        result, exit_code = _json_result(False, "IO_OR_TRANSACTION_FAILURE", None, None), 5
    _emit(result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
