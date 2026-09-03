---
name: code-review
description: Review local Git changes, a commit range, or a supplied diff for correctness, regressions, security, performance, maintainability, design-pattern opportunities, and project-guideline violations. Use when the user requests a code review, branch review, diff review, pre-merge audit, or evidence-backed findings without implementation.
---

# Code Review

## Workflow

1. Read the applicable `AGENTS.md` and inspect repository status.
2. Use the user-specified range when provided. Otherwise resolve the remote default branch from `refs/remotes/origin/HEAD`, with the current repository's established branch as a fallback.
3. Establish the intended behavior from the user request and any available change, pull-request, or commit description. Compare that intent with the diff. When intent remains unclear, raise an open question rather than assuming an unfamiliar approach is defective.
4. Inspect the diff and enough surrounding code, callers, tests, configuration, and contracts to establish impact. If broad or mixed scope prevents reliable review, explain the limitation and identify coherent review units without imposing a fixed size limit.
5. Inspect available test, lint or format, static-analysis, and presubmit results. Report missing or unavailable validation evidence as residual risk; do not assume a reviewer must rerun checks already evidenced by the workflow.
6. Prioritize behavioral defects and regressions over stylistic preferences or pattern suggestions.
7. Defer to the author's choice when multiple approaches are equally valid. Recommend an alternative only when it addresses a concrete correctness, comprehension, performance, or maintainability cost.
8. Report only actionable findings supported by a concrete failure mode or maintainability cost.

Do not edit files during a review-only request.

## Review Checks

- Correctness, edge cases, error paths, concurrency, and state transitions.
- Authentication, authorization, input handling, secrets, unsafe execution, and data exposure.
- Compatibility of public APIs, schemas, persistence, and configuration.
- Performance risks on plausible hot paths or unbounded inputs.
- Alignment between the stated intent and the diff, including scope that materially obstructs comprehension or validation.
- Test coverage for changed behavior and meaningful failure paths, plus available automated validation evidence.
- Compliance with repository instructions and established local conventions.
- Concrete design pressure that may justify a known pattern, especially repeated variation, scattered state logic, construction policy, boundary adaptation, event fanout, request lifecycle, or dependency creation.
- Evidence-backed violations of each SOLID principle: Single Responsibility (SRP), Open/Closed (OCP), Liskov Substitution (LSP), Interface Segregation (ISP), and Dependency Inversion (DIP).

## SOLID Principle Check

Treat each principle match as a hypothesis, not an automatic finding. Report it only when the diff demonstrates a concrete correctness, comprehension, or maintenance cost:

- **Single Responsibility Principle (SRP):** require distinct responsibilities or reasons to change in the same unit and show the resulting change coupling, coordination burden, or regression risk. Do not infer a violation from file size, method count, or multiple collaborators alone.
- **Open/Closed Principle (OCP):** require demonstrated recurring friction when extending behavior, such as repeated edits to a central branch or repeated modification of stable policy. Do not recommend extensibility for hypothetical variants.
- **Liskov Substitution Principle (LSP):** require a subtype to violate a stated or established base contract, invariant, precondition, postcondition, or compatible behavior. Different implementation details alone are not a violation.
- **Interface Segregation Principle (ISP):** require an actual consumer to depend on unused or inapplicable members, implement meaningless operations, or absorb changes unrelated to its needs. A broad interface alone is insufficient.
- **Dependency Inversion Principle (DIP):** require high-level policy to depend directly on replaceable low-level details, creating a demonstrated testing, substitution, or change cost. Do not equate DIP with Dependency Injection; injection is one possible mechanism and does not by itself establish proper dependency direction.

Search the bundled graph by a principle's full name, acronym, or observed pressure when the diff raises one of these concerns. Keep principle findings distinct from design-pattern opportunities in the review output.

## Pattern Graph Check

Use the bundled graph only when changed code exposes a material design pressure or possible SOLID violation. Do not search for documentation-only, generated, mechanical, or trivially local changes.

1. Describe the observed pressure in domain terms, including the affected responsibility, expected axis of change, and current cost. Do not start with a desired pattern name.
2. Resolve this skill's directory from the loaded `SKILL.md`, then run:

   ```text
   python <skill-directory>/scripts/search_review_graph.py "<observed pressure>" --depth 1 --max-nodes 8 --json
   ```

   Use the repository's configured Python interpreter when one exists. If Python is unavailable, read `references/review-graph.manifest.json` and apply the same one-hop, typed-edge lookup manually.
3. Treat returned patterns and principles as hypotheses. For a pattern, confirm its intent, applicability, tradeoffs, and `avoid_when` conditions. For a principle, confirm its concrete cues and guardrails. Similar class shapes or keywords alone are not evidence of a finding.
4. Prefer the smallest design that handles demonstrated variation. Do not recommend indirection for hypothetical reuse, stable one-off branches, or complexity that the candidate pattern merely relocates.
5. Search at most three distinct material pressures per review. A repository-specific manifest may be supplied with `--manifest` when the repository documents one.

Report a pattern opportunity only when the current design creates a concrete maintenance or correctness cost, the likely direction of change is visible, and the proposed pattern directly addresses both. Name the pattern, but explain the problem and tradeoff rather than relying on the name as justification. Report a SOLID principle finding only when the violated contract or design pressure and its concrete cost are demonstrated. Pattern and principle findings never displace higher-severity defects.

## Severity

- Critical: likely compromise, data loss, or broadly broken production behavior.
- High: likely user-visible failure or serious security/correctness regression.
- Medium: conditional defect, compatibility risk, or material maintainability problem.
- Low: localized issue with limited impact. Omit optional style preferences and speculative pattern use.

## Output

Lead with findings ordered by severity. For each finding, include the file and line, the triggering conditions, impact, and a focused remediation. Label an evidence-backed pattern finding as `Pattern opportunity` and include the matched design pressure, candidate pattern, and material tradeoff. Label an evidence-backed principle finding as `SOLID principle` and name the individual principle, demonstrated violation, and concrete cost. Then note open questions and residual test risk. If no findings remain, say so explicitly.
