# Ledger operations

Read this reference fully before operating the ledger. `<skill>` denotes the installed skill root;
schema paths in CLI instructions are relative to that root. The entry skill controls scope and authority.

## Start a run

Before substantive scoping, capture the primary session's usage checkpoint when the host exposes
the metadata and the explicit file is authorized to read:

`python <skill>/scripts/graphctl.py usage checkpoint --session-log <explicit-file>`

This read-only preflight runs without `--repo`, policy, initialization, or any ledger write. Retain
only the returned `checkpoint_schema_version: 1`, hashed `source_id`, `offset`, and `prefix_sha256`.
If no metadata is available, say that token usage is unavailable and continue the approved workflow.

1. Inspect the worktree and create a redacted, immutable task brief matching
   [the task-brief schema](task-brief.schema.json) under a repository-policy artifact root.
2. Hash the exact `.codex/engineering-graph.json` bytes and put that digest in the brief's
   `policy_approval`.
3. Initialize the ledger and generate the execution-plan summary. Pass `--size small|medium|large`
   when the Supervisor chooses an explicit size; otherwise the engine records its bounded recommendation:

  `python <skill>/scripts/graphctl.py --repo <repo> [degraded acknowledgments] init --run-id <id> --task-brief <path> --size <size> [--host codex|codex-astra|cursor] --op-id <id>`

4. Present the returned `execution_plan` and its digest to the human. Record an explicit local approval
   or rejection before dispatching anything:

   `python <skill>/scripts/graphctl.py --repo <repo> record plan-approval --run-id <id> --plan-digest <digest> --decision APPROVE --authority-ref authority:<id> --op-id <id>`

   `next`, `ready`, and `next --claim` remain blocked while this approval is pending. A rejected plan
   blocks the run; start a new run for a materially different size, route, role set, model, or effort.
5. Dispatch only the envelope returned by `next --claim` after approval. The first branch is always
   `impact_mapper`.
   When `status` reports `record_fanout_assessment`, record one complete, evidence-backed Supervisor
   assessment before claiming any sibling:

   `python <skill>/scripts/graphctl.py --repo <repo> record fanout-assessment --run-id <id> --fanout-id <id> --assessment-manifest <path> --authority-ref authority:<id> --op-id <id>`

   Cover every listed member and all four resource categories. Order every exclusive conflict and any
   service usage needed to keep each unordered set within capacity. The assessment is immutable.
   For `design_only` and `full_delivery`, the Impact Mapper result creates the fixed assessed-pending
   `design_research_architecture` and `design_research_validation` fan-out before any Tech Lead is
   created. Both branches reuse the Impact Mapper role at the approved host economy assignment,
   receive deterministic architecture/validation focus and split inspection budgets, and may project
   only filesystem or external read capabilities. They must return a verified `evidence_manifest` with evidence, no
   decision, and no findings. Sealing `research_collection` materializes the canonical evidence and
   creates the same-generation Tech Lead. A failed exhausted mandatory research pair blocks the run.
6. Put each returned branch manifest in the derived run inbox shown by `init` or `status`, then use
   `record branch-result` with the claimed `attempt_id` and `claim_token`. Branch manifests never
   contain control mutations.

### Optional reviewer delegation

Delegation is disabled unless both the repository policy and task brief provide
`reviewer_delegation`. An enabled execution-plan v2 lists every conditional assignment and its exact
role, model, effort, lens, prompt template, reason/acceptance/evidence/scope ceilings, derived
read-only capabilities, instance limit, and dispatch weight. Human approval covers these values.

A primary Code Reviewer may return `review_preliminary` plus `review_fanout_request`; it never
dispatches children. The Supervisor records both with the live attempt fence:

`python <skill>/scripts/graphctl.py --repo <repo> record review-fanout --run-id <id> --branch-id <id> --attempt-id <id> --claim-token <token> --preliminary-manifest <path> --request-manifest <path> --authority-ref authority:<id> --op-id <id>`

When status requests it, the Supervisor records the read-only resource assessment:

`python <skill>/scripts/graphctl.py --repo <repo> record review-fanout-assessment --run-id <id> --request-slot-id <id> --assessment-manifest <path> --authority-ref authority:<id> --op-id <id>`

The engine permits depth 1, at most 3 children per request, 6 children and weighted cost 15 per run,
and at most 2 request rounds. The default round ceiling is 1. Effective values are the minimum of
engine, repository, task, and approved-plan ceilings. Child failures, timeouts, and skips stay in the
nested collection and never refund cost. Once every member settles, the parent becomes ready with a
fresh claim fence and a redacted continuation that cumulatively binds every slot/collection digest,
exact member tuple, terminal non-success, and finding source without ledger or operation metadata.

On Windows, pass `--ack-degraded-permissions` because Python cannot prove profile DACL exclusivity.
Pass `--ack-degraded-durability` only when directory sync is genuinely unavailable and the reported
degraded mode is acceptable. These flags acknowledge platform limitations; they grant no authority.

## Operate the ledger

- Use `ready` or `next --all` to inspect dispatchable branches. Use `next --claim --op-id <id>` to
  claim exactly one branch atomically.
- Multi-member fixed review fan-outs begin pending. After the Supervisor assessment, independent roots
  become ready together and ordered successors promote atomically only after predecessors settle.
  Retryable failure does not release a successor. Do not use this mechanism as an arbitrary DAG scheduler.
- Use `join validate` before `join advance`. Collection joins only freeze terminal branch results
  and activate a typed Supervisor consolidation branch. Consolidation joins alone apply precedence,
  consume loop budgets, block, or activate the next generation.
- Use the typed `record timeout`, `skip`, `retry`, `heartbeat`, `approval`, `budget-use`, and
  `acceptance-evidence` commands for Supervisor mutations. Timeout, result, and heartbeat mutations
  must present the current attempt fence. Use `check run` for a policy-configured local command;
  required checks are satisfied only by its ledger receipt, not by a user-authored PASS file.
- Read consolidation inputs only from the claimed envelope. Its canonical `collection` input embeds
  every frozen branch result and terminal status, so consolidation branches never need ledger or
  database access.
- Give every mutation a unique opaque operation ID. An identical replay is a no-op; changed input
  under the same ID is an operation conflict.
- Use `resume` after interruption. Resolve every running branch by ingesting its actual result or
  recording an explicit timeout with its current attempt fence. Expired leases appear as a timeout
  action; send `record heartbeat` before expiry when work is still active.
- Use `complete` only after the closure join, acceptance evidence, approvals, and required checks
  are satisfied. Use `abort` for rollback; retained databases are audit evidence and are not deleted.

`status --json` is the supported export. Treat it as sensitive operational metadata.
It also reports schema-6 attempt counts and deterministic UTC wall-clock timing. Retry waits count toward
branch lifecycle wall time but not active duration or critical-path weight.

## Token accounting at phase handoffs

After initialization, bind the preflight checkpoint to the primary scoping phase:

`python <skill>/scripts/graphctl.py --repo <repo> record usage --run-id <run> --action bind --session-log <file> --phase scoping --generation 0 --start-offset <offset> --source-id <digest> --prefix-sha256 <digest> --op-id <id>`

Supply all three historical fields together. Identity, byte-prefix digest, and snapshot boundary
must match exactly; a mismatch leaves the ledger unchanged. Omit all three only to begin a new
baseline at the latest validated cumulative snapshot. A late baseline does not recover earlier
phases. Offset zero counts the first total only when the validated last usage equals the cumulative
total; otherwise the unknown prefix stays excluded and coverage is partial.

For an executed branch, replace `--phase` and `--generation` with the exact `--branch-id` and
`--attempt-id`. The engine derives role, phase, and generation from the attempt. Bind resumed
sessions separately to that same attempt; retries use their distinct attempt IDs. Bind delegated
reviewers separately, never copy a child's usage into its parent. A single source cannot have
overlapping bound intervals within the run. Do not share counted source intervals across runs;
the engine never searches other runs or sessions to discover ownership.

Collect while work continues and close at a settled checkpoint:

`python <skill>/scripts/graphctl.py --repo <repo> record usage --run-id <run> --action collect --binding-id <binding> --session-log <file> --op-id <id>`

`python <skill>/scripts/graphctl.py --repo <repo> record usage --run-id <run> --action close --binding-id <binding> --session-log <file> --op-id <id>`

Close the current primary phase before binding the next using the returned checkpoint, even when
both phases share a turn. Use `scoping`, `research_design`, `implementation`, `review_testing`, and
`closure`, with the applicable generation. Repeated cumulative snapshots and repeated collections
do not add tokens. The same normalized request/op ID replays its original result; new samples need
new operation IDs. Accounting mutations remain available in initialized, active, blocked, complete,
and aborted runs, including late closure metadata, without changing those states or delivery gates.

At every major phase handoff, report `usage.observed_totals`, the current phase, cumulative run
usage, role/agent usage, and observed model/effort pairs from `status`. Missing telemetry must be
reported as unavailable. Do not infer actual models from execution-plan assignments. Cached input
and reasoning output are subsets, cache writes are separate, and the headline is input plus output.
Read `coverage`, null `complete_totals`, `metric_partial`, missing executed attempts/primary phases,
open bindings, and unattributed increments before presenting any total as complete. Unexecuted or
skipped work has no measured consumption; active runs and unfinished responses are provisional.

Ambiguous in-run increments are counted once without guessed phase/model/effort attribution.
Increments that may include pre-run history are excluded. Resets drop the uncertain bridge while
retaining earlier observations. Identity changes, rewrites, and truncation retain a disclosed gap
and require an explicit new binding to replace the source. The final report can itself add tokens
beyond its last checkpoint. `complete` describes only bounded closed intervals, not all host work.

Missing executed retries keep the relevant role, agent, and generation summaries partial, and
missing primary phases keep Supervisor summaries partial. Model/effort groups cover observed
intervals only and expose association coverage; never assign missing usage to a planned model.
The source's `cache_write_input_tokens` is normalized to `cache_write_tokens` in reports and takes
precedence over the legacy source alias, even when invalid. Source counters retain signed 64-bit
bounds; exact aggregate integers can exceed that bound and require integer-preserving consumers.
Rewritten files retaining the same session ID cannot bind earlier overlapping offsets. Recovery
requires a new source identity or a later nonoverlapping checkpoint.

Only explicit authorized regular files are read, with 64 MiB/file, 1 MiB/read or record,
100,000 records/invocation, and depth-24 JSON limits. Symlink/reparse components and changed opened
file identity are rejected. Opens also request nonblocking mode where supported to prevent a raced
FIFO replacement from hanging before the opened-file type check. Source IDs and consumed prefixes
are hashed; raw source paths, conversation content, credentials, and arbitrary source strings never enter usage events or
responses. Errors are fixed diagnostics. Provenance is a caller association, not host authenticity.
See [Observed token usage](../README.md#observed-token-usage) for the supported observed JSONL
shape and report fields. If the host format or metadata is unavailable, keep coverage honest and
continue the authorized graph workflow without adding an approval gate.
