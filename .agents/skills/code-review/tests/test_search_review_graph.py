import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "search_review_graph.py"
MANIFEST = SKILL_ROOT / "references" / "review-graph.manifest.json"


def load_search_module():
    spec = importlib.util.spec_from_file_location("search_review_graph", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SEARCH_MODULE = load_search_module()


def run_search(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


class ReviewGraphSearchTests(unittest.TestCase):
    def test_default_version_two_manifest_validates(self) -> None:
        result = run_search("--validate")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Valid review graph", result.stdout)
        raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 2)
        self.assertEqual(raw["name"], "code-review-design-graph")

        graph = SEARCH_MODULE.load_manifest(MANIFEST)
        self.assertEqual(graph.version, 2)

    def test_non_version_two_manifests_are_rejected(self) -> None:
        for version in (1, 3, True, None):
            with self.subTest(version=version):
                raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
                raw["version"] = version
                with tempfile.TemporaryDirectory() as temporary:
                    invalid_manifest = Path(temporary) / "invalid.json"
                    invalid_manifest.write_text(json.dumps(raw), encoding="utf-8")
                    result = run_search(
                        "--manifest", str(invalid_manifest), "--validate"
                    )

                self.assertEqual(result.returncode, 2)
                self.assertIn("manifest version must be 2", result.stderr)

    def test_each_solid_principle_resolves_by_full_name_and_acronym(self) -> None:
        principles = {
            "Single Responsibility Principle": (
                "SRP",
                "principle.single-responsibility",
            ),
            "Open/Closed Principle": ("OCP", "principle.open-closed"),
            "Liskov Substitution Principle": (
                "LSP",
                "principle.liskov-substitution",
            ),
            "Interface Segregation Principle": (
                "ISP",
                "principle.interface-segregation",
            ),
            "Dependency Inversion Principle": (
                "DIP",
                "principle.dependency-inversion",
            ),
        }

        for full_name, (acronym, expected_id) in principles.items():
            with self.subTest(query=full_name):
                result = run_search(full_name, "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["principles"][0]["id"], expected_id)

            with self.subTest(query=acronym):
                result = run_search(acronym, "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["principles"][0]["id"], expected_id)

    def test_principles_are_not_classified_as_pattern_candidates(self) -> None:
        result = run_search("LSP", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [item["id"] for item in payload["principles"]],
            ["principle.liskov-substitution"],
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["traversal"][0]["kind"], "principle")

    def test_behavior_variation_returns_strategy(self) -> None:
        result = run_search(
            "scattered conditional branches choose a payment algorithm that will vary",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        candidate_ids = [item["id"] for item in payload["candidates"]]
        self.assertIn("pattern.strategy", candidate_ids)

    def test_existing_pattern_exact_lookup_remains_a_pattern_candidate(self) -> None:
        result = run_search("Strategy", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["principles"], [])
        candidate_ids = [item["id"] for item in payload["candidates"]]
        self.assertEqual(candidate_ids[0], "pattern.strategy")
        self.assertTrue(
            all(item["kind"] == "pattern" for item in payload["candidates"])
        )

    def test_incompatible_boundary_returns_adapter(self) -> None:
        result = run_search(
            "third party API has an incompatible interface leaking through the boundary",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        candidate_ids = [item["id"] for item in payload["candidates"]]
        self.assertIn("pattern.adapter", candidate_ids)

    def test_weak_generic_matches_do_not_surface_unrelated_patterns(self) -> None:
        result = run_search(
            "new notification logic directly calls several unrelated consumers "
            "and more consumers will be added",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        candidate_ids = [item["id"] for item in payload["candidates"]]
        self.assertEqual(candidate_ids, ["pattern.observer"])

    def test_node_budget_is_respected(self) -> None:
        result = run_search(
            "construction behavior state event interface dependency",
            "--max-nodes",
            "4",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertLessEqual(len(payload["traversal"]), 4)

    def test_unknown_edge_target_fails_validation(self) -> None:
        raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
        raw["edges"][0]["to"] = "pattern.missing"
        with tempfile.TemporaryDirectory() as temporary:
            invalid_manifest = Path(temporary) / "invalid.json"
            invalid_manifest.write_text(json.dumps(raw), encoding="utf-8")
            result = run_search("--manifest", str(invalid_manifest), "--validate")

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown node", result.stderr)

    def test_principle_without_guardrails_fails_validation(self) -> None:
        raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
        principle = next(
            node for node in raw["nodes"] if node["kind"] == "principle"
        )
        del principle["guardrails"]
        with tempfile.TemporaryDirectory() as temporary:
            invalid_manifest = Path(temporary) / "invalid.json"
            invalid_manifest.write_text(json.dumps(raw), encoding="utf-8")
            result = run_search("--manifest", str(invalid_manifest), "--validate")

        self.assertEqual(result.returncode, 2)
        self.assertIn("guardrails must be a non-empty string array", result.stderr)


if __name__ == "__main__":
    unittest.main()
