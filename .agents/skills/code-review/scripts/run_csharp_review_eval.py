#!/usr/bin/env python3
"""Validate and run the bundled C# behavioral evaluation for code-review."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence


SKILL_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = SKILL_ROOT / "assets" / "evals" / "csharp-solid-review"
BASELINE_ROOT = EVAL_ROOT / "baseline"
CHANGE_ROOT = EVAL_ROOT / "change"
DELETED_FILES = EVAL_ROOT / "deleted-files.txt"
EXPECTED_FINDINGS = EVAL_ROOT / "expected-findings.json"
OUTPUT_SCHEMA = EVAL_ROOT / "review-output.schema.json"
REVIEW_PROMPT = EVAL_ROOT / "review-prompt.md"
CONTRACT_PROJECT = (
    Path("tests")
    / "ParcelPilot.ContractChecks"
    / "ParcelPilot.ContractChecks.csproj"
)
CONTRACT_FAILURE_MARKER = "LocalPickupRateCalculator rejected a valid shipment"
POLICY_FAILURE_MARKER = "ShippingPolicy rejected LocalPickup"

PRINCIPLE_ALIASES = {
    "srp": "single responsibility principle",
    "ocp": "open closed principle",
    "lsp": "liskov substitution principle",
    "isp": "interface segregation principle",
    "dip": "dependency inversion principle",
}


class EvaluationError(RuntimeError):
    """Raised when the evaluation fixture or execution environment is invalid."""


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    expected_codes: Iterable[int] = (0,),
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode not in set(expected_codes):
        rendered = " ".join(command)
        raise EvaluationError(
            f"Command failed with exit code {result.returncode}: {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise EvaluationError(f"Missing fixture directory: {source}")
    shutil.copytree(source, destination, dirs_exist_ok=True)
    for path in destination.rglob("*"):
        if path.is_file() and path.suffix in {".cs", ".csproj", ".props", ".sln", ".md", ".json", ".txt"}:
            content = path.read_bytes()
            if b"\r\n" in content:
                path.write_bytes(content.replace(b"\r\n", b"\n"))


def initialize_baseline(destination: Path) -> None:
    """Create and commit the fixture's clean baseline repository."""
    if destination.exists() and any(destination.iterdir()):
        raise EvaluationError(f"Destination must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    _copy_tree(BASELINE_ROOT, destination)

    _run(["git", "init", "--initial-branch=main"], cwd=destination)
    _run(["git", "config", "user.name", "Code Review Eval"], cwd=destination)
    _run(
        ["git", "config", "user.email", "code-review-eval@example.invalid"],
        cwd=destination,
    )
    _run(["git", "config", "core.autocrlf", "false"], cwd=destination)
    _run(["git", "add", "."], cwd=destination)
    _run(["git", "commit", "-m", "baseline"], cwd=destination)


def apply_fixture_change(repository: Path) -> None:
    """Overlay the intentionally flawed review change onto the baseline."""
    tracked_files = set(
        _run(["git", "ls-files"], cwd=repository).stdout.splitlines()
    )
    _copy_tree(CHANGE_ROOT, repository)
    if DELETED_FILES.exists():
        for raw_path in DELETED_FILES.read_text(encoding="utf-8").splitlines():
            relative_path = raw_path.strip()
            if not relative_path or relative_path.startswith("#"):
                continue
            target = (repository / relative_path).resolve()
            try:
                target.relative_to(repository.resolve())
            except ValueError as exc:
                raise EvaluationError(
                    f"Deleted fixture path escapes repository: {relative_path}"
                ) from exc
            if not target.is_file():
                raise EvaluationError(f"Deleted fixture file is missing: {relative_path}")
            target.unlink()

    added_files = [
        path.relative_to(CHANGE_ROOT).as_posix()
        for path in CHANGE_ROOT.rglob("*")
        if path.is_file()
        and path.relative_to(CHANGE_ROOT).as_posix() not in tracked_files
    ]
    if added_files:
        _run(
            ["git", "add", "--intent-to-add", "--", *added_files],
            cwd=repository,
        )


def stage_runtime_skill(repository: Path) -> Path:
    """Stage only runtime skill files, excluding the fixture and answer key."""
    destination = repository / ".agents" / "skills" / "code-review"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SKILL_ROOT / "SKILL.md", destination / "SKILL.md")
    for directory_name in ("agents", "references"):
        _copy_tree(SKILL_ROOT / directory_name, destination / directory_name)

    scripts_destination = destination / "scripts"
    scripts_destination.mkdir()
    shutil.copy2(
        SKILL_ROOT / "scripts" / "search_review_graph.py",
        scripts_destination / "search_review_graph.py",
    )

    info_exclude = repository / ".git" / "info" / "exclude"
    with info_exclude.open("a", encoding="utf-8") as exclude_file:
        exclude_file.write("\n.agents/\n")
    return destination


def materialize_repository(destination: Path, *, stage_skill: bool = False) -> Path:
    initialize_baseline(destination)
    apply_fixture_change(destination)
    if stage_skill:
        stage_runtime_skill(destination)
    return destination


def _build(repository: Path, *, no_restore: bool = False) -> None:
    command = ["dotnet", "build", "ParcelPilot.sln", "--nologo"]
    if no_restore:
        command.extend(["--no-restore", "--no-incremental"])
    _run(command, cwd=repository, timeout=300)


def _run_contract_checks(
    repository: Path, *, expected_codes: Iterable[int]
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "dotnet",
            "run",
            "--project",
            str(CONTRACT_PROJECT),
            "--no-build",
        ],
        cwd=repository,
        expected_codes=expected_codes,
        timeout=180,
    )


def validate_fixture() -> dict[str, Any]:
    """Prove the baseline passes and the changed project exposes its contract bug."""
    if shutil.which("dotnet") is None:
        raise EvaluationError("dotnet is required to validate the C# fixture")
    if shutil.which("git") is None:
        raise EvaluationError("git is required to materialize the C# fixture")

    with tempfile.TemporaryDirectory(prefix="code-review-csharp-eval-") as temporary:
        repository = Path(temporary) / "ParcelPilot"
        initialize_baseline(repository)
        _build(repository)
        baseline_checks = _run_contract_checks(repository, expected_codes=(0,))

        apply_fixture_change(repository)
        _run(["git", "diff", "--check"], cwd=repository)
        _build(repository, no_restore=True)
        changed_checks = _run_contract_checks(repository, expected_codes=(1,))
        combined_output = f"{changed_checks.stdout}\n{changed_checks.stderr}"
        missing_markers = [
            marker
            for marker in (CONTRACT_FAILURE_MARKER, POLICY_FAILURE_MARKER)
            if marker not in combined_output
        ]
        if missing_markers:
            raise EvaluationError(
                "Changed contract checks failed without expected signals "
                f"{missing_markers}:\n"
                f"{combined_output}"
            )
        changed_files = _run(
            ["git", "diff", "--name-only"], cwd=repository
        ).stdout.splitlines()

    return {
        "baseline_contract_checks": baseline_checks.returncode,
        "changed_build": 0,
        "changed_contract_checks": changed_checks.returncode,
        "changed_files": changed_files,
    }


def _normalize_text(value: object) -> str:
    return " ".join(
        str(value).casefold().replace("/", " ").replace("-", " ").split()
    )


def _normalize_principle(value: object) -> str:
    normalized = _normalize_text(value)
    return PRINCIPLE_ALIASES.get(normalized, normalized)


def _normalize_path(value: object) -> str:
    return str(value).replace("\\", "/").casefold().lstrip("./")


def _path_matches(actual: object, expected_paths: Sequence[str]) -> bool:
    actual_path = _normalize_path(actual)
    return any(actual_path.endswith(_normalize_path(path)) for path in expected_paths)


def _matches_requirement(
    finding: dict[str, Any], requirement: dict[str, Any]
) -> bool:
    if _normalize_text(finding.get("category", "")) != "solid principle":
        return False
    if _normalize_principle(finding.get("principle", "")) != _normalize_principle(
        requirement["principle"]
    ):
        return False
    return _path_matches(finding.get("file", ""), requirement["files_any"])


def grade_review(
    review: dict[str, Any], expected: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Grade anchored review findings without matching generated prose."""
    if expected is None:
        expected = json.loads(EXPECTED_FINDINGS.read_text(encoding="utf-8"))
    findings = review.get("findings")
    if not isinstance(findings, list) or not all(
        isinstance(finding, dict) for finding in findings
    ):
        raise EvaluationError("Review output must contain a findings object array")

    malformed = [
        index
        for index, finding in enumerate(findings)
        if not str(finding.get("trigger", "")).strip()
        or not str(finding.get("impact", "")).strip()
        or not str(finding.get("remediation", "")).strip()
        or not isinstance(finding.get("line"), int)
        or finding["line"] < 1
        or (
            _normalize_text(finding.get("category", "")) == "solid principle"
            and bool(str(finding.get("pattern", "")).strip())
        )
        or (
            _normalize_text(finding.get("category", "")) == "pattern opportunity"
            and bool(str(finding.get("principle", "")).strip())
        )
    ]

    matched_ids: list[str] = []
    missing_ids: list[str] = []
    for requirement in expected["must_find"]:
        if any(_matches_requirement(finding, requirement) for finding in findings):
            matched_ids.append(requirement["id"])
        else:
            missing_ids.append(requirement["id"])

    false_positive_ids: list[str] = []
    for trap in expected["must_not_find"]:
        if any(_matches_requirement(finding, trap) for finding in findings):
            false_positive_ids.append(trap["id"])

    optional_ids: list[str] = []
    for opportunity in expected.get("optional_findings", []):
        expected_pattern = _normalize_text(opportunity["pattern"])
        if any(
            _normalize_text(finding.get("category", "")) == "pattern opportunity"
            and not str(finding.get("principle", "")).strip()
            and _normalize_text(finding.get("pattern", "")) == expected_pattern
            and _path_matches(finding.get("file", ""), opportunity["files_any"])
            for finding in findings
        ):
            optional_ids.append(opportunity["id"])

    required_count = len(expected["must_find"])
    return {
        "passed": not missing_ids and not false_positive_ids and not malformed,
        "assessment_scope": "Structural matching only; independent semantic review of evidence is required.",
        "required_recall": len(matched_ids) / required_count if required_count else 1.0,
        "matched": matched_ids,
        "missing": missing_ids,
        "false_positives": false_positive_ids,
        "malformed_finding_indexes": malformed,
        "optional_matched": optional_ids,
    }


def _execute_codex_review(
    repository: Path,
    *,
    model: str | None,
    reasoning_effort: str,
    timeout: int,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    codex = shutil.which("codex")
    if codex is None:
        raise EvaluationError("codex is required for the behavioral review")

    output_path = repository.parent / "review-output.json"
    command = [
        codex,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--color",
        "never",
        "--sandbox",
        "workspace-write",
        "--config",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--cd",
        str(repository),
        "--output-schema",
        str(OUTPUT_SCHEMA),
        "--output-last-message",
        str(output_path),
    ]
    if model:
        command.extend(["--model", model])
    command.append(REVIEW_PROMPT.read_text(encoding="utf-8"))
    original_diff = _run(
        ["git", "diff", "--binary", "HEAD"], cwd=repository
    ).stdout
    result = _run(command, cwd=repository, timeout=timeout)
    final_diff = _run(["git", "diff", "--binary", "HEAD"], cwd=repository).stdout
    if final_diff != original_diff:
        raise EvaluationError("Codex modified the review fixture during a review-only eval")
    try:
        review = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"Codex did not produce valid review JSON: {exc}") from exc
    return review, result


def run_behavioral_review(
    *,
    model: str | None = None,
    reasoning_effort: str = "high",
    timeout: int = 900,
    keep_workspace: Path | None = None,
) -> dict[str, Any]:
    """Run one fresh Codex review and return its semantic grade."""
    if keep_workspace:
        repository = keep_workspace.resolve()
        if repository.exists() and any(repository.iterdir()):
            raise EvaluationError(f"Keep-workspace destination must be empty: {repository}")
        materialize_repository(repository, stage_skill=True)
        review, process = _execute_codex_review(
            repository,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
        )
    else:
        with tempfile.TemporaryDirectory(
            prefix="code-review-behavioral-eval-"
        ) as temporary:
            repository = Path(temporary) / "ParcelPilot"
            materialize_repository(repository, stage_skill=True)
            review, process = _execute_codex_review(
                repository,
                model=model,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
            )

    return {
        "configuration": {
            "model": model or "Codex default",
            "reasoning_effort": reasoning_effort,
        },
        "grade": grade_review(review),
        "review": review,
        "diagnostics": [
            line
            for line in (process.stderr or "").splitlines()
            if " ERROR " in line or " WARN " in line
        ][:20],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bundled C# code-review behavioral evaluation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "validate", help="Build the fixture and verify its intentional contract failure"
    )

    review_parser = subparsers.add_parser(
        "review", help="Run a fresh Codex review and grade its findings"
    )
    review_parser.add_argument("--model", help="Optional Codex model override")
    review_parser.add_argument(
        "--reasoning-effort",
        default="high",
        help="Codex reasoning effort (default: high)",
    )
    review_parser.add_argument(
        "--timeout", type=int, default=900, help="Codex timeout in seconds"
    )
    review_parser.add_argument(
        "--keep-workspace",
        type=Path,
        help="Keep the materialized fixture at this empty path",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_fixture()
        else:
            result = run_behavioral_review(
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                timeout=args.timeout,
                keep_workspace=args.keep_workspace,
            )
    except (EvaluationError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2))
    if args.command == "review" and not result["grade"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
