# Software Engineering Graph

This repository is authoritative for the Software Engineering Graph workflow and its seven reusable
profile-agent definitions. The installed profile remains untouched unless separately approved work
explicitly changes it.

## Requirements

- Python 3.9 or newer
- Python standard library only

## Local validation

Operational commands act on an explicitly selected consumer repository with its own
`.codex/engineering-graph.json` policy. Repository development and validation do not read, compare,
install, or update profile files.

This is intentionally a local workflow. It does not add CI or remote automation. Consumer policies
may define each required check's `argv` and optional `timeout_seconds`; run those checks locally with
`graphctl check run`. A check PASS is accepted only when the local runner records a ledger receipt
that matches the command, repository worktree, host, and actor.

The ledger also fences retries with durable per-claim attempt records, exposes expiring branch leases with a
heartbeat command, records local approval attestations, and enforces a deterministic security gate
for critical delivery tasks. Each run now creates a T-shirt-sized execution plan with exact model and
reasoning-effort assignments before any branch can be claimed. `record plan-approval` is required before
Impact Mapper or any other agent executes; the approved plan is included in every branch envelope.

Before acting, the Senior Engineer and Code Reviewer inspect only session-exposed and
repository-instruction-declared skills, select and fully read the smallest relevant set, and report
their selection or `None` under `Skill usage`. Skills may change method only; they do not expand role
authority, approved scope, writable files, tests, delegation, external effects, or profile and consumer
permissions. The Code Reviewer remains read-only and the Senior Engineer remains the sole code writer.

The operational order is `init` with an optional `--size`, review the returned plan, record
`record plan-approval`, and only then use `next --claim`. Before any multi-member fixed review fan-out,
`status` requires one immutable `record fanout-assessment`. Its manifest must cover every member's exact
or subtree writable paths, mutable-state references, exclusive devices, constrained service units and
capacity, verified evidence, and any ordering dependencies. Independent roots then become ready together;
ordered successors wait for settled predecessors. This is resource safety for the fixed graph, not a
general DAG scheduler or agent executor.

These changes use state schema 5. Existing schema-2, schema-3, or schema-4 runs fail closed and must be
started again; no automatic migration is performed. `status` reports UTC wall-clock run, stage, branch,
overlap, slowest-branch, and semantic critical-path metrics from immutable attempt intervals.

Run the focused checks with bytecode disabled:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_contracts tests.test_planner tests.test_validator tests.test_state tests.test_cli tests.test_graph_hardening
```

After the Supervisor approves the final review, run the local read-only hygiene check separately and
last:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_hygiene
```
