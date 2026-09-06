# Software Engineering Graph

Canonical source: [ai-skills/skills/software-engineering-graph](https://github.com/JeffreyFerreiras/ai-skills/tree/master/skills/software-engineering-graph).
Maintain the skill here. The former standalone repository provides a public redirect and preserved history.
Run the commands below from this skill directory, including when it is nested in the ai-skills repository.

Software Engineering Graph is an **AI-agent skill** for Codex, Cursor, and equivalent agent hosts. It organizes complex software work
across specialized AI agents and makes scope, human approval, design, implementation, independent
review, and testing explicit.

Use it for non-trivial features, fixes, refactors, migrations, integrations, and
production-sensitive work. Documentation and mechanical changes can use a smaller, faster route.

This repository is authoritative for the AI skill, its local workflow engine, and its seven reusable
agent-role definitions. It is not a general-purpose task scheduler, CI service, or security boundary.
The installed profile remains untouched unless separately approved work explicitly changes it.

## What the skill does

The skill keeps the primary host agent in charge as the **Supervisor**. The Supervisor scopes the
request, proposes an execution plan, asks the human to approve that plan, and then coordinates only
the roles the work needs:

- **Impact Mapper** classifies the change and selects the minimum safe route.
- **Architecture and Validation Researchers** perform a fixed, bounded two-member evidence
  fan-out before every Tech Lead design generation. They use the Impact Mapper role, return only
  verified evidence manifests, and have no write, test, decision, or findings authority.
- **Tech Lead** designs the change and plans its implementation.
- **Software Architect** independently reviews the design.
- **Senior Engineer** is the sole implementation writer.
  Every implementation and follow-up repair must apply both `clean-code` and
  `clean-architecture-code`, reporting concrete actions and validation for each. A missing required
  skill blocks READY_FOR_REVIEW; architecture guidance stays within the approved design.
- **Code Reviewer** independently reviews the completed change.
- Every Code Reviewer must apply both `code-review` and `clean-architecture-review`, including
  delegated and follow-up reviews, and report the checks and conclusions from each. Missing either
  skill makes the review incomplete; the Supervisor cannot accept approval without both reports.
- **Test Engineer** verifies the acceptance criteria and regression evidence.
- **Security Reviewer** joins when security, privacy, identity, secrets, or trust boundaries are
  affected.
- **Pull Request Engineer** is the required instruction-level publication role for every repository
  implementation intended for delivery. A fresh host-catalog publication dispatch publishes after the gates
  and may later perform separately approved cleanup. It adds no eighth profile or engine node.

The workflow is deliberately bounded. It limits design and repair loops, separates writing from
review, records evidence, and returns unresolved product or risk decisions to the human.

## How the AI agents work together

1. The Supervisor turns the request into a scoped task brief with acceptance criteria and non-goals.
2. The skill sizes model cost independently from route complexity and proposes exact AI model and
   reasoning-effort assignments.
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
It performs bounded read-only repository preflight and owns creation of the initial implementation
worktree and branch within existing implementation authority. This sole setup exception does not
authorize modifying existing worktrees. It validates publication evidence but never commits, pushes,
creates a pull request, or removes a worktree. The Senior Engineer remains the sole source and test
writer and never publishes.

The Supervisor preflight names a host catalog (`codex`, `codex-astra`, or `cursor`) and recommends that catalog's
Supervisor assignment. Codex defaults to `gpt-6-astra` with `xhigh` reasoning. Cursor defaults to
`cursor-grok-4.6` with `high` reasoning instead of ChatGPT Sol. Unless a trusted host runtime
assertion verifies that exact actual assignment, the Supervisor operates in advisory mode and displays:

> Supervisor warning: This Supervisor is an advisory role and thought partner. Treat its plans, decisions, and synthesis as recommendations requiring your approval.

This warning describes model verification; it does not add approval gates. The approved plan covers
routine in-scope decisions and unchanged retries, replacements, and continuations within existing
budgets. Material changes to scope, authority, route, roles, host, model, or effort need a new plan.

`init` defaults to `codex-astra` catalog revision 2 at every size: Luna `max` for mapper
and design research, Astra `low` for Tech Lead, Senior Engineer, and Test Engineer, and Astra
`medium` for Architect, Code Reviewer, and Security Reviewer. Supervisor stays Astra `xhigh` and
publication stays Luna `max`; other advisory/specialist assignments retain their existing mapping.
Historical unversioned Astra plans retain their original assignments and digests. Older engines
cannot read revision 2 Astra plans; rollback must preserve approvals without rewriting them.
The actual primary model is not switched by the CLI. Verify host availability and exact dispatch
assignments before approval. Use `--host codex` for the explicit Luna/Sol fallback; Cursor and
existing approved plans retain their assignments. The seven reusable role profiles match the Astra
default; installed profiles require a separately authorized sync.
See [model catalogs](references/model-catalogs.md) for compatibility and evaluation.

The four executable routes are `advisory` (read-only review), `design_only` (research and independent
design approval), `fast_path` (mechanical/documentation implementation plus independent review and
testing), and `full_delivery` (research, design, implementation, review, and testing). Every
non-trivial implementation uses `full_delivery`; no reduced focused-implementation route exists.

Task-brief schema v2 makes model sizing explicit with `scope_extent` and `uncertainty`. Bounded,
low-risk, low-uncertainty work with no mandatory impact tag selects `small`, even when the approved
route is `full_delivery`. Medium risk, cross-file scope, medium uncertainty, or a non-security
mandatory tag selects `medium`. High or critical risk, `security_privacy`, high uncertainty, or
broadly cross-cutting scope selects `large`; high risk mapping to large is intentional. Explicit v2
overrides may raise cost but cannot go below the computed safety floor.

The route still determines workflow gates. A v2 small `full_delivery` run keeps the same research,
design, implementation, independent review, testing, specialist, consolidation, and closure topology
as medium or large; only approved model assignments change. Existing task-brief v1 inputs retain the
legacy route-influenced classifier, unrestricted explicit override, execution-plan shape, and digest.

## Using the skill

In a Codex or Cursor environment where this skill is installed, ask the host agent to use
`software-engineering-graph` for the task. For example:

> Use the software-engineering-graph skill for this feature. Before any specialist agents start,
> show me the exact AI-agent roles, models, and reasoning-effort levels you propose, and ask me to
> approve the plan.

The consumer repository supplies its own `.codex/engineering-graph.json` policy, including the local
commands that count as required checks. This source repository does not install itself or modify a
consumer repository, an installed profile, or any remote system outside an approved repository
implementation scope and the publication contract below.

## Observed token usage

`status` includes optional `usage` accounting from explicitly associated Codex session JSONL files.
It reports **input + output tokens**, with cached input and reasoning output as subsets, and
cache writes as a separate metric. It never adds these subsets to the headline total, estimates
prices, substitutes planned assignments for observed models, or changes a delivery gate.

Before scoping starts, obtain a sanitized checkpoint for the primary session. This read-only
command requires neither `--repo`, repository policy, nor an initialized ledger:

```text
python scripts/graphctl.py usage checkpoint --session-log <explicit-session-file>
```

Keep the returned `source_id`, `offset`, and `prefix_sha256`. After initialization, bind that
checkpoint to the primary scoping interval:

```text
python scripts/graphctl.py --repo <repo> record usage --run-id <run> --action bind --session-log <file> --phase scoping --generation 0 --start-offset <offset> --source-id <digest> --prefix-sha256 <digest> --op-id <id>
```

The three historical checkpoint options are all-or-none. The engine verifies the exact source
identity, byte prefix, and a validated cumulative snapshot boundary (or offset zero). A mismatch
rejects the mutation without silently taking a new baseline. Omitting all three starts at the
latest validated snapshot and excludes earlier history; previously executed phases remain unavailable.
An offset-zero interval includes the first cumulative total only when validated last-usage counters
equal that total. Otherwise the first total becomes a baseline and coverage reports a prefix gap.

Associate a branch session with `--branch-id <id> --attempt-id <id>` instead of `--phase` and
`--generation`. Role, phase, and generation are derived from that executed attempt. Retries have
distinct attempt IDs; resumed sessions can bind to the same attempt. Delegated reviewers bind their
own session and attempt. Parent totals never include child rollups. Do not associate overlapping
work with multiple runs: the engine checks intervals within a run and does not inspect other runs.

```text
python scripts/graphctl.py --repo <repo> record usage --run-id <run> --action collect --binding-id <binding> --session-log <file> --op-id <id>
python scripts/graphctl.py --repo <repo> record usage --run-id <run> --action close --binding-id <binding> --session-log <file> --op-id <id>
python scripts/graphctl.py --repo <repo> status --run-id <run> --json
```

Close the current primary phase, then bind the next phase using the returned checkpoint. The five
phase names are `scoping`, `research_design`, `implementation`, `review_testing`, and `closure`.
Use fresh operation IDs for new samples; repeating the same normalized request and operation ID
replays its original result, even after an append. Changing explicit input under an existing ID
conflicts. Collections of already consumed snapshots never add tokens again.

Reports include cumulative totals, all five phases, roles, branch agents, attempts, generations,
models, efforts, and model/effort pairs. `observed_totals` retains known usage; `complete_totals`
is null when coverage is incomplete. `coverage` is `unavailable`, `partial`, or `complete`;
optional missing/discontinuous metrics remain null and appear in `metric_partial`. An unexecuted
phase or skipped role has no measured consumption. `missing_executed_attempts`,
`missing_primary_phases`, and `association_coverage` separately expose association gaps.
Role, agent, and generation summaries retain their relevant missing associations and cannot call
a measured first attempt complete while an executed retry remains unbound. Supervisor summaries
also retain missing primary phases by generation. Model, effort, and model/effort summaries state
`attribution_scope: observed_intervals_only` and expose run `association_coverage`; they do not
assign an unbound attempt to its planned model or effort.
Active runs remain provisional (`running: true`, incomplete aggregate coverage); open intervals,
late telemetry, resets, malformed records, and unknown contexts remain visible. Completion means
only the declared, closed, observed intervals are covered, not an attestation of all host usage.
The final response can itself consume tokens beyond the last checkpoint.

At phase boundaries, settled increments can be attributed even within a turn. A response that
spans a checkpoint, or multiple model/effort contexts between snapshots, can make attribution
ambiguous. The engine counts such in-run increments once as unattributed and marks coverage
partial. It excludes increments that could contain pre-run work, and never guesses by elapsed time.
Counter resets preserve prior observations and omit the uncertain bridge. Truncation, replacement,
identity change, or prefix rewriting cannot silently restart a binding; use an explicit new binding
for a replacement and retain the disclosed gap.
For a replacement retaining the same session ID, earlier overlapping offsets remain rejected.
Recovery requires a new source identity or a later nonoverlapping checkpoint; rebinding cannot
bypass the existing interval deduplication rule.

The versioned `codex_jsonl_v1` adapter recognizes `session_meta.payload.id`, observed
`turn_context.payload.model` and `effort` (or `reasoning_effort`), and
`event_msg` / `token_count` / `info.total_token_usage` cumulative counters. Required input, output,
and total counters are nonnegative signed 64-bit integers, with total equal to input plus output;
booleans are invalid. Optional fields are `cached_input_tokens`, `reasoning_output_tokens`, and
the observed `cache_write_input_tokens`, normalized in reports to `cache_write_tokens`.
The legacy source alias `cache_write_tokens` is accepted only when `cache_write_input_tokens`
is absent. The observed spelling wins even if its value is invalid, which yields a null metric
rather than falling back to the alias. Aggregates use exact arbitrary-precision integers so valid
intervals across resets or sessions can exceed the raw signed 64-bit counter limit without
overflow; consumers must preserve JSON integer precision. Raw source bounds remain unchanged.
Only the finite host model catalog and finite effort values survive parsing;
other observed names become `unknown`. Other formats or missing metadata report partial or
unavailable usage. This observed-log-format adapter is not a claim of a stable public Codex API.

Only an explicit regular file is read, with symlinks/reparse points and identity changes rejected.
Where supported, the file is opened nonblocking before verifying its regular-file type again,
so replacement by a FIFO between the initial check and open cannot block the reader.
Each invocation is bounded to 64 MiB, 1 MiB reads/records, 100,000 records, and JSON depth 24.
Incomplete trailing lines wait for a later collection. No session search, directory crawl, raw
conversation, session ID, source path, credentials, or arbitrary source strings enter usage events,
operation responses, or diagnostic output. The ledger stores hashed source identity, byte-prefix
checkpoints, normalized counters/context, and fixed diagnostics. These hashes prove continuity,
not authenticity; association remains the caller's responsibility. Existing schema-6 runs require
no migration and report unavailable usage until metadata is associated. Optional usage corruption
does not disable ordinary graph validation or delivery. Usage collection is allowed after complete
or aborted runs, solely to settle late accounting metadata.

## Repository map

- [`SKILL.md`](SKILL.md) defines the AI skill and its operating contract.
- [`profile-agents/`](profile-agents/) contains the seven reusable Codex role profiles. Cursor runs
  keep those files unchanged and resolve models through the host catalog instead.
- [`graph_engine/`](graph_engine/) implements deterministic planning, validation, and local state.
  Host catalogs in `graph_engine/hosts.py` map role intelligence classes onto Codex or Cursor models.
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
- Every economy (Codex Luna / Cursor Composer) size assignment uses that catalog's economy effort.
  Tech Lead and Architect assignments use the host reasoning model at every size. Research output
  contracts require an `evidence_manifest`, verified evidence, a null decision, and empty findings.

Implementation authorization and initial plan approval cover the plan's exact non-force commit, push,
and PR actions after all gates; no later publication approval is needed. The Supervisor and Senior
Engineer never publish. Successful delivery requires one review-ready PR, or the exact existing PR
updated and verified; draft only on explicit request.

Publication uses the dedicated implementation worktree, exact repository/remote/base/head, and reviewed
commit or exact staged-plus-unstaged diff. It rejects other tracked, untracked, unapproved ignored, conflicted, or
Git-operation state, identity mismatch, secrets, ambiguity, duplicates, force, amend, or history rewrite.
Only verified generated files within exact plan-approved artifact directories may remain ignored
during publication; they must be absent from the index and reviewed diff, contain no secrets or
unrelated content, and never be force-added or deleted to bypass checks. Cleanup still refuses all
ignored entries. Read the full [publication contract](references/publication.md) before planning or publishing.
Passing local gates triggers the Pull Request Engineer's commit, push, and PR handoff. Successful
repository implementation ends with a verified PR URL; a publication blocker means incomplete delivery.

Before publication or cleanup, the Pull Request Engineer selects and fully reads the smallest relevant
set from its exposed catalog and repository-declared local skills, without crawling other skill trees or
naming an optional skill. Skills cannot expand authority or effects; controlling instructions win, and
conflicts or unavailable content are reported. Each handoff reports `Skill usage`, including provenance,
relevance, failures, or `None`.

After required PR approval and separate cleanup approval, a fresh Luna-max dispatch may run from any
safe checkout or execution context outside the exact clean, registered target; no cleanup worktree is
created. It uses only non-forced `git worktree remove`, preserves the branch, and refuses dirty,
untracked, ignored, locked, or ambiguous state, recursive deletion, force, prune, or branch deletion.

On Windows, the ledger requires `--ack-degraded-permissions` because Python cannot prove exclusive
profile permissions. `--ack-degraded-durability` is only for environments where directory syncing is
unavailable and that limitation is acceptable. These flags acknowledge platform limitations; they
do not grant extra authority.

## Contributor validation

The [behavioral evaluation protocol](references/behavioral-evaluations.md) supplies reproducible
host scenarios for approval, routing, artifacts, steering, and model selection. These are live-agent
evaluations, separate from deterministic engine tests; no live Astra results are claimed here.

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
