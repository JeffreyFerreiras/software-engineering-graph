---
name: clean-architecture-review
description: Review code, diffs, pull requests, or architecture plans for Clean Architecture violations and pragmatic design risks. Use when asked for clean architecture review, architecture review, dependency rule checks, layer separation checks, boundary crossing analysis, SOLID review, use case/domain/adapters/infrastructure review, or feedback on whether code is over-abstracted or leaking framework details inward.
---

# Clean Architecture Review

## Overview

Review for architectural behavior first: dependency direction, boundary leakage, misplaced business rules, and abstractions that either protect real boundaries or add needless ceremony. Lead with actionable findings, grounded in file and line references when reviewing code.

Use this focused workflow for architecture questions. For a general diff or regression review, use `code-review` and inspect architectural concerns only where the evidence warrants them. Review requests do not authorize edits.

## Review Workflow

1. Map the code under review to the project's actual layers. Use the local naming, but classify responsibilities as domain, application/use case, interface adapter, infrastructure/framework, and composition.
2. Trace dependencies. Check imports, constructor dependencies, type annotations, return types, tests, and configuration wiring for inward or outward coupling.
3. Inspect boundary crossings. Verify that framework objects, ORM rows, SDK responses, UI props, and transport payloads are translated before reaching domain or use case logic.
4. Locate business rules. Flag rules hidden in controllers, persistence adapters, UI components, migrations, scripts, or SDK wrappers when they belong in domain or application code.
5. Evaluate abstractions. Distinguish useful ports from speculative interfaces, pass-through services, generic repositories, and layers that only rename calls.
6. Review tests. Prefer unit coverage around domain rules and use cases; adapter tests should verify mapping, integration contracts, and failure translation.
7. Report findings by severity. Include concrete impact, file/line evidence, and a focused remediation.

## Checks

Dependency rule:
- Domain must not import application, adapters, infrastructure, UI, framework, database, filesystem, network, or SDK code.
- Application may depend on domain and application-owned ports/DTOs, not adapter implementations.
- Adapters may depend inward and translate data both ways.
- Infrastructure and app composition wire concrete implementations at the edge.

Boundary data:
- Prefer DTOs, value objects, commands, queries, and simple data structures.
- Flag framework request/response objects, ORM entities, SDK models, or UI state passed into inner layers.
- Flag domain entities returned directly to transport/UI layers when that exposes invariants or persistence shape unintentionally.

Ports and dependency inversion:
- Use ports when an inner layer needs persistence, time, IDs, external APIs, messaging, presentation, or side effects.
- Ports should be small and use-case driven.
- Implementations belong outward and are injected through composition.

Layer responsibility:
- Domain owns invariants and core rules.
- Application owns workflow orchestration.
- Adapters own translation.
- Infrastructure owns technical details.
- Composition owns construction and wiring.

SOLID in context:
- SRP: one reason to change per use case, adapter, mapper, and domain service.
- OCP: extension through stable ports where variation is real.
- LSP: implementations must preserve port contracts.
- ISP: ports should not force unused methods.
- DIP: inner policies depend on abstractions, not concretes.

## Severity Guide

- Critical: inner layers depend on frameworks/infrastructure in a way that blocks testing or forces business rules to change with technical details.
- High: business rules live in adapters or infrastructure, or side-effecting dependencies are concrete and hardwired into use cases.
- Medium: DTO/entity mapping leaks, ports are too broad, repositories expose persistence details, or tests only cover outer behavior.
- Low: naming, package placement, or minor abstraction issues that increase confusion but do not currently invert dependencies.

## Output Format

For code reviews, follow the user's requested format if provided. Otherwise:

```markdown
Findings
- [Severity] File:line - Problem, impact, and focused fix.

Open Questions
- Any assumptions that affect the review.

Summary
- Brief overall assessment and test gaps.
```

When no issues are found, say that clearly and note residual risk or unreviewed areas.

## Pragmatic Limits

- Do not require exactly four physical folders. Review the dependency rule and responsibilities, not diagram compliance.
- Do not recommend interfaces solely because Clean Architecture vocabulary exists.
- Do not flag a simple CRUD path as wrong when the extra boundary would add no useful protection.
- Do flag simple code when it puts policy inside volatile frameworks or makes core rules hard to test.

Reference influence: Robert C. Martin's dependency rule and boundary-crossing guidance, plus the linked clean-architecture review skill provided by the user.
