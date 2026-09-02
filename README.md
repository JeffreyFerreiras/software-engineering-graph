# Software Engineering Graph

Software Engineering Graph is an **AI-agent skill for Codex**. It organizes complex software work
across specialized AI agents and makes scope, human approval, design, implementation, independent
review, and testing explicit.

Use it for non-trivial features, fixes, refactors, migrations, integrations, and
production-sensitive work. Documentation and mechanical changes can use a smaller, faster route.

This repository is authoritative for the AI skill, its local workflow engine, and its seven reusable
agent-role definitions. It is not a general-purpose task scheduler, CI service, or security boundary.
The installed profile remains untouched unless separately approved work explicitly changes it.

## What the skill does

The skill keeps the primary Codex agent in charge as the **Supervisor**. The Supervisor scopes the
request, proposes an execution plan, asks the human to approve that plan, and then coordinates only
the roles the work needs:

- **Impact Mapper** classifies the change and selects the minimum safe route.
- **Architecture and Validation Researchers** perform a fixed, bounded two-member evidence
  fan-out before every Tech Lead design generation. They use the Impact Mapper role, return only
  verified evidence manifests, and have no write, test, decision, or findings authority.
- **Tech Lead** designs the change and plans its implementation.
- **Software Architect** independently reviews the design.
- **Senior Engineer** is the sole implementation writer.
- **Code Reviewer** independently reviews the completed change.
- **Test Engineer** verifies the acceptance criteria and regression evidence.
- **Security Reviewer** joins when security, privacy, identity, secrets, or trust boundaries are
  affected.
- **Pull Request Engineer** is the required instruction-level publication role for every repository
  implementation intended for delivery. After all gates pass, a fresh `gpt-5.6-luna` `max` dispatch
  publishes the reviewed change. A separately approved later dispatch may remove its exact approved,
  clean worktree. The role adds no eighth reusable profile or engine node.

The workflow is deliberately bounded. It limits design and repair loops, separates writing from
review, records evidence, and returns unresolved product or risk decisions to the human.

## How the AI agents work together

1. The Supervisor turns the request into a scoped task brief with acceptance criteria and non-goals.
2. The skill sizes the work and proposes exact AI model and reasoning-effort assignments.
3. The human approves the plan before any specialist agent starts.
4. Design routes first run the assessed architecture/validation research fan-out. The Supervisor
   seals its evidence collection before creating the same-generation Tech Lead branch, then the
   selected agents continue through bounded design, implementation, review, and test handoffs.
5. After the approved criteria, reviews, and checks pass, the Pull Request Engineer creates exactly one
   review-ready pull request or updates and verifies the exact existing pull request.
6. The Supervisor closes the run only after validating that publication evidence.

When both repository policy and task brief opt in, an approved execution-plan v2 can also contain
conditional review assignments. A primary Code Reviewer may then return a frozen preliminary review
and a typed request using only approved assignment, reason, acceptance, and evidence IDs. The
Supervisor remains the only dispatcher and ledger mutator. Delegated reviewers receive fresh,
read-only envelopes and cannot create another delegation level.

A local control ledger tracks assignments, approvals, retries, active-work ownership, and recovery
so the workflow behaves consistently and deterministically. It coordinates agents but does not
execute them. The Supervisor is the sole ledger operator and remains the user-facing decision maker.
It validates publication evidence but never commits, pushes, creates a pull request, or removes a
worktree. The Senior Engineer remains the sole source and test writer and never publishes.

The Supervisor preflight recommends `gpt-5.6-sol` with `xhigh` reasoning. Unless a trusted host runtime
assertion verifies that exact actual assignment, the Supervisor operates in advisory mode and displays:

> Supervisor warning: This Supervisor is an advisory role and thought partner. Treat its plans, decisions, and synthesis as recommendations requiring your approval.

## Using the skill

In a Codex environment where this skill is installed, ask Codex to use
`software-engineering-graph` for the task. For example:

> Use the software-engineering-graph skill for this feature. Before any specialist agents start,
> show me the exact AI-agent roles, models, and reasoning-effort levels you propose, and ask me to
> approve the plan.

The consumer repository supplies its own `.codex/engineering-graph.json` policy, including the local
commands that count as required checks. This source repository does not install itself or modify a
consumer repository, an installed profile, or any remote system outside an approved repository
implementation scope and the publication contract below.

## Repository map

- [`SKILL.md`](SKILL.md) defines the AI skill and its operating contract.
- [`profile-agents/`](profile-agents/) contains the seven reusable Codex role profiles.
- [`graph_engine/`](graph_engine/) implements deterministic planning, validation, and local state.
- [`scripts/graphctl.py`](scripts/graphctl.py) is the command-line adapter used by the Supervisor.
- [`references/`](references/) contains schemas and workflow contracts.
- [`docs/technical-design.md`](docs/technical-design.md) explains the internal architecture and
  compatibility guarantees.
- [`tests/`](tests/) contains the standalone acceptance and behavior tests.

## Requirements and boundaries

- Python 3.9 or newer
- Python standard library only
- Local operation only, with no CI or remote automation added by this repository
- Pull-request publication is a required instruction-level delivery contract for repository
  implementation, not an engine-enforced topology or remote provider implementation
- State schema 6; schema-5 runs finish under the old engine or restart under schema 6, with no
  in-place migration or downgrade
- Every Luna assignment uses `max` reasoning effort. Tech Lead and Architect assignments use
  `gpt-5.6-sol` at every size. Research output contracts require an `evidence_manifest`, verified
  evidence, a null decision, and empty findings.

Publication work uses a dedicated registered worktree in one of two admissible states: clean at the
exact reviewed commit; or with its complete staged and unstaged state exactly equal to the reviewed
diff and no other tracked change, untracked or ignored entry, conflict, or active Git operation. In the
second state, the Pull Request Engineer may stage and commit exactly that state without changing file
content. It receives only the reviewed stable change and exact repository, remote, base, and head
authority. It never forces, amends, rewrites history, or creates a duplicate pull request, creates a
draft only when explicitly requested, and otherwise creates a review-ready pull request. It refuses
every other uncommitted or unrelated state, secret risk, and identity mismatches.

The user's authorization for repository implementation and approval of its initial execution plan are
sufficient authority for the normal non-force commit, push, and pull-request actions after every
required gate passes. The plan names the Pull Request Engineer and exact repository, remote, base, head,
and action authority. No separate publication-specific approval or second approval immediately before
push or pull-request creation is required. The effort cannot close successfully until exactly one
review-ready pull request is created or the exact existing pull request is updated and verified. An
explicitly requested draft is the only exception to review-ready status.

Before publication or cleanup, the Pull Request Engineer inspects only its exposed session skill
catalog and local skills explicitly declared by applicable repository instructions; it does not crawl
arbitrary profile or global skill directories. It selects the smallest relevant set for that phase and
reads every selected `SKILL.md` fully. Its assignment and protocol do not prescribe or name a specific
optional skill. A discovered skill may change method only, never approved scope, phase, model or effort,
authority, writable files, Git, GitHub, or worktree actions, external effects, or permission to install,
synchronize, remove, or mutate skills, profiles, or consumer repositories. Controlling instructions
win and conflicts are reported. An unavailable catalog or unreadable selected skill is reported, and
work proceeds only when the controlling instructions suffice. Each publication or cleanup handoff has
a `Skill usage` section with every selected skill's name, safe provenance, relevance, and failures, or
`None`.

After the exact pull request approval is verified, separately approved cleanup uses a fresh Luna-max
dispatch from another worktree. It may only remove the exact clean, registered, unlocked worktree with
non-forced `git worktree remove`; any tracked, staged, untracked, ignored, locked, or ambiguous state
fails closed. Cleanup preserves the branch and never recursively deletes, forces, prunes, or deletes
the branch, so the worktree remains recreatable.

On Windows, the ledger requires `--ack-degraded-permissions` because Python cannot prove exclusive
profile permissions. `--ack-degraded-durability` is only for environments where directory syncing is
unavailable and that limitation is acceptable. These flags acknowledge platform limitations; they
do not grant extra authority.

## Contributor validation

Run only the focused acceptance suite below, with bytecode disabled:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_contracts tests.test_planner tests.test_validator tests.test_state tests.test_cli tests.test_graph_hardening tests.test_reviewer_delegation
```

After final review, run the local read-only hygiene check separately and last:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_hygiene
```

The hygiene check verifies forbidden artifacts, required ignore patterns, the exact seven role files,
repository authority wording, skill-discovery guardrails, and stale external requirements. It does
not repair files or inspect an installed profile or consumer repository.
