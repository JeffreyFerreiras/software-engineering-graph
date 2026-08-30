---
name: software-engineering-graph
description: Orchestrate rigorous software application work through a scope-selected supervisor, tech lead, architect, senior engineer, code reviewer, and test engineer with bounded design and delivery loops and human-approved model/effort plans. Use when a user requests graph engineering, a multi-agent software organization, technical-design approval, independent implementation review and testing, or when repository instructions require this workflow for non-trivial features, fixes, refactors, migrations, integrations, or production changes.
---

# Software Engineering Graph

Use the local control ledger for every new graph run. Treat it as a deterministic coordination and
recovery aid, not a security boundary or a model-agent executor. Keep the primary agent as Supervisor
and the sole CLI mutator and dispatcher. Never give branch agents database paths or operation IDs.
The first Supervisor step is an execution-plan preflight: T-shirt size the job as small, medium, or
large, select only pertinent roles, assign each possible role a model and reasoning effort, and explain
the size, route floor, assignments, and omitted roles to the human. No branch may execute until the
human explicitly approves that immutable execution plan.

## Start a run

1. Inspect the worktree and create a redacted, immutable task brief matching
   `references/task-brief.schema.json` under a repository-policy artifact root.
2. Hash the exact `.codex/engineering-graph.json` bytes and put that digest in the brief's
   `policy_approval`.
3. Initialize the ledger and generate the execution-plan summary. Pass `--size small|medium|large`
   when the Supervisor chooses an explicit size; otherwise the engine records its bounded recommendation:

   `python <skill>/scripts/graphctl.py --repo <repo> [degraded acknowledgments] init --run-id <id> --task-brief <path> --size <size> --op-id <id>`

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
6. Put each returned branch manifest in the derived run inbox shown by `init` or `status`, then use
   `record branch-result` with the claimed `attempt_id` and `claim_token`. Branch manifests never
   contain control mutations.

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
It also reports schema-5 attempt counts and deterministic UTC wall-clock timing. Retry waits count toward
branch lifecycle wall time but not active duration or critical-path weight.

## Operating model

Treat the primary agent as the Supervisor. Keep requirements, decisions, approvals, and user communication in the primary thread. Delegate bounded work to the smallest set of pertinent named role agents, then synthesize their results. The full engineering graph is an available route, not a default requirement.

Follow applicable repository instructions before this workflow. Let the repository define architecture, risk triggers, commands, specialists, and completion gates. Do not let this skill expand the user's requested scope or authority.

### Bounded role skill preflight

Before the Senior Engineer or Code Reviewer takes task actions, require that role to inspect only the
skill catalog exposed to its current session and local skills explicitly declared by applicable
repository instructions. Do not crawl arbitrary profile or global skill directories. Select the
smallest clearly relevant skill set for the assigned implementation or review task, then read every
selected `SKILL.md` fully before acting. Do not prescribe a specific optional skill by name.

Discovered skills may change the role's method only. They must not expand the user-approved scope,
role authority, model or reasoning effort, writable files, allowed tests or commands, delegation,
external effects, or permission to install, synchronize, remove, or mutate skills, profiles, or
consumer repositories. User instructions, repository instructions, approved task artifacts, and the
role profile control any conflict. Decline a conflicting skill instruction and report the conflict in
the role's risks or observations.

If the catalog is unavailable or a selected skill cannot be read, proceed only when the controlling
instructions remain sufficient and report the condition without inventing skill content. Senior
Engineer and Code Reviewer handoffs must each include a `Skill usage` section listing every selected
skill's name, safe source or provenance, and relevance reason, or `None` when no skill was selected.

Reviewers identify risk; they do not own scope. The Tech Lead must challenge a requested revision
that is not traceable to the immutable task brief. The Supervisor is the binding scope authority and
must resolve scope before a finding can consume a revision round.

Use these base roles when available:

- `tech_lead`: author the technical design and implementation plan.
- `software_architect`: independently approve or reject the design.
- `senior_engineer`: act as the sole implementation writer.
- `code_reviewer`: review the completed diff without editing it.
- `test_engineer`: independently verify behavior and acceptance criteria.
- `security_reviewer`: join only when security, privacy, identity, secrets, or trust boundaries are affected.

Use repository-defined specialists when its routing rules require them. If a named profile is unavailable, spawn a bounded agent with the same contract instead of weakening a required gate.

The Impact Mapper selects route, risk, and specialist tags only. The Supervisor owns fan-out
eligibility after checking branch dependencies and shared resources.

## Delegation transparency

Before dispatching any subagent, tell the user its role, exact model, reasoning effort, and bounded
task scope. When dispatching several agents together, use one compact announcement that lists each
agent and identifies which work will run in parallel.

Resolve model and effort from the approved execution plan. The plan uses the role profile defaults for
medium work and bounded size-specific overrides for small or large work. If either value is not exposed,
state that it is inherited or unavailable instead of guessing, and do not dispatch that role until the
human approves a plan that makes the assignment explicit. Tell the user before dispatch when a retry,
replacement, or follow-up changes the model or effort; that change requires a new plan and approval.

## Select the route

T-shirt size the job before assigning intelligence. Use small for bounded, low-risk work, medium for
cross-file or elevated-risk work, and large for critical, cross-cutting, or high-uncertainty work. The
size is a planning decision, not a proxy for route selection: a small task may still need a full route,
and a large task may use only the roles pertinent to its approved scope.

Scope the job before selecting roles. Choose the smallest route that preserves the required independence;
do not dispatch a role merely because it exists in the base graph. Each selected role must have a
necessary decision, artifact, review surface, or verification responsibility tied to the task brief.
The Supervisor and the Impact Mapper remain the control plane, while the execution subgraph may be
small and task-specific.

Examples of scope-selected routes include:

- A narrow answer, diagnosis, or review: only the relevant read-only role or roles.
- A documentation or clearly mechanical change: the fast path, with only the checks needed to show
  that behavior, dependencies, data, security, operations, and user experience are unaffected.
- A focused implementation: the roles needed for its design, implementation, affected review surface,
  and proportionate testing. Add the Architect, Code Reviewer, or Test Engineer when their independent
  gate protects a real risk or acceptance criterion.
- A high-risk change: the focused implementation route plus the required security, domain, platform,
  data, or release specialists.

Use the full graph when the task's complexity, risk, cross-cutting impact, or acceptance gates justify
all of its design and delivery roles. Record the route and the reason for each omitted base role in the
Supervisor's task brief or closure packet so a smaller graph is an explicit scope decision, not an
accidental missing gate.

The execution plan must list the exact model and reasoning effort for every role that may be dispatched,
including conditional specialists. Human approval covers that complete assignment matrix. The Impact
Mapper may narrow the approved role set through route and impact classification, but it may not introduce
an unapproved role, model, or effort. A retry, replacement, or material route change returns to preflight.

Then apply these route rules:

- For an answer, diagnosis, or review request, use only relevant read-only roles and do not implement.
- For a design-only request, complete the design loop and stop after presenting the approved plan.
- For a non-trivial implementation request, run the full graph.
- For a high-risk change, add the required security, domain, platform, data, or release specialists at the design and verification gates.
- Use a fast path only for documentation or clearly mechanical changes that cannot affect production behavior, dependencies, data, security, operations, or user experience.
- A fast-path delivery `REDESIGN` runs fresh design gates, then returns to a fresh Senior Engineer
  and delivery generation without changing the immutable fast-path route floor.

Treat repository routing as authoritative when it requires a stricter route.

Critical delivery tasks are engine-forced to `full_delivery` and must include the
`security_privacy` impact tag. The impact mapper cannot remove that floor.

## Manual fallback and graph roles

### 1. Create the task brief

Have the Supervisor define:

- objective and user-visible outcome;
- scope and explicit non-goals;
- constraints and preserved behavior;
- acceptance criteria;
- affected surfaces and initial risk level;
- an initial inspection budget and named evidence paths;
- authorized external or destructive actions;
- required tests, specialists, and human decisions.

Inspect the current worktree before delegating. Identify unrelated changes and protect them throughout the workflow.

### 2. Run the design loop

Ask the Tech Lead to inspect the repository and produce a technical-design packet covering current behavior, proposed components and interfaces, data and control flow, failure handling, compatibility, observability, rollout, rollback, alternatives, and test strategy.

The Tech Lead may return `SCOPE_OBJECTION` without editing the design when a requested finding lacks
an acceptance-criterion mapping, conflicts with an explicit non-goal, or requires a materially new
subsystem. The objection must identify the finding, controlling scope text, missing causal link, and
smallest in-scope alternative. The Supervisor must adjudicate it before requesting another revision.

Bound the initial design investigation to named architecture, interface, implementation, test, and operations paths. Unless the task brief authorizes more, allow at most 12 file reads and 8 focused discovery commands before requiring a first design packet. Return incomplete evidence as an explicit gap instead of roaming indefinitely. Expand the budget only through a Supervisor follow-up.

Allow the Tech Lead to write only the requested design artifact during this phase. Do not run another writer concurrently.

Send the same task brief and design to the Architect. Add required read-only specialists in parallel when their review surfaces are independent.

Require each reviewer to return `APPROVE`, `REVISE`, or `BLOCK`, with stable finding IDs and concrete evidence. Every blocking finding must name the acceptance criterion it protects, the in-scope surface that introduced or changed the risk, and the concrete impact. Concerns that cannot meet all three conditions are non-blocking separate-task observations, not findings.

Before recording a reviewer result, the Supervisor must verify that traceability against the exact
task brief. Return a nonconforming result to the same reviewer for correction under its existing
branch attempt instead of ingesting it or consuming a design revision. Before consolidation, reject
scope expansion, deduplicate valid findings, and return one bounded revision packet to the Tech
Lead. A material scope expansion requires user authorization and a new task brief/run.

Limit the design loop to three revision rounds. Escalate unresolved product choices, conflicting constraints, or material risk to the user. Do not begin implementation without approval.

### 3. Implement with one writer

Give the Senior Engineer the approved task brief, technical design, acceptance criteria, and assigned finding IDs.

Include the bounded role skill preflight without naming an optional skill. Require its `Skill usage`
report in the implementation handoff before accepting the result.

Keep the Senior Engineer as the only production-code and test-code writer. Do not run another worktree writer concurrently. Require the engineer to preserve unrelated changes, add proportionate tests, run focused checks, and report any design deviation before proceeding.

Return to the design loop when implementation reveals a material interface, dependency, persistence, security, deployment, or scope change. Do not silently redesign inside the implementation node.

### 4. Run independent delivery gates

After implementation reaches a stable checkpoint, run the Code Reviewer and Test Engineer in parallel. Add conditional read-only specialists where required.

Require the Code Reviewer to evaluate correctness, regressions, design fidelity, maintainability, security implications, and test adequacy against the approved artifacts.

Include the bounded role skill preflight without naming an optional skill. Keep the reviewer read-only,
limit discovery to the assigned review context, and require its `Skill usage` report in the review
handoff before accepting the result.

Require the Test Engineer to map acceptance criteria to evidence, run the narrowest reliable test set, expand to integration or full checks as risk requires, and distinguish regressions from unrelated pre-existing failures.

Do not let reviewers or testers repair their own findings.

### 5. Run the repair loop

Have the Supervisor deduplicate and prioritize findings. Use stable IDs such as `ARCH-001`, `REV-001`, `TEST-001`, and `SEC-001`. Route one coherent repair packet to the Senior Engineer.

After repair, return the affected findings to the independent gate that raised them. Re-run broader checks only after focused failures are resolved.

Limit the delivery loop to three repair rounds. Return to the design loop for material design changes. Escalate an unresolved blocker after the third round instead of cycling indefinitely.

### 6. Close the graph

Finish only when:

- every acceptance criterion has evidence;
- the Architect's approved design still matches the implementation;
- no blocking or major review finding remains;
- required focused, integration, build, and repository checks pass;
- unrelated failures are clearly separated and reported;
- rollout, rollback, and approval requirements are satisfied;
- the final diff is scoped and explainable.

Have the Supervisor deliver the result, validation evidence, remaining risks, and any required next action. Commit, publish, deploy, or contact external systems only when repository instructions and user authority permit it.

## Concurrency and evidence rules

- Before every Supervisor fan-out, deterministically check branch dependencies and shared resources.
  Parallelize branches only when neither consumes the other's result and they share no writable
  files, mutable state, exclusive devices, constrained or rate-limited external services, or other
  resource that imposes ordering. Otherwise serialize them or add an explicit dependency edge.
- Start every independent reviewer and read-only specialist in fresh context (`fork_turns: "none"`
  or an explicitly equivalent fresh-session mechanism). Reconstruct its prompt only from the
  verified immutable task brief, approved design when applicable, stable diff or reference,
  acceptance criteria, and required evidence. Do not pass worker chat history, prior reasoning, or
  Supervisor narration. A same-role repair or revision follow-up may retain that role agent's own
  context.
- Serialize all worktree writes. Never assign the same files or responsibility to concurrent writers.
- Give every node bounded inputs, permitted actions, expected output, and a stopping condition.
- Give exploratory nodes a file and command budget. Prefer a useful partial packet over an unbounded repository survey.
- Prefer repository evidence over assumptions. Cite files, lines, commands, logs, or test output in findings.
- Keep raw logs and noisy exploration in subagent threads. Return concise evidence packets to the Supervisor.
- Treat external, destructive, costly, production, and scope-expanding actions as explicit approval boundaries.

## Artifact contracts

Require these minimum handoffs:

- **Task brief:** objective, scope, non-goals, constraints, acceptance criteria, risk, authority, named evidence paths, inspection budget.
- **Technical design:** current state, proposal, interfaces, failure modes, rollout, rollback, observability, test strategy, alternatives.
- **Design review:** decision, finding IDs, evidence, required revisions, unresolved decisions.
- **Implementation handoff:** changed files, acceptance mapping, focused checks, deviations, risks, skill usage.
- **Code review:** decision, prioritized findings, evidence, missing tests, design conformance, skill usage.
- **Test report:** decision, environment, commands, acceptance matrix, failures, untested gaps.
- **Closure:** delivered outcome, validation, residual risks, approvals, next action.
