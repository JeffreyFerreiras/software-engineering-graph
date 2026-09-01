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

The workflow is deliberately bounded. It limits design and repair loops, separates writing from
review, records evidence, and returns unresolved product or risk decisions to the human.

## How the AI agents work together

1. The Supervisor turns the request into a scoped task brief with acceptance criteria and non-goals.
2. The skill sizes the work and proposes exact AI model and reasoning-effort assignments.
3. The human approves the plan before any specialist agent starts.
4. Design routes first run the assessed architecture/validation research fan-out. The Supervisor
   seals its evidence collection before creating the same-generation Tech Lead branch, then the
   selected agents continue through bounded design, implementation, review, and test handoffs.
5. The Supervisor closes the run only when the approved criteria and required checks have evidence.

A local control ledger tracks assignments, approvals, retries, active-work ownership, and recovery
so the workflow behaves consistently and deterministically. It coordinates agents but does not
execute them. The Supervisor is the sole ledger operator and remains the user-facing decision maker.

## Using the skill

In a Codex environment where this skill is installed, ask Codex to use
`software-engineering-graph` for the task. For example:

> Use the software-engineering-graph skill for this feature. Before any specialist agents start,
> show me the exact AI-agent roles, models, and reasoning-effort levels you propose, and ask me to
> approve the plan.

The consumer repository supplies its own `.codex/engineering-graph.json` policy, including the local
commands that count as required checks. This source repository does not install itself or modify a
consumer repository, an installed profile, or any remote system without separately approved scope.

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
- State schema 5; older schema 2, 3, and 4 runs fail closed and must be restarted
- Every Luna assignment uses `max` reasoning effort. Tech Lead and Architect assignments use
  `gpt-5.6-sol` at every size. Research output contracts require an `evidence_manifest`, verified
  evidence, a null decision, and empty findings.

On Windows, the ledger requires `--ack-degraded-permissions` because Python cannot prove exclusive
profile permissions. `--ack-degraded-durability` is only for environments where directory syncing is
unavailable and that limitation is acceptable. These flags acknowledge platform limitations; they
do not grant extra authority.

## Contributor validation

Run only the focused acceptance suite below, with bytecode disabled:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_contracts tests.test_planner tests.test_validator tests.test_state tests.test_cli tests.test_graph_hardening
```

After final review, run the local read-only hygiene check separately and last:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_hygiene
```

The hygiene check verifies forbidden artifacts, required ignore patterns, the exact seven role files,
repository authority wording, skill-discovery guardrails, and stale external requirements. It does
not repair files or inspect an installed profile or consumer repository.
