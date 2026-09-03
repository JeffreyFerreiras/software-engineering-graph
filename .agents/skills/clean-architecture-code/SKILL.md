---
name: clean-architecture-code
description: Write, refactor, or extend production code using Clean Architecture boundaries. Use when implementing features, domain logic, application use cases, ports, adapters, persistence, API/UI integration, dependency inversion, DTO mapping, repository boundaries, framework isolation, or SOLID-oriented code changes where source dependencies must point inward.
---

# Clean Architecture Code

## Overview

Use Clean Architecture as a constraint on implementation, not as ceremony. Keep business rules independent, let application use cases coordinate workflows, and push frameworks, databases, UI, network, filesystem, and SDK details outward.

## Workflow

1. Inspect the existing structure before editing. Identify the current layer names and local conventions; do not impose a four-folder template if the project already has a clear equivalent.
2. Name the policy being added or changed. Decide whether it belongs in domain rules, an application use case, an adapter, infrastructure, or composition.
3. Preserve the dependency rule. Inner code must not import outer code. If control must cross outward, define a port/interface in the inner layer and implement it outward.
4. Keep boundary data simple. Use DTOs, primitives, value objects, or simple request/response models across layer boundaries. Do not pass framework requests, ORM rows, SDK clients, UI components, or database objects inward.
5. Add the narrowest abstraction that protects an actual boundary. Avoid interfaces for every class; prefer ports for side effects, policy variation, persistence, external services, and presentation/output boundaries.
6. Test from the inside out. Cover domain rules and use cases with unit tests before relying on adapter or framework tests.

## Layer Guide

- Domain/entities: enterprise and product rules, invariants, value objects, domain services. No framework, database, HTTP, filesystem, LLM SDK, UI, or environment imports.
- Application/use cases: user or system workflows. Orchestrate domain objects, transaction boundaries, ports, DTOs, and authorization/policy checks that are application-specific.
- Interface adapters: controllers, presenters, mappers, gateways, view models, serializers, and repository adapters. Translate between external formats and application/domain models.
- Infrastructure/frameworks: database clients, web framework wiring, SDK clients, filesystem/network access, queues, runtime configuration, and dependency injection composition.

## Implementation Rules

- Put business decisions in names that describe the domain, not the transport or framework.
- Prefer use cases with one reason to change. A use case may coordinate several collaborators, but should represent one workflow.
- Define ports close to the use case that owns the need. Let outer adapters depend on those ports.
- Keep repositories as collections or persistence ports for aggregates/domain concepts, not as generic database pass-throughs.
- Put mapping at boundaries. Do not let ORM entities, JSON payloads, React props, FastAPI/Express request objects, or SDK response types become domain objects.
- Compose dependencies at the outermost application entry point.
- When adding an adapter, include failure mapping and retry/timeout policy at the boundary; keep core logic independent of those mechanics.
- Prefer explicit dependency injection over service locators and hidden globals.

## Boundary Patterns

Use this pattern when an inner use case must trigger an outer behavior:

```text
application/use-case defines OutputPort or GatewayPort
adapter implements that port
infrastructure wires implementation into the use case
```

Use direct calls only when the dependency points inward:

```text
controller -> use case -> domain
repository implementation -> application repository port
presenter -> application output DTO
```

## Pragmatic Limits

- Do not add layers that the feature does not need.
- Do not create an interface with one implementation unless it protects a real boundary or test seam.
- Do not split an anemic CRUD path into excessive classes just to satisfy a diagram.
- Do refactor toward boundaries when framework or persistence concerns are already leaking into business rules.

## Before Finishing

- Verify inner layers have no imports from outer layers.
- Verify use cases depend on abstractions for side effects.
- Verify DTOs or simple data cross boundaries.
- Verify tests cover the changed domain rules or use cases.
- State any intentional boundary compromise and why it is acceptable.

Reference influence: Robert C. Martin's dependency rule and boundary-crossing guidance, plus the linked clean-architecture review skill provided by the user.
