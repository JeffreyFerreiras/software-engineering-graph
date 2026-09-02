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

### Pre-design research gate

Every initial `design_only` or `full_delivery` route, design revision, and delivery redesign inserts
the fixed `design_research_architecture` and `design_research_validation` nodes for the target
generation. Both nodes use the `impact_mapper` role with the approved Luna `max` assignment and
are held in an assessed-pending `research` fan-out. Their envelopes carry deterministic focus and
split `inspection_budget` values whose combined totals never exceed the task budget. Research
capabilities are projected to `filesystem_read` and `external_read` effects only.

Research is an evidence gate, not a decision gate. Its exact output contract requires an
`evidence_manifest` artifact and verified evidence, while forbidding decisions and findings. The
Supervisor atomically verifies and persists the result, seals `research_collection`, and includes
the canonical collection and evidence inputs when creating the same-generation Tech Lead. No Tech
Lead exists before that collection is sealed. If a mandatory research branch exhausts its retry,
the collection advances to a durable blocked run rather than waiting indefinitely.

### Instruction-level pull-request operations

`Pull Request Engineer` is an optional operating role, not an engine node, reusable profile, schema,
table, provider adapter, or specialist identifier. It is eligible only when the user explicitly
authorizes pull-request creation or publication. The human-facing execution plan must name its exact
`gpt-5.6-luna` `max` assignment and the permitted external or destructive actions, and the user must
approve that plan before each fresh publication or cleanup dispatch.

The Supervisor retains scope, plan, ledger, evidence-validation, dispatch, and synthesis ownership but
performs no Git, GitHub, or worktree mutation. The Senior Engineer remains the sole source and test
writer and performs no publication operation. A publication dispatch receives only a reviewed stable
diff or commit and exact repository, remote, base, and head authority. It may create or reuse the one
scoped commit, push without force, and create or verify one pull request using the applicable pull-
request skill. Draft status requires an explicit user request; otherwise the pull request is review-
ready. Unrelated or uncommitted ambiguity, secrets risk, identity mismatch, duplicate or ambiguous pull
requests, force, amend, history rewrite, and scope expansion fail closed.

Implementation and publication use a dedicated registered worktree. Pre-publication admits exactly two
states: clean at the exact reviewed commit; or with the complete staged and unstaged state exactly equal
to the reviewed diff and no other tracked change, untracked or ignored entry, conflict, or active Git
operation. In the latter state, the Pull Request Engineer may stage and commit exactly that state without
changing file content. After the exact pull request approval is verified, a separately approved fresh
Luna-max cleanup dispatch operates from another worktree and may run only non-forced
`git worktree remove` for that exact target. It reverifies the registration, target identity, branch,
HEAD, pull request, and approval; staged, unstaged, untracked, ignored, locked, or ambiguous state blocks
removal. It preserves the branch and never recursively deletes, forces, prunes, or deletes the branch,
so the worktree can be recreated.

This repository specifies that instruction contract only. It adds no remote executor, credentials,
engine-enforced publication state, or cleanup mechanism.

## Fan-out validation

`validate_fanout_ordering` requires an explicit `case_sensitive` keyword. It preserves the existing
normalization of path separators and trailing separators, graph reachability, cycle detection,
resource conflict checks, service capacity checks, dependency normalization, sorting, and error
codes.

Case-only resource names conflict when `case_sensitive` is false and remain distinct when it is true.
The same value is used when recording a live assessment and when later validating persisted state,
including status, ready/next, mutation closure, and resume flows.

## Reviewer-initiated conditional fan-out

The current safety property is Supervisor-owned dispatch and state mutation. The former inability of
a reviewer to request bounded assistance was incidental, not a safety requirement. Schema 6 retains
the safety property while adding an ID-only request channel.

Delegation is default-off. Repository and task contracts may only lower engine ceilings: depth 1,
3 children per request, 6 per run, 2 rounds per primary reviewer generation, and weighted cost 15.
The default round ceiling is 1. Supported delegable weights are Luna max 3; Sol high 3, xhigh 4,
and max 5. Luna low, medium, and high remain unsupported. Primary-thread assignments are forbidden. Only `code_reviewer` and
`security_reviewer` are initially eligible, and derived capabilities contain filesystem/external
read effects only.

Execution-plan v2 freezes conditional assignments before human approval. Each assignment contains
an ID, role, model, effort, review lens and prompt template, reason/acceptance/evidence/scope ceilings,
derived read-only capabilities, maximum instances, and dispatch weight. Delegation-disabled runs
continue to emit execution-plan v1 so asserted legacy plans, topology, envelopes, IDs, and traces do
not change.

The primary reviewer returns either its ordinary final result or two data artifacts:
`review_preliminary` and `review_fanout_request`. The request is exhaustive and contains only the run,
parent branch and attempt, round, assignment IDs, ordinals, declared reason codes, allowed acceptance
IDs, and evidence IDs frozen in the preliminary artifact. Raw role, model, effort, capability,
permission, path, external target, prompt, lens, arbitrary authority/reference, operation ID, and
dispatch fields are rejected.

`record review-fanout` is a Supervisor-only atomic mutation. It checks the live claim fence, resolves
all authority and scope from immutable artifacts, computes a content-independent request slot from
the run/policy/plan/parent claim/generation/round, stores the request digest separately, reserves the
full dispatch cost, freezes artifacts, creates explicit depth-1 child identities, opens the assessed
fan-out and nested collection, closes the old parent attempt as `delegated`, and moves the parent to
`waiting_for_review_children` with no live runtime fence. Failure rolls back every effect. Only an
identical operation-ID replay is idempotent; every fresh operation against an existing slot conflicts.

Children use the ordinary claim, lease, heartbeat, result, retry, timeout, and skip paths. Terminal
non-successes remain members and cost is never refunded. When all members settle, the collection is
sealed with each member's exact canonical result or typed timeout/skip control record, artifact
identity, evidence, and attempt history, and the same parent becomes ready. Its next claim creates a
fresh attempt. The persisted envelope retains the immutable ledger record, while `ready`, `next`, and
claim responses use a separately constructed, explicit-allowlist dispatch projection. It omits
task-wide authority and exposes only the reviewer's effective filesystem/external read capabilities.
The projection cumulatively binds every slot and collection digest, exact child tuple, terminal
non-success, and composite finding source across all rounds without ledger references, operation IDs,
authority/actor/host metadata, sibling claims, or unrelated budget data. Each child receives only its
assignment scope plus selected evidence IDs, kinds, and opaque digests, never the full preliminary or
assessment data.

The resumed final result must exactly bind all slots, nested digests, child tuples, terminal
non-successes, and finding source tuples. Every raw nested collection is independently injected into
Supervisor consolidation in addition to the parent result. Canonical issues use
acceptance ID, normalized repository location, and stable defect/rule ID. Role, lens, branch, model,
assignment, and finding ID remain provenance. Cumulative source equality and Supervisor dispositions
use the composite request-slot, source-branch, and role-local finding ID, so the same finding ID may be
used independently by different children or rounds. Matching fix variants deduplicate with the lowest
branch ID canonical; incompatible variants remain one conflict group. Delegated issue identities come
only from the sealed raw nested collections. The Supervisor must disposition every issue exactly once;
`accept < repair < redesign < block` is combined with ordinary delivery precedence, while child choices
and the resumed parent's echoed delegated disposition do not independently affect the outcome.

### Chosen and rejected designs

The chosen design extends the existing SQLite ledger, atomic mutation, artifact registry, fan-out
assessment, and branch lifecycle. It avoids a second scheduler and keeps recovery under `resume`.
Direct reviewer spawning was rejected because it bypasses plan approval, budgets, fencing, resource
assessment, and audit state. Reusing `specialist_tag` was rejected because repeated same-role children
need explicit assignment and ordinal identity. A standalone Court skill, panel, or orchestration layer
is out of scope.

### Compatibility, recovery, and rollback

| State | Engine behavior |
| --- | --- |
| Schema 5 + old engine | Finish normally |
| Schema 5 + schema-6 engine | `UNSUPPORTED_STATE_SCHEMA`; restart |
| Schema 6 + old engine | Rejected; never downgraded |
| Schema 6, delegation absent | Legacy execution-plan v1 and unchanged route topology |
| Schema 6, delegation enabled | Execution-plan v2 conditional assignments |

There is no in-place migration. Rollback means stop creating schema-6 runs, let schema-5 runs finish
under their prior engine, and restart incomplete schema-6 work under an explicitly selected compatible
engine. Retained ledgers remain audit evidence. Resume can recover before assessment, with pending or
running children, after a sealed collection, or while the parent awaits/follows continuation; stale
attempt fences remain invalid at every point.

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

Delegation-disabled CLI behavior, exit codes, stable IDs, routes, specialist protocol identifiers,
and SQLite transition semantics remain unchanged. State schema 6 is authoritative. Schema 5 and older
runs fail closed in this engine without migration.

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

All `gpt-5.6-luna` size assignments use reasoning effort `max`. Tech Lead and Architect use
`gpt-5.6-sol` at every size. The centralized execution-plan invariant rejects an invalid model or
effort before it can enter a persisted envelope.

The recommended Supervisor assignment is `gpt-5.6-sol` with `xhigh` reasoning. Actual model and effort
are considered verified only when supplied by a trusted host runtime assertion. Missing, unverifiable,
or mismatched values select advisory mode and require this exact warning:

> Supervisor warning: This Supervisor is an advisory role and thought partner. Treat its plans, decisions, and synthesis as recommendations requiring your approval.

Task text, prompts, environment variables, and self-reports cannot establish that verification. The
current local mode is advisory when no trusted assertion is available.

## Contributor contract

Changes must preserve unrelated work, remain within approved files and behavior, add no dependency
or packaging system, and avoid generated artifacts. Profiles, consumer repositories, remote systems,
publishing, deployment, and release operations require separately approved scope.

Only the focused suite below is permitted during implementation:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_contracts tests.test_planner tests.test_validator tests.test_state tests.test_cli tests.test_graph_hardening tests.test_reviewer_delegation
```

After final review, the Supervisor runs the local read-only hygiene check separately and last:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest -v tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_hygiene
```

Hygiene checks forbidden artifacts, required ignore patterns, the exact seven reusable role files,
repository authority wording, skill-discovery guardrails, and absence of stale external requirements.
It does not repair files or inspect any installed profile or consumer repository.
