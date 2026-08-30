# Software Engineering Graph technical design

## Authority and scope

This repository is authoritative for the workflow engine, command-line adapter, schemas, tests,
fixtures, documentation, and seven reusable role definitions. The installed profile remains
untouched unless a separately approved task explicitly authorizes profile work.

The repository supports Python 3.9 or newer and the standard library only. It has no packaging,
dependency, CI, deployment, release, installation, or synchronization responsibility. Consumer
repositories own their policy and task artifacts. Repository work must not inspect or mutate a
consumer repository unless that repository is separately in scope.

## Architecture

The engine uses pragmatic inward-pointing boundaries:

- `graph_engine/planner.py` contains deterministic route and fan-out policy. It receives primitives
  and mappings, returns deterministic values, and has no CLI, filesystem, subprocess, or environment
  dependency.
- `graph_engine/validator.py` validates contracts and persisted semantic state. It receives the
  platform case policy explicitly and does not detect runtime environment settings.
- `graph_engine/state.py` owns SQLite transactions, durability, filesystem identity, and atomic
  persistence. Mutation semantic validation is a required callable dependency, not mutable store
  configuration.
- `graph_engine/cli.py` is the composition boundary. Once per invocation it detects whether resource
  names are case-sensitive, builds the semantic-validator closure, and passes both dependencies to
  live, read-only, mutation, and resume paths.

This separation keeps resource-conflict policy deterministic while leaving platform detection and
side effects at the outer boundary.

## Fan-out validation

`validate_fanout_ordering` requires an explicit `case_sensitive` keyword. It preserves the existing
normalization of path separators and trailing separators, graph reachability, cycle detection,
resource conflict checks, service capacity checks, dependency normalization, sorting, and error
codes.

Case-only resource names conflict when `case_sensitive` is false and remain distinct when it is true.
The same value is used when recording a live assessment and when later validating persisted state,
including status, ready/next, mutation closure, and resume flows.

## Mutation transaction contract

`StateStore.mutate` requires a semantic validator for every new mutation. Its ordering is fixed:

1. Compute the request digest.
2. Begin an immediate transaction.
3. Look up the operation. Roll back and replay an identical operation, or reject a conflicting one.
4. Load the run and validate command and run-state eligibility.
5. Validate semantic state before the action.
6. Run the action and build the result.
7. Invoke the existing pre-commit fault hook.
8. Update the revision, then insert the operation and event.
9. Reload and validate semantic state after the action.
10. Commit, or roll back on any exception.

Replay never invokes the action or semantic validator and returns the original resulting revision.
Post-action validation failure rolls back the action, revision, operation, and event together.

## Preserved compatibility

Public CLI commands, JSON output, exit codes, stable IDs, routes, specialist protocol identifiers,
schemas, and SQLite semantics remain unchanged. State schema 5 remains authoritative. Older schema 2,
3, and 4 runs continue to fail closed without migration.

The reusable profile set remains exactly:

- `impact_mapper.toml`
- `tech_lead.toml`
- `software_architect.toml`
- `senior_engineer.toml`
- `code_reviewer.toml`
- `test_engineer.toml`
- `security_reviewer.toml`

Optional application-specialist protocol identifiers remain supported by topology and contract
validation even though their role TOMLs are not part of the reusable profile set. No role
substitution or topology change is introduced.

## Contributor contract

Changes must preserve unrelated work, remain within approved files and behavior, add no dependency
or packaging system, and avoid generated artifacts. Profiles, consumer repositories, remote systems,
publishing, deployment, and release operations require separately approved scope.

Only the focused suite below is permitted during implementation:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_contracts tests.test_planner tests.test_validator tests.test_state tests.test_cli tests.test_graph_hardening
```

After final review, the Supervisor runs the local read-only hygiene check separately and last:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_hygiene
```

Hygiene checks forbidden artifacts, required ignore patterns, the exact seven reusable role files,
repository authority wording, skill-discovery guardrails, and absence of stale external requirements.
It does not repair files or inspect any installed profile or consumer repository.
