import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from graph_engine.cli import execute
from graph_engine.ids import sha256_bytes
from graph_engine.state import StateStore


WORKSPACE = Path(r"C:\dev\GitHub\AlbanianLiveTranslate")
POLICY_SOURCE = WORKSPACE / ".codex" / "engineering-graph.json"
DIGEST = "a" * 64


class GraphCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        (self.repo / ".codex").mkdir(parents=True)
        (self.repo / "docs" / "artifacts").mkdir(parents=True)
        (self.repo / "docs" / "engineering-graph.md").write_text("# Test graph evidence\n", encoding="utf-8")
        shutil.copyfile(POLICY_SOURCE, self.repo / ".codex" / "engineering-graph.json")
        self.policy_bytes = (self.repo / ".codex" / "engineering-graph.json").read_bytes()
        self.store = StateStore(self.root / "codex")
        self.counter = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def task(self, mode: str = "delivery", route: str = "full_delivery", tags: Optional[List[str]] = None) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "task_id": "TASK-1",
            "objective": "Exercise the graph",
            "user_outcome": "Deterministic evidence",
            "request_mode": mode,
            "minimum_route": route,
            "mandatory_impact_tags": tags or [],
            "scope": {"included": ["graph"], "excluded": ["application"]},
            "constraints": ["preserve runtime"],
            "acceptance_criteria": [{"id": "AC-001", "text": "Graph closes"}],
            "risk_level": "high" if tags else "low",
            "authority": {"capabilities": [
                {"effect": "filesystem_read", "action": "read", "target_ref": "repo:docs/"}
            ]},
            "policy_approval": {"sha256": sha256_bytes(self.policy_bytes), "authority_ref": "authority:test"},
            "evidence_paths": ["repo:docs/engineering-graph.md"],
            "inspection_budget": {"file_reads": 12, "discovery_commands": 8},
            "required_check_ids": ["repo-check"],
            "required_human_decisions": [],
        }

    def graphctl(self, *args: str):
        return execute(["--repo", str(self.repo), *args], self.store)[0]

    def initialize(
        self, mode: str = "delivery", route: str = "full_delivery", tags: Optional[List[str]] = None,
        size: Optional[str] = None, approve: bool = True,
    ):
        return self.initialize_task(self.task(mode, route, tags), size=size, approve=approve)

    def initialize_task(self, task: Dict[str, Any], size: Optional[str] = None, approve: bool = True):
        task_path = self.repo / "docs" / "task.json"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        args = [
            "--ack-degraded-permissions", "--ack-degraded-durability", "init",
            "--run-id", "RUN-1", "--task-brief", str(task_path), "--op-id", "init-1",
        ]
        if size:
            args.extend(["--size", size])
        result = self.graphctl(*args)
        if approve:
            self.graphctl(
                "record", "plan-approval", "--run-id", "RUN-1",
                "--plan-digest", result["execution_plan_digest"], "--decision", "APPROVE",
                "--authority-ref", "authority:test", "--op-id", "plan-approval-1",
            )
        return result

    def inbox_manifest(self, content: Dict[str, Any], name: Optional[str] = None) -> Path:
        self.counter += 1
        inbox = self.store.inbox_root("albanian-live-translate", "RUN-1")
        path = inbox / (name or f"manifest-{self.counter}.json")
        path.write_text(json.dumps(content), encoding="utf-8")
        if os.name != "nt":
            os.chmod(path, 0o600)
        return path

    def repo_artifact(self, kind: str, label: Optional[str] = None) -> Dict[str, str]:
        self.counter += 1
        name = (label or f"artifact-{self.counter}") + ".json"
        path = self.repo / "docs" / "artifacts" / name
        path.write_text(json.dumps({"schema_version": 1, "kind": kind, "label": label or name}), encoding="utf-8")
        artifact_digest = sha256_bytes(path.read_bytes())
        ref = "repo:docs/artifacts/" + name + "#sha256=" + artifact_digest
        return {"kind": kind, "ref": ref, "sha256": artifact_digest}

    def control_manifest(self, kind: str, reason: str, branch: Optional[Dict[str, Any]] = None) -> Path:
        evidence = self.repo_artifact(kind, kind + "-evidence-" + str(self.counter))
        manifest = {
            "schema_version": 1, "kind": kind, "run_id": "RUN-1",
            "reason_code": reason, "evidence": [evidence],
        }
        if branch is not None:
            manifest["branch_id"] = branch["branch_id"]
            if kind == "timeout" and branch.get("attempt_id") and branch.get("claim_token"):
                manifest["attempt_id"] = branch["attempt_id"]
                manifest["claim_digest"] = sha256_bytes(branch["claim_token"].encode("utf-8"))
        return self.inbox_manifest(manifest)

    def claim(self) -> Dict[str, Any]:
        status = self.graphctl("status", "--run-id", "RUN-1")
        if status["next_action"]["kind"] == "record_fanout_assessment":
            self.assess_fanout(status["next_action"]["fanout_id"])
        self.counter += 1
        return self.graphctl("next", "--run-id", "RUN-1", "--claim", "--op-id", f"claim-{self.counter}")["branch"]

    def record(self, branch: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
        self.counter += 1
        manifest = dict(manifest)
        manifest["attempt_id"] = branch["attempt_id"]
        manifest["claim_digest"] = sha256_bytes(branch["claim_token"].encode("utf-8"))
        path = self.inbox_manifest(manifest)
        return self.graphctl(
            "record", "branch-result", "--run-id", "RUN-1", "--branch-id", branch["branch_id"],
            "--attempt-id", branch["attempt_id"], "--claim-token", branch["claim_token"],
            "--result-manifest", str(path), "--op-id", f"result-{self.counter}",
        )

    def assess_fanout(self, fanout_id: str, dependencies: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        status = self.graphctl("status", "--run-id", "RUN-1")
        fanout = next(item for item in status["fanouts"] if item["fanout_id"] == fanout_id)
        evidence = self.repo_artifact("finding", "fanout-evidence-" + str(self.counter))
        manifest = {
            "schema_version": 1, "kind": "fanout_assessment", "run_id": "RUN-1",
            "fanout_id": fanout_id,
            "members": [{
                "branch_id": branch_id,
                "resources": {
                    "writable_paths": [], "mutable_state_refs": [],
                    "exclusive_device_refs": [], "services": [],
                },
            } for branch_id in fanout["member_branch_ids"]],
            "dependencies": dependencies or [], "evidence": [evidence],
        }
        self.counter += 1
        path = self.inbox_manifest(manifest)
        return self.graphctl(
            "record", "fanout-assessment", "--run-id", "RUN-1", "--fanout-id", fanout_id,
            "--assessment-manifest", str(path), "--authority-ref", "authority:test",
            "--op-id", "fanout-assessment-" + str(self.counter),
        )

    def impact(self, route: str, tags: Optional[List[str]] = None) -> None:
        mapper = self.claim()
        evidence = self.repo_artifact("finding", "impact-evidence-" + str(self.counter))
        self.record(mapper, {
            "schema_version": 1, "task_id": "TASK-1", "route_label": route,
            "impact_tags": sorted(tags or []), "evidence_refs": [evidence["ref"]],
        })

    def success(self, branch: Dict[str, Any], decision: Optional[str] = None, findings: Optional[List[Dict[str, str]]] = None) -> None:
        kind = branch["output_contract"]["artifact_kind"]
        artifact = self.repo_artifact(kind, branch["branch_id"])
        if decision is None and branch["output_contract"].get("decision_values"):
            decision = "APPROVE"
        manifest: Dict[str, Any] = {
            "schema_version": 1, "run_id": "RUN-1", "branch_id": branch["branch_id"],
            "status": "succeeded", "output_kind": kind,
            "artifact_ref": artifact,
            "evidence": [], "findings": findings or [],
        }
        if decision is not None:
            manifest["decision"] = decision
        self.record(branch, manifest)

    def open_join(self, key: str, generation: int = 0) -> Dict[str, Any]:
        status = self.graphctl("status", "--run-id", "RUN-1")
        return next(join for join in status["joins"] if join["join_key"] == key and join["generation"] == generation and join["status"] == "open")

    def advance(self, key: str, generation: int = 0) -> Dict[str, Any]:
        self.counter += 1
        join = self.open_join(key, generation)
        return self.graphctl("join", "advance", "--run-id", "RUN-1", "--join-id", join["join_id"], "--op-id", f"join-{self.counter}")

    def consolidation(self, stage: str, outcome: str, generation: int = 0, dispositions: Optional[List[Dict[str, str]]] = None) -> None:
        branch = self.claim()
        self.assertEqual(branch["node_key"], f"supervisor_{stage}_consolidation")
        collection_input = next(item for item in branch["inputs"] if item["kind"] == "collection")
        collection = collection_input["content"]
        sources = [member["branch_id"] for member in collection["members"]]
        self.record(branch, {
            "schema_version": 1, "kind": stage + "_consolidation", "run_id": "RUN-1",
            "join_id": collection["join_id"], "generation": generation,
            "source_branch_ids": sources, "finding_dispositions": dispositions or [], "outcome": outcome,
        })
