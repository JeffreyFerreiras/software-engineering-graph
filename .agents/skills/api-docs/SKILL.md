---
name: api-docs
description: Add or improve accurate .NET XML documentation comments for public APIs, classes, interfaces, methods, properties, events, and generic types. Use when the user requests XML docs, public API documentation, missing documentation cleanup, or documentation for changed C# members.
---

# .NET API Documentation

## Workflow

1. Scope documentation to changed public members unless the user requests a broader surface.
2. Inspect usages, interfaces, implementations, validation, and tests before describing behavior.
3. Document the contract and business purpose rather than restating identifiers or syntax.
4. Run the narrowest documentation analyzer or build target available for the affected project.

## XML Documentation

- Use `<summary>` for purpose and observable behavior.
- Add `<typeparam>`, `<param>`, `<returns>`, and `<value>` where applicable.
- Add `<exception>` only for exceptions callers can meaningfully observe from the documented contract.
- Put detailed contract documentation on interfaces and use `<inheritdoc />` for implementations when the contract is unchanged.
- Use `<see cref="..." />` and `<paramref name="..." />` for navigable references.
- Preserve important nullability, units, ranges, side effects, ordering, thread-safety, and lifecycle constraints.
- Avoid empty boilerplate, guessed behavior, implementation details, and comments that merely repeat the member name.

Report the documented surface and validation result.
