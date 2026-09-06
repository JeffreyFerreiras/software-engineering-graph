"""Optional, bounded Codex token telemetry. No conversation content enters the ledger."""

import copy
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .contracts import ContractError, digest, opaque, require_keys
from .hosts import HOST_MATRIX
from .ids import canonical_bytes, sha256_bytes, stable_id
from .state import StateError


PHASES = ("scoping", "research_design", "implementation", "review_testing", "closure")
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "unknown"}
MODELS = {row[0] for catalog in HOST_MATRIX.values() for row in catalog.values()} - {"primary-thread"}
MODELS.add("unknown")
REQUIRED = ("input_tokens", "output_tokens", "total_tokens")
OPTIONAL = ("cached_input_tokens", "reasoning_output_tokens", "cache_write_tokens")
METRICS = REQUIRED + OPTIONAL
MAX_INTEGER = (1 << 63) - 1
MAX_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
MAX_RECORDS = 100000
DIAGNOSTICS = {
    "source_unavailable", "source_unsafe", "source_changed", "source_limit", "record_limit",
    "malformed_record", "unsupported_usage", "missing_identity", "missing_usage",
    "identity_changed", "prefix_changed", "counter_reset", "prefix_gap", "ambiguous_increment",
    "unknown_context", "optional_discontinuity", "open_interval", "invalid_usage_state",
}
STAGE_PHASE = {
    "bootstrap": "scoping", "research": "research_design", "design": "research_design",
    "implementation": "implementation", "delivery": "review_testing", "advisory": "review_testing",
    "review_delegation": "review_testing",
    "closure": "closure",
}


def _integer(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_INTEGER


def _counters(value: Any, *, aggregate: bool = False) -> Optional[Dict[str, Optional[int]]]:
    def valid_number(number: Any) -> bool:
        return type(number) is int and number >= 0 and (aggregate or number <= MAX_INTEGER)

    if not isinstance(value, dict) or any(not valid_number(value.get(key)) for key in REQUIRED):
        return None
    if value["total_tokens"] != value["input_tokens"] + value["output_tokens"]:
        return None
    result = {key: value[key] for key in REQUIRED}
    for key in OPTIONAL:
        number = value.get(key)
        maximum = value["input_tokens"] if key == "cached_input_tokens" else value["output_tokens"]
        result[key] = number if valid_number(number) and (key == "cache_write_tokens" or number <= maximum) else None
    return result


def _source_counters(value: Any) -> Optional[Dict[str, Optional[int]]]:
    if isinstance(value, dict) and "cache_write_input_tokens" in value:
        # The observed source spelling wins, even when invalid; no alias fallback
        # may turn malformed preferred metadata into an apparently valid count.
        value = {**value, "cache_write_tokens": value["cache_write_input_tokens"]}
    return _counters(value)


def _context(value: Mapping[str, Any]) -> Dict[str, str]:
    model, effort = value.get("model"), value.get("effort", value.get("reasoning_effort"))
    return {
        "model": model if isinstance(model, str) and model in MODELS else "unknown",
        "effort": effort if isinstance(effort, str) and effort in EFFORTS else "unknown",
    }


def _safe_components(path: Path) -> None:
    for component in (path,) + tuple(path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise StateError("USAGE_SOURCE_UNSAFE")


def _identity(info: os.stat_result) -> Tuple[int, int]:
    return info.st_dev, info.st_ino


def _read_source(path: str) -> Tuple[bytes, List[str]]:
    """Snapshot one explicit regular file, with opened-handle and prefix continuity checks."""
    try:
        source = Path(os.path.abspath(path))
        _safe_components(source)
        before = source.stat()
        if not stat.S_ISREG(before.st_mode):
            return b"", ["source_unsafe"]
        if before.st_size > MAX_BYTES:
            return b"", ["source_limit"]
        flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        descriptor = os.open(str(source), flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
                return b"", ["source_changed"]
            _safe_components(source)
            chunks = []
            remaining = before.st_size
            while remaining:
                chunk = handle.read(min(remaining, CHUNK_BYTES))
                if not chunk:
                    return b"", ["source_changed"]
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            # Appends are permitted. Replacement or modification of any sampled byte is not.
            handle.seek(0)
            position = 0
            while position < len(data):
                chunk = handle.read(min(CHUNK_BYTES, len(data) - position))
                if not chunk or chunk != data[position:position + len(chunk)]:
                    return b"", ["source_changed"]
                position += len(chunk)
            after = source.stat()
            _safe_components(source)
            if (_identity(after) != _identity(opened) or after.st_size < len(data)
                    or _identity(os.fstat(handle.fileno())) != _identity(opened)):
                return b"", ["source_changed"]
            return data, []
    except StateError:
        return b"", ["source_unsafe"]
    except (OSError, ValueError, OverflowError):
        return b"", ["source_unavailable"]


def _bounded_json(line: bytes) -> Any:
    # Bound nesting before json.loads, including irrelevant conversation records.
    depth, quoted, escaped = 0, False, False
    for byte in line:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 24:
                raise ValueError()
        elif byte in (93, 125):
            depth -= 1
    return json.loads(line)


@dataclass
class Source:
    data: bytes
    source_id: Optional[str]
    snapshots: List[Dict[str, Any]]
    diagnostics: List[Tuple[int, str]]

    def checkpoint(self, offset: Optional[int] = None) -> Dict[str, Any]:
        if self.source_id is None:
            raise StateError("USAGE_CHECKPOINT_UNAVAILABLE")
        if offset is None:
            offset = self.snapshots[-1]["offset"] if self.snapshots else 0
        return {"checkpoint_schema_version": 1, "source_id": self.source_id,
                "offset": offset, "prefix_sha256": sha256_bytes(self.data[:offset])}


def read_source(path: str) -> Source:
    data, failures = _read_source(path)
    result = Source(data, None, [], [(0, code) for code in failures])
    if failures:
        return result
    position = 0
    context = _context({})
    contexts = set()
    last_total = None
    for index, line in enumerate(data.splitlines(keepends=True)):
        if not line.endswith(b"\n"):
            break
        position += len(line)
        if index >= MAX_RECORDS:
            result.diagnostics.append((position, "record_limit"))
            break
        if len(line) > CHUNK_BYTES:
            result.diagnostics.append((position, "record_limit"))
            continue
        try:
            record = _bounded_json(line)
        except (ValueError, UnicodeError, RecursionError):
            result.diagnostics.append((position, "malformed_record"))
            continue
        if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
            result.diagnostics.append((position, "malformed_record"))
            continue
        kind, payload = record.get("type"), record["payload"]
        if kind == "session_meta":
            identifier = payload.get("id")
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
                result.diagnostics.append((position, "missing_identity"))
                continue
            hashed = sha256_bytes(identifier.encode("utf-8"))
            if result.source_id is not None and result.source_id != hashed:
                result.diagnostics.append((position, "identity_changed"))
                result.source_id = None
                return result
            result.source_id = hashed
        elif kind == "turn_context":
            context = _context(payload)
            contexts.add((context["model"], context["effort"]))
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info")
            counters = _source_counters(info.get("total_token_usage")) if isinstance(info, dict) else None
            if counters is None:
                result.diagnostics.append((position, "unsupported_usage"))
                continue
            observed_contexts = contexts or {(context["model"], context["effort"])}
            selected = context if len(observed_contexts) == 1 else _context({})
            result.snapshots.append({
                "offset": position, "counters": counters,
                "last": _source_counters(info.get("last_token_usage")), "context": dict(selected),
                "ambiguous": len(observed_contexts) > 1,
            })
            if counters != last_total:
                contexts = set()
                last_total = counters
    if result.source_id is None:
        result.diagnostics.append((0, "missing_identity"))
    if not result.snapshots:
        result.diagnostics.append((0, "missing_usage"))
    return result


def checkpoint(path: str) -> Dict[str, Any]:
    source = read_source(path)
    if any(code != "missing_usage" for _, code in source.diagnostics):
        raise StateError("USAGE_CHECKPOINT_UNAVAILABLE")
    return source.checkpoint()


def validate_checkpoint(source: Source, value: Mapping[str, Any]) -> Dict[str, Any]:
    require_keys(value, {"offset", "source_id", "prefix_sha256"},
                 {"offset", "source_id", "prefix_sha256"}, "usage_checkpoint")
    offset = value["offset"]
    if not _integer(offset) or offset > len(source.data):
        raise StateError("USAGE_CHECKPOINT_INVALID")
    digest(value["source_id"], "source_id")
    digest(value["prefix_sha256"], "prefix_sha256")
    if (source.source_id != value["source_id"]
            or sha256_bytes(source.data[:offset]) != value["prefix_sha256"]
            or (offset != 0 and not any(item["offset"] == offset for item in source.snapshots))):
        raise StateError("USAGE_CHECKPOINT_MISMATCH")
    return dict(value)


def _add_diagnostic(binding: Dict[str, Any], code: str) -> None:
    binding["diagnostics"] = sorted(set(binding["diagnostics"]) | {code})


def _empty_totals() -> Dict[str, Optional[int]]:
    return {key: 0 for key in METRICS}


def _advance(binding: Dict[str, Any], source: Source, closing: bool, boundary_kind: str) -> None:
    """Attribute only cumulative differences; preserve observations when continuity is lost."""
    start = binding["offset"]
    if source.source_id is None:
        for _, code in source.diagnostics:
            _add_diagnostic(binding, code)
    elif source.source_id != binding["source_id"]:
        _add_diagnostic(binding, "identity_changed")
    elif len(source.data) < start or sha256_bytes(source.data[:start]) != binding["prefix_sha256"]:
        _add_diagnostic(binding, "prefix_changed")
    elif not binding["broken"]:
        for offset, code in source.diagnostics:
            if offset == 0 or offset > start:
                _add_diagnostic(binding, code)
        first = binding["previous"] is None
        for snapshot in source.snapshots:
            if snapshot["offset"] <= start:
                continue
            counters, previous = snapshot["counters"], binding["previous"]
            binding["observed"] = True
            delta = None
            if previous is None:
                if snapshot["last"] is not None and all(counters[key] == snapshot["last"][key] for key in REQUIRED):
                    delta = dict(counters)
                else:
                    _add_diagnostic(binding, "prefix_gap")
            elif any(counters[key] < previous[key] for key in REQUIRED):
                _add_diagnostic(binding, "counter_reset")
            elif all(counters[key] == previous[key] for key in REQUIRED):
                # Repeated token_count messages often differ only in timestamp or last usage.
                continue
            else:
                delta = {key: counters[key] - previous[key] for key in REQUIRED}
                for key in OPTIONAL:
                    now, before = counters[key], previous[key]
                    delta[key] = now - before if now is not None and before is not None and now >= before else None
                    if delta[key] is None:
                        binding["metric_partial"] = sorted(set(binding["metric_partial"]) | {key})
                for key, maximum in (("cached_input_tokens", delta["input_tokens"]),
                                     ("reasoning_output_tokens", delta["output_tokens"])):
                    if delta[key] is not None and delta[key] > maximum:
                        delta[key] = None
                        binding["metric_partial"] = sorted(set(binding["metric_partial"]) | {key})
            if delta is not None:
                ambiguous = snapshot["ambiguous"]
                # A checkpoint is a settled cumulative sample, not a timestamp partition.
                bridge = (first or boundary_kind != "continuation") and previous is not None
                if bridge and (snapshot["last"] is None or any(delta[key] != snapshot["last"][key] for key in REQUIRED)):
                    if boundary_kind == "baseline":
                        delta = None
                        _add_diagnostic(binding, "prefix_gap")
                    else:
                        ambiguous = True
                if delta is not None:
                    context = _context({}) if ambiguous else snapshot["context"]
                    phase = "unattributed" if ambiguous else binding["phase"]
                    if ambiguous:
                        _add_diagnostic(binding, "ambiguous_increment")
                    if "unknown" in context.values():
                        _add_diagnostic(binding, "unknown_context")
                    for key in OPTIONAL:
                        if delta[key] is None:
                            binding["metric_partial"] = sorted(set(binding["metric_partial"]) | {key})
                    segment = {"phase": phase, **context, "totals": delta}
                    # Coalesce adjacent equal dimensions so repeated polls do not bloat state.
                    if binding["segments"] and all(binding["segments"][-1][key] == segment[key] for key in ("phase", "model", "effort")):
                        _sum_into(binding["segments"][-1]["totals"], delta)
                    else:
                        binding["segments"].append(segment)
            binding["previous"] = counters
            first = False
            boundary_kind = "continuation"
        if source.snapshots:
            last_offset = source.snapshots[-1]["offset"]
            if last_offset >= start:
                binding["offset"] = last_offset
                binding["prefix_sha256"] = sha256_bytes(source.data[:last_offset])
        binding["boundary_kind"] = boundary_kind
    if any(code in binding["diagnostics"] for code in ("identity_changed", "prefix_changed", "source_changed")):
        binding["broken"] = True
    if closing:
        binding["closed"] = True


def _sum_into(target: Dict[str, Optional[int]], values: Mapping[str, Optional[int]]) -> None:
    for key in METRICS:
        if values[key] is None:
            target[key] = None
        elif target[key] is not None:
            target[key] += values[key]


def _bindings(connection: Any, run_id: str) -> Dict[str, Dict[str, Any]]:
    bindings = {}
    rows = connection.execute(
        "SELECT detail_json FROM events WHERE run_id=? AND event_type='usage.observation' ORDER BY event_id", (run_id,)
    )
    for row in rows:
        value = json.loads(row[0])
        _validate_binding(value)
        if value["branch_id"] is None:
            if value["role"] != "supervisor" or value["attempt_id"] is not None:
                raise ValueError()
        else:
            association = connection.execute(
                "SELECT n.role,n.stage,n.generation FROM nodes n JOIN branch_attempts a ON a.branch_id=n.branch_id "
                "WHERE n.run_id=? AND n.branch_id=? AND a.attempt_id=?", (run_id, value["branch_id"], value["attempt_id"])
            ).fetchone()
            if association is None or any((
                    association["role"] != value["role"], association["generation"] != value["generation"],
                    STAGE_PHASE.get(association["stage"]) != value["phase"])):
                raise ValueError()
        bindings[value["binding_id"]] = value
    return bindings


def _validate_binding(value: Any) -> None:
    """Reject optional telemetry corruption without weakening core graph validation."""
    keys = {"usage_schema_version", "binding_id", "source_id", "adapter", "branch_id", "attempt_id",
            "role", "phase", "generation", "start_offset", "offset", "prefix_sha256", "previous",
            "observed", "closed", "broken", "diagnostics", "metric_partial", "segments", "boundary_kind"}
    if not isinstance(value, dict):
        raise ValueError()
    require_keys(value, keys, keys, "usage")
    if value["usage_schema_version"] != 1 or value["adapter"] != "codex_jsonl_v1":
        raise ValueError()
    if value["phase"] not in PHASES or value["boundary_kind"] not in {"baseline", "phase", "continuation"}:
        raise ValueError()
    if not isinstance(value["binding_id"], str) or not re.fullmatch(r"g2-[0-9a-f]{24}", value["binding_id"]):
        raise ValueError()
    for key in ("binding_id", "role"):
        opaque(value[key], "usage")
    for key in ("branch_id", "attempt_id"):
        if value[key] is not None:
            opaque(value[key], "usage")
    digest(value["prefix_sha256"], "usage")
    if value["source_id"] is not None:
        digest(value["source_id"], "usage")
    elif (value["observed"] or value["previous"] is not None or value["segments"]
          or value["offset"] != 0 or value["start_offset"] != 0 or not value["diagnostics"]):
        raise ValueError()
    if any(not _integer(value[key]) for key in ("generation", "offset", "start_offset")) or value["offset"] < value["start_offset"]:
        raise ValueError()
    if any(type(value[key]) is not bool for key in ("observed", "closed", "broken")):
        raise ValueError()
    if value["previous"] is not None and _counters(value["previous"]) != value["previous"]:
        raise ValueError()
    for key, allowed in (("diagnostics", DIAGNOSTICS), ("metric_partial", set(OPTIONAL))):
        if not isinstance(value[key], list) or len(value[key]) > len(allowed) or any(item not in allowed for item in value[key]):
            raise ValueError()
    if not isinstance(value["segments"], list):
        raise ValueError()
    for segment in value["segments"]:
        require_keys(segment, {"phase", "model", "effort", "totals"}, {"phase", "model", "effort", "totals"}, "usage")
        if (segment["phase"] not in PHASES + ("unattributed",) or segment["model"] not in MODELS
                or segment["effort"] not in EFFORTS or _counters(segment["totals"], aggregate=True) != segment["totals"]):
            raise ValueError()


def _association(connection: Any, run_id: str, args: Any) -> Dict[str, Any]:
    if args.branch_id is not None or args.attempt_id is not None:
        if not args.branch_id or not args.attempt_id or args.phase is not None or args.generation is not None:
            raise StateError("USAGE_ASSOCIATION_INVALID")
        row = connection.execute(
            "SELECT n.role,n.stage,n.generation,n.branch_id,a.attempt_id FROM nodes n "
            "JOIN branch_attempts a ON a.branch_id=n.branch_id WHERE n.run_id=? AND n.branch_id=? AND a.attempt_id=?",
            (run_id, opaque(args.branch_id, "branch_id"), opaque(args.attempt_id, "attempt_id")),
        ).fetchone()
        if row is None or row["stage"] not in STAGE_PHASE:
            raise StateError("USAGE_ASSOCIATION_INVALID")
        return {"branch_id": row["branch_id"], "attempt_id": row["attempt_id"], "role": row["role"],
                "phase": STAGE_PHASE[row["stage"]], "generation": row["generation"]}
    if args.phase not in PHASES or not _integer(args.generation):
        raise StateError("USAGE_ASSOCIATION_INVALID")
    return {"branch_id": None, "attempt_id": None, "role": "supervisor", "phase": args.phase,
            "generation": args.generation}


def record(args: Any, connection: Any, run: Any, store: Any, semantic_validator: Any) -> Dict[str, Any]:
    """Prepare a sanitized request before StateStore persists anything."""
    operation_id = opaque(args.op_id, "op_id")
    historical = (args.start_offset, args.source_id, args.prefix_sha256)
    if any(value is not None for value in historical) and not all(value is not None for value in historical):
        raise StateError("USAGE_CHECKPOINT_INVALID")
    source = read_source(args.session_log)
    supplied = None
    if all(value is not None for value in historical):
        supplied = validate_checkpoint(source, {"offset": args.start_offset, "source_id": args.source_id,
                                                "prefix_sha256": args.prefix_sha256})
    request = {"command": "record.usage", "action": args.action, "source_id": source.source_id}
    if args.action == "bind":
        if args.binding_id is not None:
            raise StateError("USAGE_ARGUMENT_INVALID")
        association = _association(connection, run["run_id"], args)
        request.update(association)
        request["checkpoint"] = supplied
        binding_id = stable_id(run["run_id"], run["policy_digest"], "usage", operation_id, association["generation"])
    else:
        if supplied is not None or any(value is not None for value in (args.phase, args.generation, args.branch_id, args.attempt_id)):
            raise StateError("USAGE_ARGUMENT_INVALID")
        binding_id = opaque(args.binding_id, "binding_id")
    request["binding_id"] = binding_id
    # The explicit request is stable across appends, so retrying an operation never
    # collects a new span. Sampled metadata belongs only to its observation event.
    try:
        initial = _bindings(connection, run["run_id"])
    except (ValueError, TypeError, KeyError, ContractError, RecursionError):
        raise StateError("USAGE_STATE_INVALID")
    previous_digest = sha256_bytes(canonical_bytes(initial))

    def action(conn: Any, current: Any, revision: int) -> Dict[str, Any]:
        current_bindings = _bindings(conn, current["run_id"])
        if sha256_bytes(canonical_bytes(current_bindings)) != previous_digest:
            raise StateError("USAGE_STALE_CHECKPOINT")
        if args.action == "bind":
            # Retain a failed association as an unavailable interval. Dropping it
            # could make a partially observed resumed attempt look complete.
            selected = supplied or (source.checkpoint() if source.source_id is not None else {
                "offset": 0, "prefix_sha256": sha256_bytes(b"")})
            start = selected["offset"]
            prior = next((item for item in source.snapshots if item["offset"] == start), None)
            contiguous = any(item["source_id"] == source.source_id and item["closed"] and item["offset"] == start
                             for item in current_bindings.values())
            binding = {"usage_schema_version": 1, "binding_id": binding_id, "adapter": "codex_jsonl_v1",
                       "source_id": source.source_id, **association, "start_offset": start, "offset": start,
                       "prefix_sha256": selected["prefix_sha256"], "previous": prior["counters"] if prior else None,
                       "observed": prior is not None, "closed": False, "broken": False, "diagnostics": [],
                       "metric_partial": [], "segments": [], "boundary_kind": "phase" if contiguous else "baseline"}
            _advance(binding, source, False, binding["boundary_kind"])
        else:
            if binding_id not in current_bindings:
                raise StateError("USAGE_BINDING_NOT_FOUND")
            binding = copy.deepcopy(current_bindings[binding_id])
            if binding["closed"]:
                raise StateError("USAGE_BINDING_CLOSED")
            _advance(binding, source, args.action == "close", binding["boundary_kind"])
        for other_id, other in current_bindings.items():
            if binding["source_id"] is None or other_id == binding_id or other["source_id"] != binding["source_id"]:
                continue
            end = binding["offset"] if binding["closed"] else MAX_INTEGER
            other_end = other["offset"] if other["closed"] else MAX_INTEGER
            if binding["start_offset"] < other_end and other["start_offset"] < end:
                raise StateError("USAGE_INTERVAL_OVERLAP")
        _validate_binding(binding)
        conn.execute("INSERT INTO events(run_id,revision,event_type,source_id,detail_json) VALUES(?,?,?,?,?)",
                     (current["run_id"], revision, "usage.observation", binding_id, json.dumps(binding, sort_keys=True)))
        return {"code": "USAGE_RECORDED" if binding["source_id"] else "USAGE_UNAVAILABLE", "binding_id": binding_id, "checkpoint": {
                    "checkpoint_schema_version": 1, "source_id": binding["source_id"],
                    "offset": binding["offset"], "prefix_sha256": binding["prefix_sha256"]} if binding["source_id"] else None,
                "usage": report(conn, current)}

    return store.mutate(connection, run["run_id"], operation_id, request, action, semantic_validator=semantic_validator)


def _summary(bindings: List[Mapping[str, Any]], segments: List[Mapping[str, Any]], missing: bool = False) -> Dict[str, Any]:
    observed = any(item["observed"] for item in bindings)
    totals = _empty_totals()
    for segment in segments:
        _sum_into(totals, segment["totals"])
    diagnostics = sorted({code for item in bindings for code in item["diagnostics"]})
    open_interval = any(not item["closed"] for item in bindings)
    complete = observed and not missing and not diagnostics and not open_interval
    if open_interval:
        diagnostics = sorted(set(diagnostics) | {"open_interval"})
    return {"coverage": "complete" if complete else "partial" if observed else "unavailable",
            "observed_totals": totals if observed else None, "complete_totals": totals if complete else None,
            "diagnostics": diagnostics, "metric_partial": sorted({key for item in bindings for key in item["metric_partial"]})}


def report(connection: Any, run: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        bindings = list(_bindings(connection, run["run_id"]).values())
    except (ValueError, TypeError, KeyError, ContractError, RecursionError):
        return {"usage_schema_version": 1, "coverage": "unavailable", "observed_totals": None,
                "complete_totals": None, "diagnostics": ["invalid_usage_state"]}
    attempts = connection.execute(
        "SELECT a.attempt_id,a.branch_id,n.role,n.stage,n.generation FROM branch_attempts a JOIN nodes n ON n.branch_id=a.branch_id WHERE a.run_id=?",
        (run["run_id"],),
    ).fetchall()
    covered = {item["attempt_id"] for item in bindings}
    missing = [row["attempt_id"] for row in attempts if row["attempt_id"] not in covered]
    primary_scopes = {(item["phase"], item["generation"]) for item in bindings if item["branch_id"] is None}
    executed_scopes = {("scoping", 0)} | {(STAGE_PHASE[row["stage"]], row["generation"]) for row in attempts}
    if run["status"] == "complete":
        executed_scopes.add(("closure", max(run["design_generation"], run["implementation_generation"])))
    executed_phases = {phase for phase, _ in executed_scopes}
    missing_primary_scopes = executed_scopes - primary_scopes
    missing_primary = sorted({phase for phase, _ in missing_primary_scopes})
    running = run["status"] in {"initialized", "active"}
    all_segments = [segment for item in bindings for segment in item["segments"]]
    result = {"usage_schema_version": 1, **_summary(bindings, all_segments, bool(missing or missing_primary or running)),
              "running": running,
              "association_coverage": "partial" if bindings and (missing or missing_primary) else "complete" if bindings else "unavailable",
              "missing_primary_phases": missing_primary,
              "missing_executed_attempts": missing, "open_bindings": [item["binding_id"] for item in bindings if not item["closed"]],
              "bindings": [{key: item[key] for key in ("binding_id", "branch_id", "attempt_id", "role", "phase", "generation", "closed")}
                           for item in bindings]}
    result["phases"] = {}
    for phase in PHASES:
        selected = [item for item in bindings if item["phase"] == phase]
        segments = [segment for item in selected for segment in item["segments"] if segment["phase"] == phase]
        phase_missing = any(row["attempt_id"] in missing and STAGE_PHASE.get(row["stage"]) == phase for row in attempts)
        result["phases"][phase] = _summary(selected, segments, phase_missing or phase in missing_primary)
        result["phases"][phase]["executed"] = phase in executed_phases or bool(selected)
    for dimension, field in (("roles", "role"), ("agents", "branch_id"), ("attempts", "attempt_id"), ("generations", "generation")):
        result[dimension] = {}
        group_values = {str(item[field]) for item in bindings if item[field] is not None}
        if field == "role" and missing_primary:
            group_values.add("supervisor")
        if field == "generation":
            group_values.update(str(generation) for _, generation in missing_primary_scopes)
        for value in sorted(group_values):
            selected = [item for item in bindings if str(item[field]) == value]
            group_missing = [row["attempt_id"] for row in attempts if row["attempt_id"] in missing and str(row[field]) == value]
            group_primary = sorted({phase for phase, generation in missing_primary_scopes
                                    if (field == "role" and value == "supervisor")
                                    or (field == "generation" and str(generation) == value)})
            result[dimension][value] = {
                **_summary(selected, [segment for item in selected for segment in item["segments"]], bool(group_missing or group_primary)),
                "missing_executed_attempts": group_missing, "missing_primary_phases": group_primary,
            }
    for dimension, field in (("models", "model"), ("efforts", "effort")):
        result[dimension] = {}
        for value in sorted({segment[field] for segment in all_segments}):
            selected = [item for item in bindings if any(segment[field] == value for segment in item["segments"])]
            result[dimension][value] = _summary(selected, [segment for segment in all_segments if segment[field] == value])
            result[dimension][value]["attribution_scope"] = "observed_intervals_only"
            result[dimension][value]["association_coverage"] = result["association_coverage"]
    result["model_efforts"] = {}
    for model, effort in sorted({(segment["model"], segment["effort"]) for segment in all_segments}):
        selected = [item for item in bindings if any(segment["model"] == model and segment["effort"] == effort for segment in item["segments"])]
        result["model_efforts"][model + "/" + effort] = _summary(
            selected, [segment for segment in all_segments if segment["model"] == model and segment["effort"] == effort])
        result["model_efforts"][model + "/" + effort]["attribution_scope"] = "observed_intervals_only"
        result["model_efforts"][model + "/" + effort]["association_coverage"] = result["association_coverage"]
    result["unattributed"] = _summary(bindings, [item for item in all_segments if item["phase"] == "unattributed"])
    return result
