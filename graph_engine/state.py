"""SQLite persistence, atomic initialization, and idempotent mutations."""

import errno
import getpass
import json
import os
import platform
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from . import ENGINE_VERSION, STATE_SCHEMA_VERSION
from .contracts import ContractError, ensure_safe_components
from .ids import canonical_bytes, repository_digest, sha256_bytes


UNSUPPORTED_POSIX_FILESYSTEMS = {
    "9p", "afs", "ceph", "cifs", "davfs", "gcsfuse", "glusterfs",
    "nfs", "nfs4", "smb3", "sshfs",
}

SemanticValidator = Callable[[sqlite3.Connection, sqlite3.Row], None]


SCHEMA = """
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, repository_id TEXT NOT NULL, repository_digest TEXT NOT NULL,
  repository_path TEXT NOT NULL, repository_device INTEGER NOT NULL, repository_inode INTEGER NOT NULL,
  status TEXT NOT NULL, state_revision INTEGER NOT NULL, engine_version TEXT NOT NULL,
  state_schema_version INTEGER NOT NULL, policy_digest TEXT NOT NULL, policy_json TEXT NOT NULL,
  task_digest TEXT NOT NULL, task_ref TEXT NOT NULL, task_path TEXT NOT NULL, task_json TEXT NOT NULL,
  request_mode TEXT NOT NULL, minimum_route TEXT NOT NULL, selected_route TEXT,
  selected_tags_json TEXT, design_generation INTEGER NOT NULL DEFAULT 0,
  implementation_generation INTEGER NOT NULL DEFAULT 0, durability TEXT NOT NULL,
  durability_detail TEXT NOT NULL, permission_verification TEXT NOT NULL,
  degraded_permissions_ack INTEGER NOT NULL, degraded_durability_ack INTEGER NOT NULL,
  journal_mode TEXT NOT NULL, synchronous TEXT NOT NULL, sqlite_version TEXT NOT NULL,
  local_filesystem TEXT NOT NULL, host_identity TEXT NOT NULL, database_device INTEGER,
  database_inode INTEGER, blocked_reason TEXT, authoritative INTEGER NOT NULL
  ,started_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE execution_plans (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id), size TEXT NOT NULL,
  plan_json TEXT NOT NULL, plan_digest TEXT NOT NULL, status TEXT NOT NULL,
  authority_ref TEXT, approved_at TEXT, approved_by TEXT, approval_digest TEXT
);
CREATE TABLE nodes (
  branch_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), node_instance_id TEXT NOT NULL UNIQUE,
  node_key TEXT NOT NULL, role TEXT NOT NULL, stage TEXT NOT NULL, generation INTEGER NOT NULL,
  mandatory INTEGER NOT NULL, specialist_tag TEXT, status TEXT NOT NULL, retry_count INTEGER NOT NULL,
  max_retries INTEGER NOT NULL, envelope_json TEXT NOT NULL, result_json TEXT, result_digest TEXT,
  failure_code TEXT, reason_code TEXT, started_at TEXT, finished_at TEXT,
  UNIQUE(run_id,node_key,stage,generation,specialist_tag)
);
CREATE TABLE joins (
  join_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), join_key TEXT NOT NULL,
  kind TEXT NOT NULL, stage TEXT NOT NULL, generation INTEGER NOT NULL, status TEXT NOT NULL,
  degraded INTEGER NOT NULL DEFAULT 0, result_json TEXT,
  UNIQUE(run_id,join_key,generation)
);
CREATE TABLE join_members (
  join_id TEXT NOT NULL REFERENCES joins(join_id), branch_id TEXT NOT NULL REFERENCES nodes(branch_id),
  mandatory INTEGER NOT NULL, PRIMARY KEY(join_id,branch_id)
);
CREATE TABLE budgets (
  run_id TEXT NOT NULL REFERENCES runs(run_id), budget_id TEXT NOT NULL, limit_value INTEGER NOT NULL,
  used INTEGER NOT NULL, PRIMARY KEY(run_id,budget_id)
);
CREATE TABLE budget_consumptions (
  run_id TEXT NOT NULL REFERENCES runs(run_id), budget_id TEXT NOT NULL,
  source_branch_id TEXT NOT NULL REFERENCES nodes(branch_id), amount INTEGER NOT NULL,
  PRIMARY KEY(run_id,budget_id,source_branch_id)
);
CREATE TABLE operations (
  run_id TEXT NOT NULL REFERENCES runs(run_id), operation_id TEXT NOT NULL, request_digest TEXT NOT NULL,
  response_json TEXT NOT NULL, resulting_revision INTEGER NOT NULL,
  PRIMARY KEY(run_id,operation_id)
);
CREATE TABLE approvals (
  run_id TEXT NOT NULL REFERENCES runs(run_id), approval_id TEXT NOT NULL, scope_ref TEXT NOT NULL,
  decision TEXT NOT NULL, authority_ref TEXT NOT NULL, artifact_sha256 TEXT NOT NULL,
  PRIMARY KEY(run_id,approval_id)
);
CREATE TABLE approval_attestations (
  run_id TEXT NOT NULL REFERENCES runs(run_id), approval_id TEXT NOT NULL,
  actor TEXT NOT NULL, host_identity TEXT NOT NULL, approved_at TEXT NOT NULL,
  approval_digest TEXT NOT NULL, PRIMARY KEY(run_id,approval_id),
  FOREIGN KEY(run_id,approval_id) REFERENCES approvals(run_id,approval_id)
);
CREATE TABLE acceptance_evidence (
  run_id TEXT NOT NULL REFERENCES runs(run_id), criterion_id TEXT NOT NULL, artifact_ref TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL, PRIMARY KEY(run_id,criterion_id)
);
CREATE TABLE check_evidence (
  run_id TEXT NOT NULL REFERENCES runs(run_id), check_id TEXT NOT NULL, outcome TEXT NOT NULL,
  artifact_ref TEXT NOT NULL, artifact_sha256 TEXT NOT NULL, PRIMARY KEY(run_id,check_id)
);
CREATE TABLE events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(run_id),
  revision INTEGER NOT NULL, event_type TEXT NOT NULL, source_id TEXT, detail_json TEXT NOT NULL
);
CREATE TABLE artifacts (
  ref TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), kind TEXT NOT NULL,
  sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, source_type TEXT NOT NULL,
  source_path TEXT, content_json TEXT, device INTEGER, inode INTEGER, immutable INTEGER NOT NULL,
  UNIQUE(run_id,kind,sha256,ref)
);
CREATE TABLE fanouts (
  fanout_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
  stage TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>=0),
  status TEXT NOT NULL CHECK(status IN ('awaiting','assessed')),
  member_branch_ids_json TEXT NOT NULL,
  assessment_ref TEXT REFERENCES artifacts(ref) ON DELETE RESTRICT,
  assessment_digest TEXT, authority_ref TEXT, actor TEXT, host_identity TEXT, assessed_at TEXT,
  UNIQUE(run_id,stage,generation),
  CHECK(
    (status='awaiting' AND assessment_ref IS NULL AND assessment_digest IS NULL AND authority_ref IS NULL
      AND actor IS NULL AND host_identity IS NULL AND assessed_at IS NULL)
    OR
    (status='assessed' AND assessment_ref IS NOT NULL AND assessment_digest IS NOT NULL
      AND authority_ref IS NOT NULL AND actor IS NOT NULL AND host_identity IS NOT NULL AND assessed_at IS NOT NULL)
  )
);
CREATE TABLE fanout_dependencies (
  fanout_id TEXT NOT NULL REFERENCES fanouts(fanout_id) ON DELETE RESTRICT,
  before_branch_id TEXT NOT NULL REFERENCES nodes(branch_id) ON DELETE RESTRICT,
  after_branch_id TEXT NOT NULL REFERENCES nodes(branch_id) ON DELETE RESTRICT,
  reason TEXT NOT NULL,
  PRIMARY KEY(fanout_id,before_branch_id,after_branch_id),
  CHECK(before_branch_id<>after_branch_id)
);
CREATE TABLE branch_attempts (
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
  branch_id TEXT NOT NULL REFERENCES nodes(branch_id) ON DELETE RESTRICT,
  attempt_number INTEGER NOT NULL CHECK(attempt_number>0), attempt_id TEXT NOT NULL,
  claim_digest TEXT NOT NULL CHECK(length(claim_digest)=64), started_at TEXT NOT NULL,
  finished_at TEXT, outcome TEXT,
  PRIMARY KEY(branch_id,attempt_number), UNIQUE(run_id,attempt_id),
  CHECK((finished_at IS NULL AND outcome IS NULL) OR (finished_at IS NOT NULL AND outcome IS NOT NULL))
);
CREATE TRIGGER fanout_transition_guard BEFORE UPDATE ON fanouts
BEGIN
  SELECT CASE
    WHEN OLD.status<>'awaiting' OR NEW.status<>'assessed'
      OR OLD.fanout_id<>NEW.fanout_id OR OLD.run_id<>NEW.run_id OR OLD.stage<>NEW.stage
      OR OLD.generation<>NEW.generation OR OLD.member_branch_ids_json<>NEW.member_branch_ids_json
    THEN RAISE(ABORT,'FANOUT_IMMUTABLE')
  END;
END;
CREATE TRIGGER fanout_insert_guard BEFORE INSERT ON fanouts WHEN NEW.status<>'awaiting'
BEGIN SELECT RAISE(ABORT,'FANOUT_IMMUTABLE'); END;
CREATE TRIGGER fanout_delete_guard BEFORE DELETE ON fanouts
BEGIN SELECT RAISE(ABORT,'FANOUT_IMMUTABLE'); END;
CREATE TRIGGER fanout_dependency_update_guard BEFORE UPDATE ON fanout_dependencies
BEGIN SELECT RAISE(ABORT,'FANOUT_DEPENDENCY_IMMUTABLE'); END;
CREATE TRIGGER fanout_dependency_insert_guard BEFORE INSERT ON fanout_dependencies
WHEN (SELECT status FROM fanouts WHERE fanout_id=NEW.fanout_id)<>'awaiting'
BEGIN SELECT RAISE(ABORT,'FANOUT_DEPENDENCY_IMMUTABLE'); END;
CREATE TRIGGER fanout_dependency_delete_guard BEFORE DELETE ON fanout_dependencies
BEGIN SELECT RAISE(ABORT,'FANOUT_DEPENDENCY_IMMUTABLE'); END;
CREATE TRIGGER branch_attempt_identity_guard BEFORE UPDATE ON branch_attempts
BEGIN
  SELECT CASE
    WHEN OLD.run_id<>NEW.run_id OR OLD.branch_id<>NEW.branch_id
      OR OLD.attempt_number<>NEW.attempt_number OR OLD.attempt_id<>NEW.attempt_id
      OR OLD.claim_digest<>NEW.claim_digest OR OLD.started_at<>NEW.started_at
      OR OLD.finished_at IS NOT NULL OR (NEW.finished_at IS NULL)<>(NEW.outcome IS NULL)
    THEN RAISE(ABORT,'ATTEMPT_IMMUTABLE')
  END;
END;
CREATE TRIGGER branch_attempt_delete_guard BEFORE DELETE ON branch_attempts
BEGIN SELECT RAISE(ABORT,'ATTEMPT_IMMUTABLE'); END;
"""

MUTATION_RUN_STATES = {
    "next.claim": {"initialized", "active"},
    "record.branch-result": {"initialized", "active"},
    "record.timeout": {"initialized", "active"},
    "record.skip": {"active"},
    "record.retry": {"initialized", "active"},
    "record.approval": {"initialized", "active"},
    "record.plan-approval": {"initialized"},
    "record.heartbeat": {"initialized", "active"},
    "record.budget-use": {"initialized", "active"},
    "record.acceptance-evidence": {"active"},
    "record.check-evidence": {"active"},
    "record.fanout-assessment": {"active"},
    "check.run": {"active"},
    "join.advance": {"active"},
    "complete": {"active"},
    "block": {"initialized", "active"},
    "abort": {"initialized", "active", "blocked"},
}


class StateError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def current_actor() -> str:
    return getpass.getuser() or "unknown-user"


def installed_codex_home() -> Path:
    resolved = Path(__file__).resolve()
    for parent in resolved.parents:
        if parent.name == ".codex":
            return parent
    raise StateError("CODEX_PROFILE_ROOT_NOT_FOUND")


def current_host_identity() -> str:
    value = "\0".join((platform.system(), platform.node(), platform.machine(), getpass.getuser()))
    return sha256_bytes(b"graph-host-v1\0" + value.encode("utf-8"))


def _process_alive(process_id: int) -> bool:
    if process_id <= 0:
        return False
    if process_id == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, process_id)
        if not process:
            return False
        ctypes.windll.kernel32.CloseHandle(process)
        return True
    try:
        os.kill(process_id, 0)
    except OSError as error:
        return error.errno == errno.EPERM
    return True


def repository_identity(repo: Path) -> Tuple[int, int, str]:
    resolved = repo.resolve(strict=True)
    ensure_safe_components(resolved)
    info = resolved.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ContractError("repo", "NOT_DIRECTORY")
    local_filesystem_identity(resolved)
    return int(info.st_dev), int(info.st_ino), str(resolved)


def _linux_filesystem_type(path: Path) -> Optional[str]:
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        return None
    resolved = str(path.resolve(strict=True))
    best_mount = ""
    best_type: Optional[str] = None
    try:
        lines = mountinfo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        fields = before.split()
        trailing = after.split()
        if len(fields) < 5 or not trailing:
            continue
        mount_point = fields[4].replace("\\040", " ").replace("\\134", "\\")
        try:
            Path(resolved).relative_to(Path(mount_point))
        except ValueError:
            continue
        if len(mount_point) >= len(best_mount):
            best_mount = mount_point
            best_type = trailing[0]
    return best_type


def local_filesystem_identity(path: Path) -> str:
    resolved = path.resolve(strict=True)
    if os.name == "nt":
        text = str(resolved)
        if text.startswith("\\\\"):
            raise StateError("NON_LOCAL_FILESYSTEM")
        import ctypes
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(resolved.anchor)
        if drive_type != 3:  # DRIVE_FIXED
            raise StateError("NON_LOCAL_FILESYSTEM")
        return "windows_fixed_drive:" + resolved.anchor.rstrip("\\").upper()
    fs_type = _linux_filesystem_type(resolved)
    if fs_type is not None and (fs_type in UNSUPPORTED_POSIX_FILESYSTEMS or fs_type.startswith("fuse")):
        raise StateError("NON_LOCAL_FILESYSTEM")
    return "posix_local:" + (fs_type or "lock_probe") + ":" + str(resolved.stat().st_dev)


class StateStore:
    def __init__(self, codex_home: Optional[Path] = None, fault_hook: Optional[Callable[[str], None]] = None):
        self.codex_home = (codex_home or installed_codex_home()).absolute()
        self.fault_hook = fault_hook or (lambda _point: None)

    def run_root(self, repository_id: str, run_id: str) -> Path:
        return self.codex_home / "graph-runs" / repository_digest(repository_id) / run_id

    def inbox_root(self, repository_id: str, run_id: str) -> Path:
        return self.codex_home / "graph-inbox" / repository_digest(repository_id) / run_id

    def db_path(self, repository_id: str, run_id: str) -> Path:
        return self.run_root(repository_id, run_id) / "state.sqlite3"

    def _mkdir_private(self, path: Path) -> None:
        ensure_safe_components(self.codex_home)
        current = self.codex_home
        current.mkdir(parents=True, exist_ok=True)
        for part in path.relative_to(self.codex_home).parts:
            current = current / part
            if current.exists():
                ensure_safe_components(current, self.codex_home)
            else:
                current.mkdir(mode=0o700)
            if os.name != "nt":
                os.chmod(current, 0o700)
                info = current.stat()
                if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise StateError("PERMISSION_VERIFICATION_FAILED")

    def _verify_private_directory(self, path: Path) -> os.stat_result:
        ensure_safe_components(path, self.codex_home)
        try:
            info = path.lstat()
        except OSError:
            raise StateError("STATE_DIRECTORY_INVALID")
        if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
            raise StateError("STATE_DIRECTORY_INVALID")
        if os.name != "nt" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
            raise StateError("PERMISSION_VERIFICATION_FAILED")
        return info

    def verify_state_paths(
        self, repository_id: str, run_id: str, expected_locality: Optional[str] = None
    ) -> str:
        ensure_safe_components(self.codex_home)
        locality = local_filesystem_identity(self.codex_home)
        if expected_locality is not None and locality != expected_locality:
            raise StateError("FILESYSTEM_IDENTITY_CHANGED")
        run_info = self._verify_private_directory(self.run_root(repository_id, run_id))
        inbox_path = self.inbox_root(repository_id, run_id)
        inbox_info = self._verify_private_directory(inbox_path)
        if run_info.st_dev != inbox_info.st_dev:
            raise StateError("STATE_DIRECTORY_INVALID")
        for entry in inbox_path.iterdir():
            ensure_safe_components(entry, inbox_path)
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode) or entry.is_symlink():
                raise StateError("INBOX_ENTRY_INVALID")
            if os.name != "nt" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
                raise StateError("PERMISSION_VERIFICATION_FAILED")
        return locality

    def verify_inbox_manifest(self, repository_id: str, run_id: str, path: Path) -> None:
        self.verify_state_paths(repository_id, run_id)
        inbox = self.inbox_root(repository_id, run_id).absolute()
        candidate = path.absolute()
        if candidate.parent != inbox:
            raise ContractError("path", "OUTSIDE_FIXED_INBOX")
        ensure_safe_components(candidate, inbox)
        try:
            info = candidate.lstat()
        except OSError:
            raise ContractError("path", "NOT_REGULAR_FILE")
        if not stat.S_ISREG(info.st_mode) or candidate.is_symlink():
            raise ContractError("path", "NOT_REGULAR_FILE")
        if os.name != "nt" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise StateError("PERMISSION_VERIFICATION_FAILED")

    def _write_incomplete_marker(
        self, marker: Path, payload: Mapping[str, Any], acknowledged: bool
    ) -> str:
        data = canonical_bytes(payload)
        descriptor = os.open(
            str(marker), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600
        )
        try:
            offset = 0
            while offset < len(data):
                offset += os.write(descriptor, data[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if os.name != "nt":
            os.chmod(marker, 0o600)
        return self._directory_sync(marker.parent, acknowledged)

    def _incomplete_database_request_digest(self, path: Path, run_id: str) -> str:
        try:
            with self.connect(path) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise StateError("INCOMPLETE_INIT_CORRUPT")
                runs = connection.execute(
                    "SELECT run_id,authoritative FROM runs"
                ).fetchall()
                operations = connection.execute(
                    "SELECT run_id,operation_id,request_digest FROM operations"
                ).fetchall()
                if (len(runs) != 1 or runs[0]["run_id"] != run_id or runs[0]["authoritative"] != 0
                        or len(operations) != 1 or operations[0]["run_id"] != run_id
                        or len(operations[0]["request_digest"]) != 64):
                    raise StateError("INCOMPLETE_INIT_CORRUPT")
                return operations[0]["request_digest"]
        except sqlite3.DatabaseError:
            raise StateError("INCOMPLETE_INIT_CORRUPT")

    def _probe_sqlite_locking(self, path: Path) -> None:
        self.fault_hook("locking_probe")
        first = sqlite3.connect(str(path), timeout=0, isolation_level=None)
        second = sqlite3.connect(str(path), timeout=0, isolation_level=None)
        try:
            first.execute("BEGIN IMMEDIATE")
            try:
                second.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                if "locked" not in str(error).lower():
                    raise StateError("SQLITE_LOCK_PROBE_FAILED")
            else:
                second.rollback()
                raise StateError("SQLITE_LOCK_PROBE_FAILED")
            first.rollback()
            second.execute("BEGIN IMMEDIATE")
            second.rollback()
        except sqlite3.DatabaseError:
            raise StateError("SQLITE_LOCK_PROBE_FAILED")
        finally:
            first.close()
            second.close()

    def _directory_sync(self, directory: Path, acknowledged: bool) -> str:
        self.fault_hook("directory_sync")
        try:
            descriptor = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError as error:
            if os.name == "nt" and error.errno in {errno.EACCES, errno.EINVAL, errno.ENOTSUP, errno.EPERM}:
                if not acknowledged:
                    raise StateError("DEGRADED_DURABILITY_ACK_REQUIRED")
                return "directory_fsync_unavailable_windows"
            raise StateError("DIRECTORY_SYNC_FAILED")
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno in {errno.EINVAL, errno.ENOTSUP}:
                if not acknowledged:
                    raise StateError("DEGRADED_DURABILITY_ACK_REQUIRED")
                return "directory_fsync_unsupported"
            raise StateError("DIRECTORY_SYNC_FAILED")
        finally:
            os.close(descriptor)
        return "verified"

    def initialize(
        self,
        repo: Path,
        policy: Mapping[str, Any],
        policy_digest: str,
        task: Mapping[str, Any],
        task_path: Path,
        task_digest: str,
        run_id: str,
        op_id: str,
        request_digest: str,
        ack_permissions: bool,
        ack_durability: bool,
        bootstrap_row: Mapping[str, Any],
        execution_plan: Mapping[str, Any],
        task_ref: str,
        initial_artifacts: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        run_root = self.run_root(policy["repository_id"], run_id)
        inbox = self.inbox_root(policy["repository_id"], run_id)
        self._mkdir_private(run_root)
        self._mkdir_private(inbox)
        filesystem_identity = self.verify_state_paths(policy["repository_id"], run_id)
        permission_state = "verified"
        if os.name == "nt":
            permission_state = "DEGRADED_PERMISSION_VERIFICATION"
            if not ack_permissions:
                raise StateError("DEGRADED_PERMISSION_ACK_REQUIRED")
        final_path = run_root / "state.sqlite3"
        incomplete_markers = sorted(run_root.glob("*.incomplete.sqlite3.marker"))
        marker_digests: List[str] = []
        marker_corrupt = False
        for marker in incomplete_markers:
            try:
                incomplete = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                marker_corrupt = True
                continue
            marker_digest = incomplete.get("request_digest")
            if not isinstance(marker_digest, str) or len(marker_digest) != 64:
                marker_corrupt = True
                continue
            marker_digests.append(marker_digest)
        if final_path.exists():
            try:
                with self.open_run(policy["repository_id"], run_id) as connection:
                    operation = connection.execute(
                        "SELECT request_digest,response_json,resulting_revision FROM operations WHERE run_id=? AND operation_id=?",
                        (run_id, op_id),
                    ).fetchone()
                    if operation and operation["request_digest"] == request_digest:
                        result = json.loads(operation["response_json"])
                        result["code"] = "REPLAYED"
                        return result
                    if operation:
                        raise StateError("OPERATION_CONFLICT")
                raise StateError("RUN_ALREADY_EXISTS")
            except StateError as error:
                if error.code != "NON_AUTHORITATIVE_STATE":
                    raise
                database_request_digest = self._incomplete_database_request_digest(final_path, run_id)
                if database_request_digest != request_digest:
                    raise StateError("INCOMPLETE_INIT_CONFLICT")
                if marker_digests and any(item != database_request_digest for item in marker_digests):
                    raise StateError("INCOMPLETE_INIT_CORRUPT")
                failed_path = run_root / (".state.failed." + next(tempfile._get_candidate_names()) + ".sqlite3")
                os.replace(str(final_path), str(failed_path))
        elif marker_corrupt:
            raise StateError("INCOMPLETE_INIT_CORRUPT")
        elif marker_digests and any(item != request_digest for item in marker_digests):
            raise StateError("INCOMPLETE_INIT_CONFLICT")
        device, inode, repo_path = repository_identity(repo)
        lock_path = run_root / ".init.lock"
        lock_record = {"schema_version": 1, "host_identity": current_host_identity(), "process_id": os.getpid(), "request_digest": request_digest}
        for attempt in range(2):
            try:
                lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(lock_fd, canonical_bytes(lock_record))
                os.fsync(lock_fd)
                os.close(lock_fd)
                break
            except FileExistsError:
                if attempt:
                    raise StateError("INITIALIZATION_CONFLICT")
                try:
                    existing_lock = json.loads(lock_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raise StateError("INITIALIZATION_CONFLICT")
                if (existing_lock.get("host_identity") != current_host_identity() or
                        _process_alive(existing_lock.get("process_id", -1))):
                    raise StateError("INITIALIZATION_CONFLICT")
                try:
                    lock_path.unlink()
                except OSError:
                    raise StateError("INITIALIZATION_CONFLICT")
        temporary = run_root / (".state." + next(tempfile._get_candidate_names()) + ".incomplete.sqlite3")
        incomplete_marker = temporary.with_suffix(temporary.suffix + ".marker")
        connection: Optional[sqlite3.Connection] = None
        try:
            marker_sync = self._write_incomplete_marker(incomplete_marker, {
                "schema_version": 1, "request_digest": request_digest,
                "operation_id": op_id, "failure_code": "INITIALIZING",
            }, ack_durability)
            connection = sqlite3.connect(str(temporary), isolation_level=None)
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            task_json = json.dumps(task, sort_keys=True, separators=(",", ":"))
            policy_json = json.dumps(policy, sort_keys=True, separators=(",", ":"))
            row = (
                run_id, policy["repository_id"], repository_digest(policy["repository_id"]), repo_path,
                device, inode, "initialized", 1, ENGINE_VERSION, STATE_SCHEMA_VERSION, policy_digest,
                policy_json, task_digest, task_ref, str(task_path), task_json, task["request_mode"],
                task["minimum_route"], "degraded" if ack_durability and os.name == "nt" else "verified",
                "pending_final_verification", permission_state, int(ack_permissions), int(ack_durability),
                "delete", "FULL", sqlite3.sqlite_version, "pending", current_host_identity(), None, None, 0,
            )
            connection.execute(
                """INSERT INTO runs(
                run_id,repository_id,repository_digest,repository_path,repository_device,repository_inode,
                status,state_revision,engine_version,state_schema_version,policy_digest,policy_json,task_digest,
                task_ref,task_path,task_json,request_mode,minimum_route,durability,durability_detail,
                permission_verification,degraded_permissions_ack,degraded_durability_ack,journal_mode,
                synchronous,sqlite_version,local_filesystem,host_identity,database_device,database_inode,
                authoritative,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                row + (utc_now(), None),
            )
            connection.execute(
                "INSERT INTO execution_plans(run_id,size,plan_json,plan_digest,status) VALUES(?,?,?,?,?)",
                (
                    run_id, execution_plan["size"],
                    json.dumps(execution_plan, sort_keys=True, separators=(",", ":")),
                    execution_plan["plan_digest"], "pending",
                ),
            )
            for artifact in initial_artifacts:
                connection.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        artifact["ref"], run_id, artifact["kind"], artifact["sha256"], artifact["size_bytes"],
                        artifact["source_type"], artifact.get("source_path"), artifact.get("content_json"),
                        artifact.get("device"), artifact.get("inode"), 1,
                    ),
                )
            self._insert_node(connection, run_id, bootstrap_row)
            for budget_id, limit_value in (
                ("design_revisions", policy["limits"]["design_revisions"]),
                ("delivery_repairs", policy["limits"]["delivery_repairs"]),
                ("file_reads", task["inspection_budget"]["file_reads"]),
                ("discovery_commands", task["inspection_budget"]["discovery_commands"]),
            ):
                connection.execute("INSERT INTO budgets VALUES(?,?,?,0)", (run_id, budget_id, limit_value))
            response = {
                "schema_version": 1, "ok": True, "code": "INITIALIZED", "run_id": run_id,
                "state_revision": 1, "status": "initialized", "branch": json.loads(bootstrap_row["envelope_json"]),
                "execution_plan": dict(execution_plan), "execution_plan_digest": execution_plan["plan_digest"],
                "execution_plan_status": "pending", "approval_required": True,
                "inbox": str(inbox), "permission_verification": permission_state,
            }
            connection.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?)",
                (run_id, op_id, request_digest, json.dumps(response, sort_keys=True), 1),
            )
            connection.execute(
                "INSERT INTO events(run_id,revision,event_type,source_id,detail_json) VALUES(?,?,?,?,?)",
                (run_id, 1, "init", op_id, "{}"),
            )
            connection.commit()
            connection.close()
            connection = None
            self._probe_sqlite_locking(temporary)
            if os.name != "nt":
                os.chmod(temporary, 0o600)
                file_info = temporary.stat()
                if file_info.st_uid != os.geteuid() or stat.S_IMODE(file_info.st_mode) != 0o600:
                    raise StateError("PERMISSION_VERIFICATION_FAILED")
            self.fault_hook("database_file_flush")
            fd = os.open(str(temporary), os.O_RDWR | getattr(os, "O_BINARY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            first_sync = self._directory_sync(run_root, ack_durability)
            self.fault_hook("replace")
            os.replace(str(temporary), str(final_path))
            self.fault_hook("post_replace")
            second_sync = self._directory_sync(run_root, ack_durability)
            self.fault_hook("reopen")
            with self.connect(final_path) as verified:
                self.fault_hook("identity_verification")
                if not final_path.is_file():
                    raise StateError("DATABASE_IDENTITY_FAILED")
                database_info = final_path.stat()
                self.fault_hook("integrity_check")
                if verified.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise StateError("INTEGRITY_CHECK_FAILED")
                journal = verified.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower()
                if journal not in {"wal", "delete"}:
                    raise StateError("UNSUPPORTED_JOURNAL_MODE")
                verified.execute("PRAGMA synchronous=FULL")
                sync = verified.execute("PRAGMA synchronous").fetchone()[0]
                if sync != 2:
                    raise StateError("SYNCHRONOUS_NOT_FULL")
                degraded_detail = next(
                    (item for item in (marker_sync, first_sync, second_sync) if item != "verified"),
                    "verified",
                )
                durability = "degraded" if degraded_detail != "verified" else "verified"
                verified.execute("BEGIN IMMEDIATE")
                verified.execute(
                    "UPDATE runs SET journal_mode=?,synchronous='FULL',durability=?,durability_detail=?,local_filesystem=?,database_device=?,database_inode=?,authoritative=1 WHERE run_id=?",
                    (journal, durability, degraded_detail, filesystem_identity, int(database_info.st_dev), int(database_info.st_ino), run_id),
                )
                response["durability"] = durability
                response["durability_detail"] = degraded_detail
                verified.execute(
                    "UPDATE operations SET response_json=? WHERE run_id=? AND operation_id=?",
                    (json.dumps(response, sort_keys=True), run_id, op_id),
                )
                verified.commit()
            for marker in incomplete_markers:
                try:
                    marker.unlink()
                except OSError:
                    pass
            try:
                incomplete_marker.unlink()
            except OSError:
                pass
            return response
        except Exception as error:
            if connection is not None:
                connection.close()
            try:
                self._write_incomplete_marker(incomplete_marker, {
                    "schema_version": 1,
                    "request_digest": request_digest,
                    "operation_id": op_id,
                    "failure_code": getattr(error, "code", "INIT_FAILURE"),
                }, ack_durability)
            except (OSError, StateError):
                pass
            if final_path.exists():
                failed_path = run_root / (".state.failed." + next(tempfile._get_candidate_names()) + ".sqlite3")
                try:
                    os.replace(str(final_path), str(failed_path))
                except OSError:
                    pass
            raise
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass

    @contextmanager
    def connect(self, path: Path) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
        finally:
            connection.close()

    def open_run(self, repository_id: str, run_id: str) -> Iterator[sqlite3.Connection]:
        path = self.db_path(repository_id, run_id)
        locality = self.verify_state_paths(repository_id, run_id)
        ensure_safe_components(path, self.codex_home)
        if not path.is_file() or path.is_symlink():
            raise StateError("RUN_NOT_FOUND")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024 * 1024:
            raise StateError("DATABASE_FILE_INVALID")
        if os.name != "nt" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise StateError("PERMISSION_VERIFICATION_FAILED")
        return self._verified_connection(path, info, locality)

    @contextmanager
    def _verified_connection(
        self, path: Path, info: os.stat_result, locality: str
    ) -> Iterator[sqlite3.Connection]:
        try:
            with self.connect(path) as connection:
                run = connection.execute("SELECT * FROM runs LIMIT 1").fetchone()
                if run is None or run["authoritative"] != 1:
                    raise StateError("NON_AUTHORITATIVE_STATE")
                if (run["database_device"], run["database_inode"]) != (int(info.st_dev), int(info.st_ino)):
                    raise StateError("DATABASE_IDENTITY_FAILED")
                if run["local_filesystem"] != locality:
                    raise StateError("FILESYSTEM_IDENTITY_CHANGED")
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise StateError("INTEGRITY_CHECK_FAILED")
                journal = connection.execute("PRAGMA journal_mode").fetchone()[0].lower()
                synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
                if journal not in {"wal", "delete"} or journal != run["journal_mode"] or synchronous != 2 or run["synchronous"] != "FULL":
                    raise StateError("DURABILITY_STATE_INVALID")
                if run["durability"] not in {"verified", "degraded"} or (run["durability"] == "degraded" and not run["degraded_durability_ack"]):
                    raise StateError("DURABILITY_STATE_INVALID")
                if run["permission_verification"] == "DEGRADED_PERMISSION_VERIFICATION" and not run["degraded_permissions_ack"]:
                    raise StateError("PERMISSION_VERIFICATION_FAILED")
                yield connection
        except sqlite3.DatabaseError:
            raise StateError("DATABASE_STATE_INVALID")

    def mutate(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        op_id: str,
        request: Mapping[str, Any],
        action: Callable[[sqlite3.Connection, sqlite3.Row, int], Dict[str, Any]],
        *,
        semantic_validator: SemanticValidator,
    ) -> Dict[str, Any]:
        request_digest = sha256_bytes(canonical_bytes(request))
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise StateError("TRANSACTION_CONFLICT")
        try:
            previous = connection.execute(
                "SELECT * FROM operations WHERE run_id=? AND operation_id=?", (run_id, op_id)
            ).fetchone()
            if previous:
                connection.rollback()
                if previous["request_digest"] != request_digest:
                    raise StateError("OPERATION_CONFLICT")
                result = json.loads(previous["response_json"])
                result["code"] = "REPLAYED"
                return result
            run = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise StateError("RUN_NOT_FOUND")
            command = request["command"]
            status = run["status"]
            allowed_states = MUTATION_RUN_STATES.get(command)
            if allowed_states is None:
                raise StateError("UNKNOWN_MUTATION")
            if status not in allowed_states:
                if status in {"complete", "aborted"}:
                    raise StateError("TERMINAL_RUN")
                if status == "blocked":
                    raise StateError("GRAPH_BLOCKED")
                raise StateError("INVALID_RUN_TRANSITION")
            semantic_validator(connection, run)
            revision = int(run["state_revision"]) + 1
            result = action(connection, run, revision)
            result.update({"schema_version": 1, "ok": True, "run_id": run_id, "state_revision": revision})
            self.fault_hook("before_commit")
            connection.execute("UPDATE runs SET state_revision=? WHERE run_id=?", (revision, run_id))
            connection.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?)",
                (run_id, op_id, request_digest, json.dumps(result, sort_keys=True), revision),
            )
            connection.execute(
                "INSERT INTO events(run_id,revision,event_type,source_id,detail_json) VALUES(?,?,?,?,?)",
                (run_id, revision, request["command"], op_id, json.dumps(request, sort_keys=True)),
            )
            updated_run = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            semantic_validator(connection, updated_run)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _insert_node(connection: sqlite3.Connection, run_id: str, row: Mapping[str, Any]) -> None:
        connection.execute(
            """INSERT INTO nodes(branch_id,run_id,node_instance_id,node_key,role,stage,generation,
            mandatory,specialist_tag,status,retry_count,max_retries,envelope_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["branch_id"], run_id, row["node_instance_id"], row["node_key"], row["role"],
                row["stage"], row["generation"], int(row["mandatory"]), row.get("specialist_tag"),
                row["status"], row["retry_count"], row["max_retries"], row["envelope_json"],
            ),
        )

    @staticmethod
    def insert_join(connection: sqlite3.Connection, run_id: str, row: Mapping[str, Any], members: Sequence[Mapping[str, Any]]) -> None:
        connection.execute(
            "INSERT INTO joins(join_id,run_id,join_key,kind,stage,generation,status) VALUES(?,?,?,?,?,?,?)",
            (row["join_id"], run_id, row["join_key"], row["kind"], row["stage"], row["generation"], "open"),
        )
        for member in members:
            connection.execute(
                "INSERT INTO join_members VALUES(?,?,?)",
                (row["join_id"], member["branch_id"], int(member["mandatory"])),
            )

    @staticmethod
    def row_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in row.keys()}
