# Ledger operations

Read this reference fully before operating the ledger. `<skill>` denotes the installed skill root;
schema paths in CLI instructions are relative to that root. The entry skill controls scope and authority.

## Start a run

1. Inspect the worktree and create a redacted, immutable task brief matching
   `references/task-brief.schema.json` under a repository-policy artifact root.
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
