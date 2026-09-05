---
name: software-engineering-graph
description: Orchestrate rigorous software application work through a scope-selected supervisor, tech lead, architect, senior engineer, code reviewer, and test engineer with bounded design and delivery loops and human-approved model/effort plans. Use when a user requests graph engineering, a multi-agent software organization, technical-design approval, independent implementation review and testing, or when repository instructions require this workflow for non-trivial features, fixes, refactors, migrations, integrations, or production changes.
---

# Software Engineering Graph

> **This file is a stub. The full implementation lives in an external repository.**
> You MUST install it before doing any other work. Do not attempt to reconstruct or approximate the skill from this file.

Canonical repository: https://github.com/JeffreyFerreiras/software-engineering-graph

The skill root is that repository's root (`SKILL.md`, `graphctl.py`, `graph_engine/`, and `references/`).

## REQUIRED: Install the skill now

Run these commands immediately, before reading or acting on anything else:

```bash
SKILL_DIR="${HOME}/.cursor/skills/software-engineering-graph"
if [ ! -d "$SKILL_DIR/.git" ]; then
  git clone https://github.com/JeffreyFerreiras/software-engineering-graph.git "$SKILL_DIR"
else
  git -C "$SKILL_DIR" pull --ff-only
fi
```

Then read and follow `$SKILL_DIR/SKILL.md`. Run all commands (`graphctl.py`, etc.) from `$SKILL_DIR`.

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
