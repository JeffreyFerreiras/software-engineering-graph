# Software Engineering Graph

This repository is the canonical source checkout for the Software Engineering Graph workflow and
its seven reusable profile-agent definitions. The separate profile installation is not modified or
managed by this repository.

## Requirements

- Python 3.9 or newer
- Python standard library only

## Local validation

Supported use from this checkout is limited to imports, tests, and displaying CLI help. Operational
commands require a separate consumer repository with its own `.codex/engineering-graph.json` policy
and may discover profile-local state.

This is intentionally a local workflow. It does not add CI or remote automation. Consumer policies
may define each required check's `argv` and optional `timeout_seconds`; run those checks locally with
`graphctl check run`. A check PASS is accepted only when the local runner records a ledger receipt
that matches the command, repository worktree, host, and actor.

The ledger also fences retries with per-claim attempt tokens, exposes expiring branch leases with a
heartbeat command, records local approval attestations, and enforces a deterministic security gate
for critical delivery tasks. Each run now creates a T-shirt-sized execution plan with exact model and
reasoning-effort assignments before any branch can be claimed. `record plan-approval` is required before
Impact Mapper or any other agent executes; the approved plan is included in every branch envelope.

The operational order is `init` with an optional `--size`, review the returned plan, record
`record plan-approval`, and only then use `next --claim`. The plan records assignments for conditional
specialists too, so route narrowing cannot silently introduce a new model or effort level.

These changes use state schema 4. Existing schema-2 or schema-3 runs fail closed and must be started
again; no automatic migration is performed.

Run the focused checks with bytecode disabled:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_graph_hardening
```

The historical byte-parity acceptance test remains for copy-only releases and is not applicable to
this hardening branch, which intentionally changes the runtime contracts.

Run hygiene last when making additional local changes:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:SEG_SOURCE_SKILL = '<absolute-path-to-approved-skill-source>'
$env:SEG_SOURCE_AGENTS = '<absolute-path-to-approved-agent-source>'
python -m unittest -v tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_hygiene
```
