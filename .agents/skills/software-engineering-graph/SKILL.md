---
name: software-engineering-graph
description: Orchestrate rigorous software application work through a scope-selected supervisor, tech lead, architect, senior engineer, code reviewer, and test engineer with bounded design and delivery loops and human-approved model/effort plans. Use when a user requests graph engineering, a multi-agent software organization, technical-design approval, independent implementation review and testing, or when repository instructions require this workflow for non-trivial features, fixes, refactors, migrations, integrations, or production changes.
---

# Software Engineering Graph

This file resolves an externally managed dependency. Reading or auditing it does not authorize installation, updates, or graph execution. Do not reconstruct the engine from this stub.

Canonical repository: https://github.com/JeffreyFerreiras/software-engineering-graph

The skill root is that repository's root (`SKILL.md`, `scripts/graphctl.py`, `graph_engine/`, and `references/`).

## Resolve the dependency

1. For an authorized graph task, discover the full installation from loaded skill paths or the user's configured profile. Verify the required files in [external-source.json](external-source.json); do not assume a Cursor path or a shell.
2. Use an existing valid installation without pulling updates. Record its version or Git commit and read its own SKILL.md before running its commands.
3. If it is missing, identify the exact dependency and destination. Install only when the task includes setup or existing authorization covers it. Otherwise report the missing dependency and continue independent authorized work.
4. For authorized installation, resolve the user-requested version or a concrete upstream commit, record that revision, and check out that exact revision using the host's shell. Do not follow a moving branch during execution. Verify the required files and runtime capabilities before dispatch.
5. Run engine commands from the verified installation root. Treat updates as a separate requested operation.

The `external-source.json` marker tells bulk sync to leave this skill to its external manager, preserving installed engines rather than replacing them with this stub.

Do not copy the engine, schemas, or tests back into this repository — a local replica would drift from the source of truth.

## Delegation transparency

<!-- dispatch-transparency:start -->
Immediately before every dispatch, tell the user the concrete agent or task name, the bounded scope,
the exact approved model, and the exact approved reasoning effort. This applies to every initial dispatch,
fan-out member, retry, replacement, follow-up, and same-role continuation. Refuse the dispatch when
the concrete identity or any approved assignment value is unavailable, unverifiable, or mismatched;
do not infer, substitute, or silently inherit missing values. When dispatching several agents together,
use one compact announcement that lists every concrete name and identifies which work will run in parallel.
<!-- dispatch-transparency:end -->
