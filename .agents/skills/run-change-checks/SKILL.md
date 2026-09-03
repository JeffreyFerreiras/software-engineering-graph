---
name: run-change-checks
description: Select and run focused tests, lint, type checks, and builds for current changes, then fix relevant failures.
---

# Run Change Checks

## Workflow

1. Inspect repository instructions, status, changed files, and the project-native test and lint configuration.
2. Prefer built-in affected-target tooling or dependency graphs. Otherwise select tests for changed modules, direct consumers, and altered public contracts.
3. Run the cheapest focused checks first: formatter or lint, unit tests, type checks, then a build when production code changed or compilation risk remains.
4. Fix failures caused by the current changes or required to validate the requested scope.
5. Re-run the failed focused checks and report exact commands and results.

Do not fix unrelated failures merely because they appear in an impacted file. Record pre-existing or unrelated failures with enough evidence for follow-up. Expand to broader suites only when focused checks pass and the change risk justifies it.
