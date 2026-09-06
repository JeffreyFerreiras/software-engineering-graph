# Software Engineering Graph technical design

## Optional token telemetry

`graph_engine/usage.py` owns the bounded `codex_jsonl_v1` source adapter, sanitized checkpoint
contract, cumulative-delta reducer, and reports. `record usage` adds only one permission entry
to the existing mutation-state matrix and persists optional `usage_schema_version: 1` observations
in `events.detail_json`. There are no new tables, state schema version changes, artifact kinds,
policy requirements, dispatch behavior, or delivery gates. Existing schema-6 runs remain compatible.

The adapter snapshots one explicitly named regular file. It verifies all path components, opened
handle identity, stable sampled bytes, and post-read identity under fixed size/record/depth limits.
Only metadata counters, finite normalized model/effort values, offsets, SHA-256 source/prefix
identities, and fixed diagnostics survive parsing. The raw path and source payloads never enter
the request passed to `StateStore.mutate`, which persists requests verbatim. Candidate metadata is
prepared outside the write transaction; the transaction rechecks prior usage state before applying
it. Existing operation replay, revision, semantic-validation, and rollback envelopes are preserved.

Each engine-generated binding associates a session source with one executed branch attempt or a
Supervisor phase/generation. Open and closed intervals for the same source may not overlap within
a run. Cumulative input/output deltas are counted once, identical snapshots ignored, optional subsets
kept separate, resets disclosed, and rewritten prefixes never silently restarted. Historical
checkpoints require source identity, prefix hash, and a full snapshot boundary or offset zero.
The independent read-only checkpoint command works before repository or ledger initialization.

Attribution follows settled counters and observed context. Ambiguous in-run increments remain in
the run total with unknown dimensions/unattributed phase; potentially pre-run increments remain
excluded. Reports expose coverage and association gaps, running state, five phases, roles, branch
agents, attempts, generations, models, efforts, and model/effort pairs. Aggregate coverage remains
provisional during a live run. Optional malformed usage state yields unavailable usage without
bypassing core graph validation. Closed-interval completeness is not a host authenticity or global
usage attestation. See [the usage contract](../README.md#observed-token-usage) for exact limits,
supported observed JSONL shape, checkpoint arguments, and source-association responsibilities.

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

### Host model catalogs

Role intelligence is a host-agnostic class plus requested effort, not a vendor model ID.
`graph_engine/hosts.py` expands `(class, effort)` through `HOST_MATRIX`:

| Class | Requested effort | Explicit Codex fallback | Cursor runtime |
| --- | --- | --- | --- |
| `economy` | `max` | `gpt-5.6-luna` `max` | `composer-2.5` `high` |
| `reasoning` | `medium` / `high` / `xhigh` / `max` | `gpt-5.6-sol` at that effort | `cursor-grok-4.6` at medium/high/xhigh |
| `primary-thread` | `inherited` | inherited | inherited |

The frozen baseline uses the Codex catalog. Cursor can dispatch those same Codex model IDs, so
Codex-config assertions are valid on both hosts. `--host cursor` is the cheaper runtime mapping.
The execution plan records `host`, `intelligence_class`, resolved `model`/`reasoning_effort`, and
`dispatch_model`. Human approval covers the mapped vendor IDs. Host detection does not use
environment variables or agent self-reports.

Omitting `--host` or passing `--host codex-astra` selects default catalog revision 2 for the Codex runtime. At every size it uses
Luna max for mapper/research, Astra low for Tech Lead/Senior Engineer/Test Engineer, and Astra medium
for Architect/Code Reviewer/Security Reviewer. Other advisory/specialist mappings remain unchanged.
Supervisor stays Astra xhigh, publication stays Luna max, and consolidation stays inherited.
It does not switch the primary model. Baseline catalogs stay unchanged; the seven reusable profiles
match the Astra default. Installed profiles require a separately authorized sync.
New Astra plans include `catalog_revision: 2` in the canonical digest. Reconstruction treats absent
markers as the frozen historical matrix and accepts only integer 2 on Astra when a marker is present.
Exact plan, canonical digest, row digest, and approval digest checks remain mandatory. Historical
plans keep their original bytes and approvals, including delegation-enabled plans. Older engines
cannot read new revision 2 Astra plans; rollback must not rewrite approvals.
The host must expose each exact approved assignment; see [model catalogs](../references/model-catalogs.md).
Reviewer delegation accepts Astra medium/high/xhigh/max with weights 3/3/4/5 in schema and runtime;
Astra low and Sol medium remain unsupported. Weights are not monetary prices. Sizing, topology,
and token accounting are unchanged; this candidate table makes no live benchmark claim.

### Pre-design research gate

Every initial `design_only` or `full_delivery` route, design revision, and delivery redesign inserts
the fixed `design_research_architecture` and `design_research_validation` nodes for the target
generation. Both nodes use the `impact_mapper` role with the approved host economy assignment and
are held in an assessed-pending `research` fan-out. Their envelopes carry deterministic focus and
split `inspection_budget` values whose combined totals never exceed the task budget. Research
capabilities are projected to `filesystem_read` and `external_read` effects only.

Research is an evidence gate, not a decision gate. Its exact output contract requires an
`evidence_manifest` artifact and verified evidence, while forbidding decisions and findings. The
Supervisor atomically verifies and persists the result, seals `research_collection`, and includes
the canonical collection and evidence inputs when creating the same-generation Tech Lead. No Tech
Lead exists before that collection is sealed. If a mandatory research branch exhausts its retry,
the collection advances to a durable blocked run rather than waiting indefinitely.

### Required instruction-level pull-request publication

`Pull Request Engineer` is an instruction-only role with no profile, engine node, schema, table,
provider, credentials, or specialist identifier. Every repository implementation intended for delivery
plans a fresh host-catalog publication dispatch with exact repository, remote, base, head,
and non-force actions. Implementation authorization plus initial plan approval is sufficient after all
gates; no later publication approval is needed. The Supervisor owns control and evidence but performs no
Git, GitHub, or worktree mutation during publication; its only mutation exception is initial setup
as described below. The Senior Engineer writes source and tests but never publishes.
Successful closure requires one review-ready PR, or the exact existing PR updated and verified; an
explicit draft request is the only exception.

Each phase selects and fully reads the smallest relevant exposed or repository-declared skill set,
without naming an optional skill or crawling other skill trees. Skills may change method, never approved
authority or effects. Controlling instructions win; conflicts and unavailable content are reported, and
the handoff records `Skill usage` with provenance, relevance, failures, or `None`.

Publication uses the dedicated implementation worktree and exact reviewed commit, or an exact complete
staged-plus-unstaged diff with no other tracked, untracked, unapproved ignored, conflicted, or Git-operation state.
Only that diff may be staged and committed without content changes. The role creates or reuses one
commit, pushes without force, and creates or updates the one PR. Identity mismatch, secrets, ambiguity,
duplicates, force, amend, history rewrite, and scope expansion fail closed.
The sole ignored-entry exception is for verified generated files inside exact plan-approved artifact
directories, produced by approved commands, with no user-maintained source, secrets, unrelated
content, escaping links, or index/diff entries. Verified compiler-generated source is permitted
under these same checks. Stage only reviewed paths and report retained generated paths; never
force-add or delete artifacts to bypass publication checks. This instruction-level rule is not an
engine-enforced filesystem check. Cleanup still rejects all ignored entries. See the complete
[publication contract](../references/publication.md). Passing local gates triggers publication;
successful repository implementation requires a verified PR URL. Publication blockers are reported
as incomplete delivery, not replaced with local completion.

After required PR approval and separate cleanup approval, a fresh host-catalog publication dispatch must use an existing
safe checkout or execution context outside the exact clean, registered target; it must not create a
separate, new, or dedicated cleanup worktree. It reverifies target, branch, HEAD, PR, and approval,
then uses only non-forced `git worktree remove`. Dirty, untracked, ignored, locked, or ambiguous state blocks removal;
the branch is preserved and recursive deletion, force, prune, and branch deletion are forbidden.

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
The default round ceiling is 1. Supported delegable weights are host-catalog economy 3; reasoning
high 3, xhigh 4, and max 5. Codex maps those to Luna max and Sol high/xhigh/max. Cursor maps them to
Composer high and Grok high/xhigh. Economy assignments below the catalog's economy effort remain
unsupported. Primary-thread assignments are forbidden. Only `code_reviewer` and
`security_reviewer` are initially eligible, and derived capabilities contain filesystem/external
read effects only.

Execution-plan v2 freezes conditional assignments before human approval. Each assignment contains
an ID, role, model, effort, review lens and prompt template, reason/acceptance/evidence/scope ceilings,
derived read-only capabilities, maximum instances, and dispatch weight. Delegation-disabled runs
continue to emit execution-plan v1. Execution-plan schema remains controlled only by reviewer
delegation and is not reused to identify the task-brief or size-policy version.

## Route complexity and model-cost sizing

Task-brief schema v2 adds required structured `model_sizing.scope_extent` (`bounded`, `cross_file`, or
`broadly_cross_cutting`) and `model_sizing.uncertainty` (`low`, `medium`, or `high`). The canonical
size inputs contain risk, sorted mandatory impact tags, and those two sizing values. The task schema
version and minimum route remain separately persisted. Plan reconstruction and resume choose the classifier solely from the
persisted task-brief schema version, never execution-plan schema, route prose, or metadata presence.

The v2 classifier is safety-ordered. High or critical risk, `security_privacy`, high uncertainty, or
broadly cross-cutting scope selects `large`; the high-risk-to-large mapping is intentional. Medium risk,
cross-file scope, medium uncertainty, or a non-security mandatory tag selects `medium`. Only bounded,
low-risk, low-uncertainty, tag-free work selects `small`. Stable reason codes and canonical inputs are
included under `size_policy_version: 2`; an explicit override below the computed floor fails closed,
while a higher override remains allowed.

Route controls topology and gates; size controls model-cost assignments. Therefore a v2 small
`full_delivery` plan preserves the full research, design, implementation, independent review, test,
specialist, consolidation, and closure graph. Small, medium, and large plans differ only in the existing
host-resolved class assignment matrix. Task-brief v1 retains its exact legacy classifier, unrestricted
override behavior, execution-plan JSON shape, and digest for compatibility.

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
| Schema 6, delegation absent | Execution-plan schema 1; task-brief v1 retains legacy plan bytes |
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

All economy size assignments use the selected host catalog's economy effort. Tech Lead and Architect
use that catalog's reasoning model at every size. The centralized execution-plan invariant rejects an
invalid host, model, or effort before it can enter a persisted envelope.

The recommended Supervisor assignment comes from the host catalog. Codex defaults to `gpt-6-astra`
with `xhigh` reasoning. Cursor recommends `cursor-grok-4.6` with `high` reasoning rather than
ChatGPT Sol. Actual model and effort are considered verified only when supplied by a trusted host
runtime assertion. Missing, unverifiable, or mismatched values select advisory mode and require this
exact warning:

> Supervisor warning: This Supervisor is an advisory role and thought partner. Treat its plans, decisions, and synthesis as recommendations requiring your approval.

Task text, prompts, environment variables, and self-reports cannot establish that verification. The
current local mode is advisory when no trusted assertion is available.
Advisory mode does not introduce additional approval gates. Existing execution-plan approval covers
routine in-scope decisions and unchanged retries, replacements, and continuations within the existing
budgets. Material changes to scope, authority, route, roles, host, model, or effort require a new plan.

The Supervisor owns initial worktree and branch creation within existing implementation authority,
after bounded read-only inspection of instructions, status, registrations, and the intended base.
This setup exception never permits commits, publication, cleanup, force, or mutation of an existing
checkout. All non-trivial implementation uses `full_delivery`; a reduced focused-implementation
route is not implemented. The documentation fast path still requires independent review and testing.

## Contributor contract

The Senior Engineer role requires both `clean-code` and `clean-architecture-code` on every
implementation assignment and follow-up repair. Every dispatch and continuation names both skills;
the role reads them fully and applies both workflows within the approved design. `Skill usage`
reports concrete implementation actions and validation for each. Missing required content returns
DESIGN-BLOCKER; the Supervisor rejects READY_FOR_REVIEW without both reports. Architecture guidance
does not justify additional layers, abstractions, or scope. This is an instruction-level handoff
requirement, not a new engine decision or schema field.

The Code Reviewer role requires both `code-review` and `clean-architecture-review` on every
assignment, including delegated and follow-up reviews. Both workflows must be applied within the
assigned scope and documented in `Skill usage` with concrete checks and conclusions. A missing or
unreadable required skill makes review incomplete; the Supervisor rejects approval without both
reports. This is an instruction-level handoff requirement, not a new engine decision or schema field.
Optional skill discovery remains bounded, and no architecture scope expansion is authorized.

Changes must preserve unrelated work, remain within approved files and behavior, add no dependency
or packaging system, and avoid generated artifacts. Approved implementation publication follows the
contract above; profiles, other remote changes, deployment, and release require separate scope.

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
