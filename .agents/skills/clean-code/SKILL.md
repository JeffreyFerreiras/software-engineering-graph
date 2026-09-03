---
name: clean-code
description: Write, refactor, or improve production code for clarity, cohesion, maintainability, safety, and testability while preserving behavior and local conventions. Use for clean-code work, focused refactoring, naming and function design, pragmatic SOLID improvements, duplication reduction, or requests previously framed as code quality or Uncle Bob guidance.
---

# Clean Code

## Workflow

1. Inspect the surrounding code, tests, conventions, and current behavior before editing.
2. Identify the concrete readability, design, safety, or maintainability problem. Avoid broad rewrites without a demonstrated benefit.
3. Make the smallest cohesive change that improves the code while preserving public behavior unless a behavior change is requested.
4. Verify with the narrowest relevant tests, lint, type checks, or build commands.
5. Summarize the meaningful improvement and any remaining risk.

## Design Guidance

- Use intention-revealing names consistent with the language and codebase.
- Keep functions and classes cohesive; extract code when it separates responsibilities or levels of abstraction, not to satisfy a line-count rule.
- Make side effects and dependencies explicit. Introduce interfaces only for real boundaries, variation, or useful test seams.
- Reduce duplication when it represents shared knowledge. Do not abstract coincidentally similar code prematurely.
- Keep error handling appropriate to the language and contract. Preserve useful context and handle failures at a deliberate boundary.
- Prefer simple control flow and data shapes over clever compression.
- Keep comments for rationale, constraints, or non-obvious behavior; remove comments that merely narrate the code.
- Treat tests as behavior documentation. Avoid over-mocking and assertions tied to incidental implementation details.

## Pragmatic Limits

- Follow local architecture unless the requested change specifically addresses an architectural problem.
- Do not require strict TDD retroactively. Add or update tests in proportion to behavioral risk.
- Do not force arbitrary limits on function length, parameter count, assertions, or class size.
- Do not turn straightforward code into layers of pass-through abstractions.
- Do not alter unrelated code merely because it could also be cleaner.

## Review Versus Implementation

For review-only requests, report evidence-backed findings without editing. For implementation requests, make the change and validate it. If the request is ambiguous, prefer diagnosis before mutation.
