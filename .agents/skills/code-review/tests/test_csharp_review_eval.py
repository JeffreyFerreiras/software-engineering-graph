from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "run_csharp_review_eval.py"
SPEC = importlib.util.spec_from_file_location("run_csharp_review_eval", SCRIPT)
assert SPEC and SPEC.loader
EVAL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EVAL
SPEC.loader.exec_module(EVAL)


def finding(principle: str, file: str) -> dict[str, object]:
    return {
        "title": f"{principle} finding",
        "severity": "Medium",
        "file": file,
        "line": 10,
        "category": "SOLID principle",
        "principle": principle,
        "pattern": "",
        "trigger": "The changed code demonstrates the violation.",
        "impact": "The violation creates a concrete maintenance cost.",
        "remediation": "Separate the affected contract or responsibility.",
    }


class CSharpReviewEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = json.loads(
            EVAL.EXPECTED_FINDINGS.read_text(encoding="utf-8")
        )

    def passing_review(self) -> dict[str, object]:
        findings = [
            finding(requirement["principle"], requirement["files_any"][0])
            for requirement in self.expected["must_find"]
        ]
        return {
            "findings": findings,
            "open_questions": [],
            "residual_risks": [],
        }

    def test_grader_accepts_anchored_findings_without_matching_prose(self) -> None:
        review = self.passing_review()
        review["findings"][0]["title"] = "A differently worded responsibility issue"
        review["findings"][0]["file"] = (
            ".\\src\\ParcelPilot.Application\\ShipmentWorkflow.cs"
        )

        grade = EVAL.grade_review(review, self.expected)

        self.assertTrue(grade["passed"])
        self.assertEqual(1.0, grade["required_recall"])
        self.assertEqual([], grade["missing"])

    def test_grader_reports_missing_required_principle(self) -> None:
        review = self.passing_review()
        review["findings"] = [
            item
            for item in review["findings"]
            if item["principle"] != "Dependency Inversion Principle"
        ]

        grade = EVAL.grade_review(review, self.expected)

        self.assertFalse(grade["passed"])
        self.assertEqual(
            ["dip-dispatch-handler-constructs-file-audit-detail"],
            grade["missing"],
        )

    def test_grader_rejects_principle_false_positive_on_decoy(self) -> None:
        review = self.passing_review()
        review["findings"].append(
            finding(
                "Single Responsibility Principle",
                "src/ParcelPilot.Application/ShipmentSummary.cs",
            )
        )

        grade = EVAL.grade_review(review, self.expected)

        self.assertFalse(grade["passed"])
        self.assertEqual(
            ["srp-data-only-shipment-summary"], grade["false_positives"]
        )

    def test_grader_rejects_mixed_principle_and_pattern_finding(self) -> None:
        review = self.passing_review()
        review["findings"][0]["pattern"] = "Strategy"

        grade = EVAL.grade_review(review, self.expected)

        self.assertFalse(grade["passed"])
        self.assertEqual([0], grade["malformed_finding_indexes"])

    def test_command_runner_decodes_utf8_output_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = EVAL._run(
                [
                    sys.executable,
                    "-c",
                    "import sys; "
                    "sys.stdout.buffer.write('review complete: →'.encode('utf-8'))",
                ],
                cwd=Path(temporary),
            )

        self.assertIn("review complete: →", result.stdout)

    def test_runtime_skill_excludes_fixture_and_answer_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "ParcelPilot"
            EVAL.materialize_repository(repository, stage_skill=True)
            runtime_skill = repository / ".agents" / "skills" / "code-review"

            self.assertTrue((runtime_skill / "SKILL.md").is_file())
            self.assertTrue(
                (runtime_skill / "scripts" / "search_review_graph.py").is_file()
            )
            self.assertFalse((runtime_skill / "assets").exists())
            self.assertFalse((runtime_skill / "tests").exists())
            self.assertFalse(
                (runtime_skill / "scripts" / "run_csharp_review_eval.py").exists()
            )

            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertNotIn(".agents", status)

    def test_materialized_repository_contains_reviewable_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "ParcelPilot"
            EVAL.materialize_repository(repository)
            changed_files = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()

            self.assertIn(
                "src/ParcelPilot.Infrastructure/Rates/LocalPickupRateCalculator.cs",
                changed_files,
            )
            self.assertIn(
                "src/ParcelPilot.Application/Devices/ILabelPrinter.cs",
                changed_files,
            )
            self.assertGreaterEqual(len(changed_files), 10)

    @unittest.skipUnless(
        shutil.which("dotnet") and shutil.which("git"),
        "dotnet and git are required for the fixture integration check",
    )
    def test_fixture_builds_and_exposes_expected_contract_failure(self) -> None:
        result = EVAL.validate_fixture()

        self.assertEqual(0, result["baseline_contract_checks"])
        self.assertEqual(0, result["changed_build"])
        self.assertEqual(1, result["changed_contract_checks"])


if __name__ == "__main__":
    unittest.main()
