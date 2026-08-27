import threading
import time
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

from graph_engine.cli import execute
from graph_engine.contracts import ContractError
from graph_engine.evidence import canonical_ledger_artifact, persist_artifact, resolve_reference
from graph_engine.state import (
    StateError, StateStore, current_host_identity, installed_codex_home,
    local_filesystem_identity,
)

from test_support import GraphCase


class StateTests(GraphCase):
    def test_oversized_ledger_artifact_fails_resolution_status_and_resume(self):
        policy_path = self.repo / ".codex" / "engineering-graph.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["artifact_kinds"]["collection"]["max_bytes"] = 1024
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        self.policy_bytes = policy_path.read_bytes()
        self.initialize()

        marker = "private-collection-content"
        oversized = canonical_ledger_artifact(
            "corrupt-collection", "collection", {"payload": marker + ("x" * 2048)},
        )
        self.assertGreater(oversized.size_bytes, 1024)
        database = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(database) as connection:
            persist_artifact(connection, "RUN-1", oversized)
            connection.commit()
            with self.assertRaises(ContractError) as resolution:
                resolve_reference(
                    oversized.ref, oversized.sha256, oversized.kind,
                    self.repo, Path(__file__).parents[1], policy, connection,
                )
        self.assertEqual(resolution.exception.code, "FILE_TOO_LARGE")
        self.assertNotIn(marker, str(resolution.exception))

        for command in (
            ("status", "--run-id", "RUN-1"),
            (
                "resume", "--run-id", "RUN-1", "--ack-degraded-permissions",
                "--ack-degraded-durability",
            ),
        ):
            with self.subTest(command=command[0]):
                with self.assertRaises(ContractError) as captured:
                    self.graphctl(*command)
                self.assertEqual(
                    (captured.exception.field, captured.exception.code),
                    ("artifact_ref", "FILE_TOO_LARGE"),
                )
                self.assertNotIn(marker, str(captured.exception))

    def test_init_and_identical_operation_are_idempotent(self):
        first = self.initialize()
        self.assertEqual(first["permission_verification"], "DEGRADED_PERMISSION_VERIFICATION" if __import__("os").name == "nt" else "verified")
        second = self.graphctl("--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(self.repo / "docs" / "task.json"), "--op-id", "init-1")
        self.assertEqual(first["state_revision"], second["state_revision"])
        self.assertEqual(second["code"], "REPLAYED")

    def test_windows_permission_degradation_requires_acknowledgment(self):
        if __import__("os").name != "nt":
            self.skipTest("Windows-specific degraded permission contract")
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(__import__("json").dumps(self.task()), encoding="utf-8")
        with self.assertRaisesRegex(StateError, "DEGRADED_PERMISSION_ACK_REQUIRED"):
            execute(["--repo", str(self.repo), "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "init-no-permission-ack"], self.store)

    def test_resume_consumes_host_bound_degraded_acknowledgments(self):
        self.initialize()
        if __import__("os").name == "nt":
            with self.assertRaisesRegex(StateError, "DEGRADED_PERMISSION_ACK_REQUIRED"):
                self.graphctl("resume", "--run-id", "RUN-1")
        resumed = self.graphctl("resume", "--run-id", "RUN-1", "--ack-degraded-permissions", "--ack-degraded-durability")
        self.assertEqual(resumed["acknowledgments"]["host_identity"], current_host_identity())
        self.assertTrue(resumed["acknowledgments"]["degraded_permissions"])

    def test_acknowledged_degraded_directory_sync_is_recorded(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        degraded = StateStore(self.root / "degraded-codex")
        degraded._directory_sync = lambda _path, acknowledged: "simulated_directory_sync_unavailable" if acknowledged else self.fail("ack not supplied")
        result = execute(["--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "degraded-op"], degraded)[0]
        self.assertEqual((result["durability"], result["durability_detail"]), ("degraded", "simulated_directory_sync_unavailable"))
        with degraded.open_run("albanian-live-translate", "RUN-1") as connection:
            run = connection.execute("SELECT * FROM runs").fetchone()
            self.assertEqual((run["degraded_durability_ack"], run["host_identity"]), (1, current_host_identity()))

    def test_changed_operation_id_payload_conflicts_without_mutation(self):
        self.initialize()
        first = self.graphctl("next", "--run-id", "RUN-1", "--claim", "--op-id", "same-op")
        with self.assertRaisesRegex(StateError, "OPERATION_CONFLICT"):
            self.graphctl("abort", "--run-id", "RUN-1", "--reason-code", "STOP", "--authority-ref", "authority:test", "--op-id", "same-op")
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(status["state_revision"], first["state_revision"])

    def test_fault_before_commit_leaves_claim_ready(self):
        self.initialize()
        faulting = StateStore(self.store.codex_home, lambda point: (_ for _ in ()).throw(RuntimeError("fault")) if point == "before_commit" else None)
        with self.assertRaisesRegex(RuntimeError, "fault"):
            execute(["--repo", str(self.repo), "next", "--run-id", "RUN-1", "--claim", "--op-id", "fault-op"], faulting)
        status = self.graphctl("status", "--run-id", "RUN-1")
        self.assertEqual(status["state_revision"], 1)
        self.assertEqual(status["branches"][0]["status"], "ready")

    def test_initialization_fault_never_leaves_authoritative_database(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(__import__("json").dumps(self.task()), encoding="utf-8")
        faulting = StateStore(self.root / "fault-codex", lambda point: (_ for _ in ()).throw(RuntimeError("flush")) if point == "database_file_flush" else None)
        with self.assertRaisesRegex(RuntimeError, "flush"):
            execute(["--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "init-fault"], faulting)
        self.assertFalse(faulting.db_path("albanian-live-translate", "RUN-1").exists())

    def test_all_initialization_fault_points_fail_closed(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(__import__("json").dumps(self.task()), encoding="utf-8")
        for point in (
            "locking_probe", "database_file_flush", "directory_sync", "replace",
            "post_replace", "reopen", "identity_verification", "integrity_check",
        ):
            with self.subTest(point=point):
                home = self.root / ("fault-" + point)
                faulting = StateStore(home, lambda actual, expected=point: (_ for _ in ()).throw(RuntimeError(expected)) if actual == expected else None)
                with self.assertRaises(RuntimeError):
                    execute(["--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "init-" + point], faulting)
                self.assertFalse(faulting.db_path("albanian-live-translate", "RUN-1").exists())

    def test_post_replace_failure_is_recoverable_only_by_identical_init(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        home = self.root / "recover-codex"
        faulting = StateStore(home, lambda point: (_ for _ in ()).throw(RuntimeError("death")) if point == "post_replace" else None)
        argv = ["--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "recover-op"]
        with self.assertRaisesRegex(RuntimeError, "death"):
            execute(argv, faulting)
        self.assertFalse(faulting.db_path("albanian-live-translate", "RUN-1").exists())
        conflicting = list(argv); conflicting[-1] = "different-op"
        with self.assertRaisesRegex(StateError, "INCOMPLETE_INIT_CONFLICT"):
            execute(conflicting, StateStore(home))
        recovered = execute(argv, StateStore(home))[0]
        self.assertEqual(recovered["code"], "INITIALIZED")
        replay = execute(argv, StateStore(home))[0]
        self.assertEqual((replay["code"], replay["state_revision"]), ("REPLAYED", 1))

    def test_process_death_after_replace_is_superseded_by_identical_init(self):
        class SimulatedProcessDeath(BaseException):
            pass

        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        home = self.root / "death-codex"
        dying = StateStore(home, lambda point: (_ for _ in ()).throw(SimulatedProcessDeath()) if point == "post_replace" else None)
        argv = ["--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "death-op"]
        with self.assertRaises(SimulatedProcessDeath):
            execute(argv, dying)
        self.assertTrue(dying.db_path("albanian-live-translate", "RUN-1").exists())
        recovered = execute(argv, StateStore(home))[0]
        self.assertEqual(recovered["code"], "INITIALIZED")

    def test_identical_init_recovers_from_truncated_marker_using_database_digest(self):
        class SimulatedProcessDeath(BaseException):
            pass

        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        home = self.root / "truncated-marker-codex"
        dying = StateStore(
            home,
            lambda point: (_ for _ in ()).throw(SimulatedProcessDeath())
            if point == "post_replace" else None,
        )
        argv = [
            "--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability",
            "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "truncated-op",
        ]
        with self.assertRaises(SimulatedProcessDeath):
            execute(argv, dying)
        marker = next(dying.run_root("albanian-live-translate", "RUN-1").glob("*.incomplete.sqlite3.marker"))
        marker.write_text("{", encoding="utf-8")
        if os.name != "nt":
            os.chmod(marker, 0o600)
        recovered = execute(argv, StateStore(home))[0]
        self.assertEqual(recovered["code"], "INITIALIZED")

    def test_conflicting_init_with_absent_marker_fails_closed_from_database_digest(self):
        class SimulatedProcessDeath(BaseException):
            pass

        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        home = self.root / "absent-marker-codex"
        dying = StateStore(
            home,
            lambda point: (_ for _ in ()).throw(SimulatedProcessDeath())
            if point == "post_replace" else None,
        )
        argv = [
            "--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability",
            "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "original-op",
        ]
        with self.assertRaises(SimulatedProcessDeath):
            execute(argv, dying)
        for marker in dying.run_root("albanian-live-translate", "RUN-1").glob("*.incomplete.sqlite3.marker"):
            marker.unlink()
        conflicting = list(argv)
        conflicting[-1] = "conflicting-op"
        with self.assertRaisesRegex(StateError, "INCOMPLETE_INIT_CONFLICT"):
            execute(conflicting, StateStore(home))
        self.assertTrue(dying.db_path("albanian-live-translate", "RUN-1").exists())

    def test_sqlite_cross_connection_lock_probe_is_required_and_succeeds_locally(self):
        seen = []
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        probing = StateStore(self.root / "probe-codex", lambda point: seen.append(point))
        result = execute([
            "--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability",
            "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "probe-op",
        ], probing)[0]
        self.assertEqual(result["code"], "INITIALIZED")
        self.assertIn("locking_probe", seen)

    def test_non_local_state_root_and_changed_locality_fail_closed(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        with patch("graph_engine.state.local_filesystem_identity", side_effect=StateError("NON_LOCAL_FILESYSTEM")):
            with self.assertRaisesRegex(StateError, "NON_LOCAL_FILESYSTEM"):
                execute([
                    "--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability",
                    "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "remote-op",
                ], StateStore(self.root / "remote-codex"))
        self.initialize()
        with patch("graph_engine.state.local_filesystem_identity", return_value="changed-filesystem"):
            with self.assertRaisesRegex(StateError, "FILESYSTEM_IDENTITY_CHANGED"):
                self.graphctl("status", "--run-id", "RUN-1")

    def test_platform_locality_probe_rejects_known_network_filesystems(self):
        if os.name == "nt":
            with patch("ctypes.windll.kernel32.GetDriveTypeW", return_value=4):
                with self.assertRaisesRegex(StateError, "NON_LOCAL_FILESYSTEM"):
                    local_filesystem_identity(self.root)
        else:
            with patch("graph_engine.state._linux_filesystem_type", return_value="nfs"):
                with self.assertRaisesRegex(StateError, "NON_LOCAL_FILESYSTEM"):
                    local_filesystem_identity(self.root)

    def test_run_and_inbox_identity_are_reverified_on_open(self):
        self.initialize()
        inbox = self.store.inbox_root("albanian-live-translate", "RUN-1")
        (inbox / "unexpected-directory").mkdir()
        with self.assertRaisesRegex(StateError, "INBOX_ENTRY_INVALID"):
            self.graphctl("status", "--run-id", "RUN-1")

    def test_concurrent_initialization_has_one_authoritative_winner(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        home = self.root / "concurrent-init"
        entered = threading.Event()

        def hook(point):
            if point == "database_file_flush":
                entered.set(); time.sleep(0.2)

        stores = [StateStore(home, hook), StateStore(home)]
        outcomes = []
        argv = ["--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "concurrent-op"]

        def initialize(active_store):
            try:
                outcomes.append(execute(argv, active_store)[0]["code"])
            except StateError as error:
                outcomes.append(error.code)

        first = threading.Thread(target=initialize, args=(stores[0],)); first.start(); entered.wait(2)
        second = threading.Thread(target=initialize, args=(stores[1],)); second.start()
        first.join(); second.join()
        self.assertIn("INITIALIZED", outcomes)
        self.assertTrue(set(outcomes).issubset({"INITIALIZED", "INITIALIZATION_CONFLICT", "REPLAYED"}))
        with StateStore(home).open_run("albanian-live-translate", "RUN-1") as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_second_parent_sync_failure_never_becomes_authoritative(self):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(self.task()), encoding="utf-8")
        calls = 0

        def hook(point):
            nonlocal calls
            if point == "directory_sync":
                calls += 1
                if calls == 2:
                    raise RuntimeError("post-rename-sync")

        faulting = StateStore(self.root / "sync-codex", hook)
        with self.assertRaisesRegex(RuntimeError, "post-rename-sync"):
            execute(["--repo", str(self.repo), "--ack-degraded-permissions", "--ack-degraded-durability", "init", "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "sync-op"], faulting)
        self.assertFalse(faulting.db_path("albanian-live-translate", "RUN-1").exists())

    def test_replay_precedes_state_matrix_for_every_mutation(self):
        self.initialize()
        db = self.store.db_path("albanian-live-translate", "RUN-1")
        with self.store.connect(db) as connection:
            connection.execute("UPDATE runs SET status='active' WHERE run_id='RUN-1'")
            commands = [
                "next.claim", "record.branch-result", "record.timeout", "record.skip", "record.retry",
                "record.approval", "record.budget-use", "record.acceptance-evidence",
                "record.check-evidence", "join.advance", "complete", "block", "abort",
            ]
            for index, command in enumerate(commands, 1):
                op_id = "matrix-" + str(index)
                first = self.store.mutate(connection, "RUN-1", op_id, {"command": command}, lambda _c, _r, _v, name=command: {"code": "RECORDED", "command": name})
                connection.execute("UPDATE runs SET status='complete' WHERE run_id='RUN-1'")
                replay = self.store.mutate(connection, "RUN-1", op_id, {"command": command}, lambda *_args: self.fail("replay action executed"))
                self.assertEqual(replay["code"], "REPLAYED")
                self.assertEqual(replay["state_revision"], first["state_revision"])
                connection.execute("UPDATE runs SET status='active' WHERE run_id='RUN-1'")

    def test_default_store_uses_profile_root_not_skill_directory(self):
        home = installed_codex_home()
        self.assertEqual(home, Path(r"C:\Users\sephn\.codex"))
        default = StateStore()
        self.assertTrue(str(default.run_root("repo", "run")).startswith(str(home / "graph-runs")))

    def test_semantic_corruption_fails_closed(self):
        cases = [
            ("negative-budget", "UPDATE budgets SET used=-1 WHERE budget_id='file_reads'", "BUDGET_STATE_INVALID"),
            ("policy-json", "UPDATE runs SET policy_json='{}'", "POLICY_STATE_INVALID"),
            ("node-role", "UPDATE nodes SET role='senior_engineer'", "NODE_BINDING_INVALID"),
            ("operation-response", "UPDATE operations SET response_json='{}' WHERE resulting_revision=1", "OPERATION_LEDGER_INVALID"),
        ]
        for name, statement, code in cases:
            with self.subTest(name=name):
                self.tearDown(); self.setUp(); self.initialize()
                db = self.store.db_path("albanian-live-translate", "RUN-1")
                connection = sqlite3.connect(str(db))
                try:
                    connection.execute(statement)
                    connection.commit()
                finally:
                    connection.close()
                with self.assertRaisesRegex(StateError, code):
                    self.graphctl("status", "--run-id", "RUN-1")

    def test_compatible_engine_upgrade_is_accepted_but_range_exit_is_rejected(self):
        self.initialize()
        db = self.store.db_path("albanian-live-translate", "RUN-1")
        connection = sqlite3.connect(str(db))
        try:
            connection.execute("UPDATE runs SET engine_version='2.5.0'")
            connection.commit()
        finally:
            connection.close()
        resumed = self.graphctl(
            "resume", "--run-id", "RUN-1", "--ack-degraded-permissions",
            "--ack-degraded-durability",
        )
        self.assertEqual(resumed["code"], "RESUMED")
        connection = sqlite3.connect(str(db))
        try:
            connection.execute("UPDATE runs SET engine_version='3.0.0'")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(StateError, "ENGINE_VERSION_INCOMPATIBLE"):
            self.graphctl("status", "--run-id", "RUN-1")

    def test_route_tag_specialist_and_generation_corruption_fail_closed(self):
        cases = [
            (
                "route-downgrade", [],
                "UPDATE runs SET selected_route='fast_path'", "ROUTE_EVIDENCE_MISMATCH",
            ),
            (
                "tag-downgrade", ["security_privacy"],
                "UPDATE runs SET selected_tags_json='[]'", "ROUTE_EVIDENCE_MISMATCH",
            ),
            (
                "generation-counter", [],
                "UPDATE runs SET design_generation=7", "GENERATION_STATE_INVALID",
            ),
        ]
        for name, tags, statement, code in cases:
            with self.subTest(name=name):
                self.tearDown(); self.setUp()
                self.initialize(tags=tags); self.impact("full_delivery", tags)
                db = self.store.db_path("albanian-live-translate", "RUN-1")
                connection = sqlite3.connect(str(db))
                try:
                    connection.execute(statement); connection.commit()
                finally:
                    connection.close()
                with self.assertRaisesRegex(StateError, code):
                    self.graphctl("status", "--run-id", "RUN-1")

        self.tearDown(); self.setUp()
        tags = ["security_privacy"]
        self.initialize(tags=tags); self.impact("full_delivery", tags)
        tech = self.claim(); self.success(tech); self.advance("design_inputs")
        db = self.store.db_path("albanian-live-translate", "RUN-1")
        connection = sqlite3.connect(str(db))
        try:
            connection.execute(
                "UPDATE nodes SET specialist_tag='audio_realtime_translation' WHERE specialist_tag='security_privacy'"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(
            StateError, "NODE_BINDING_INVALID|TOPOLOGY_STATE_INVALID|STABLE_ID_INVALID"
        ):
            self.graphctl("status", "--run-id", "RUN-1")

    def test_artifact_envelope_and_join_corruption_fail_closed(self):
        self.initialize(); self.impact("full_delivery")
        tech = self.claim(); self.success(tech); self.advance("design_inputs")
        db = self.store.db_path("albanian-live-translate", "RUN-1")
        corruption = [
            ("DELETE FROM artifacts WHERE kind='task_brief'", "INPUT_ARTIFACT_INVALID"),
            ("UPDATE nodes SET envelope_json='{}' WHERE node_key='architect'", "ENVELOPE_INVALID"),
            ("DELETE FROM join_members WHERE join_id=(SELECT join_id FROM joins WHERE join_key='design_collection')", "JOIN_MEMBERSHIP_INVALID"),
        ]
        for index, (statement, code) in enumerate(corruption):
            with self.subTest(index=index):
                if index:
                    self.tearDown(); self.setUp(); self.initialize(); self.impact("full_delivery")
                    tech = self.claim(); self.success(tech); self.advance("design_inputs")
                    db = self.store.db_path("albanian-live-translate", "RUN-1")
                connection = sqlite3.connect(str(db))
                try:
                    connection.execute(statement); connection.commit()
                finally:
                    connection.close()
                with self.assertRaisesRegex(StateError, code):
                    self.graphctl("status", "--run-id", "RUN-1")

    def test_concurrent_claims_have_one_winner_and_one_conflict(self):
        self.initialize()
        entered = threading.Event()

        def hook(point):
            if point == "before_commit" and not entered.is_set():
                entered.set()
                time.sleep(0.2)

        first_store = StateStore(self.store.codex_home, hook)
        outcomes = []

        def claim(op_id, active_store):
            try:
                outcomes.append(execute(["--repo", str(self.repo), "next", "--run-id", "RUN-1", "--claim", "--op-id", op_id], active_store)[0]["code"])
            except StateError as error:
                outcomes.append(error.code)

        one = threading.Thread(target=claim, args=("claim-one", first_store))
        two = threading.Thread(target=claim, args=("claim-two", self.store))
        one.start(); entered.wait(2); two.start(); one.join(); two.join()
        self.assertEqual(sorted(outcomes), ["CLAIMED", "CLAIM_CONFLICT"])
