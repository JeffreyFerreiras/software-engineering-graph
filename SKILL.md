---
name: software-engineering-graph
description: Orchestrate rigorous software application work through a scope-selected supervisor, tech lead, architect, senior engineer, code reviewer, and test engineer with bounded design and delivery loops and human-approved model/effort plans. Use when a user requests graph engineering, a multi-agent software organization, technical-design approval, independent implementation review and testing, or when repository instructions require this workflow for non-trivial features, fixes, refactors, migrations, integrations, or production changes.
---

# Software Engineering Graph

Use the local control ledger for every new graph run. Treat it as a deterministic coordination and
recovery aid, not a security boundary or a model-agent executor. Keep the primary agent as Supervisor
and the sole `graphctl` and ledger CLI mutator and dispatcher. The execution-plan-authorized Pull Request
Engineer is the sole bounded Git, GitHub, and worktree mutator for publication and cleanup and never
operates the ledger. Never give branch agents database paths or operation IDs.
The first Supervisor step is an execution-plan preflight: T-shirt size the job as small, medium, or
large, select only pertinent roles, assign each possible role a model and reasoning effort, and explain
the size, route floor, assignments, and omitted roles to the human. No branch may execute until the
human explicitly approves that immutable execution plan.

At the start of that preflight, before substantive scoping work, take a read-only
`usage checkpoint --session-log <explicit primary session file>` when Codex token metadata is
available. It runs before repository policy or ledger initialization. Retain only its sanitized
checkpoint fields and bind them to `scoping` after initialization; never count unrelated primary
thread history. If metadata is unavailable, report token usage as unavailable rather than omitting
it or inferring consumption from the plan. Read the token-accounting procedure in
[Ledger operations](references/ledger-operations.md) before collecting metadata.

For new repository implementation work, the Supervisor first performs bounded read-only inspection
of repository instructions, status, worktree registrations, and the intended base. Within existing
implementation authority, the Supervisor owns setup: create one new isolated implementation worktree
and branch before editing project files. This is its sole Git/worktree mutation exception; it does
not authorize commits, publication, cleanup, force, or changes to an existing checkout. Resolve the
exact target path and base first, and preserve unrelated work. If repository policy forbids setup,
report that concrete constraint and continue authorized read-only preparation.
The task brief records the selected worktree and branch as scope context. Reuse an existing checkout
or worktree when the user explicitly directs it; still inspect its status before delegating.

Name the host catalog in the execution plan as `codex`, `codex-astra`, or `cursor`.
`codex-astra` is the default model catalog for the Codex runtime. Do not infer the host from a
task, prompt, environment variable, or agent self-report. Use a trusted host runtime assertion, or
ask the human. Pass `--host cursor` to `init` when running in Cursor; omit it or pass `--host codex-astra`
for the default Codex catalog. Use `--host codex` for the explicit Luna/Sol fallback.
Verify that the host supports every planned model and effort. Changing catalog is a new plan.
Before choosing or dispatching a catalog, read [Model catalogs](references/model-catalogs.md).

Recommend the host catalog's Supervisor assignment and dispatch that catalog's resolved models. Codex
defaults use `gpt-6-astra` with `xhigh` reasoning. Cursor defaults use `cursor-grok-4.6` with
`high` reasoning rather than ChatGPT Sol, and `composer-2.5` for economy work rather than Luna.
The default Astra catalog revision 2 uses Luna `max` for mapper and design research at all sizes;
Astra `low` for Tech Lead, Senior Engineer, and Test Engineer; and Astra `medium` for Architect,
Code Reviewer, and Security Reviewer. Supervisor stays Astra `xhigh`, publication stays Luna `max`,
and unlisted advisory/specialist assignments keep their existing mapping. Unversioned historical
plans retain their original assignments and digests. Older engines cannot read revision 2 Astra
plans; never rewrite existing approvals to roll back.
Report the actual Supervisor model and effort only when a trusted host runtime assertion makes both
values verifiable. If either value is missing, unverifiable, or different, operate in advisory mode
and display this exact warning once per run, repeating only if verification status changes:

> Supervisor warning: This Supervisor is an advisory role and thought partner. Treat its plans, decisions, and synthesis as recommendations requiring your approval.

Do not infer verification from a task, prompt, environment variable, or agent self-report. Current
local operation without a trusted host assertion is advisory.
Advisory mode describes model verification, not an additional approval gate. Once the execution
plan is approved, continue routine in-scope decisions, checks, and bounded retries under that approval.
Ask only for a required human decision or a material change to approved scope, authority, or assignments.
If a controlling instruction causes a pause, cite its exact file and instruction and explain the
concrete conflict. Do not infer new approval requirements from optional skill guidance.

## Ledger procedures

Before initializing, claiming, recording, joining, resuming, or completing a run, read
[Ledger operations](references/ledger-operations.md) fully. It defines the required approval,
attempt fences, research and review fan-outs, budgets, recovery, and platform acknowledgments.
Use only the claimed envelope for dispatch; the first branch is always the Impact Mapper.

## Operating model

Treat a new user message as steering the active task unless it clearly cancels or replaces it.
Answer status questions briefly, then continue. Incorporate routine clarifications without restarting
the run. If a change invalidates immutable scope or acceptance criteria, stop dependent dispatches,
settle running attempts through the ledger, and prepare a new brief and plan; retain valid evidence
and report what must be revalidated. Never silently edit approved artifacts or discard completed work.

Use concise user updates: outcome or current blocker first, then the next action. Keep detailed
protocol packets in artifacts. Before evaluating or changing prompting or catalog defaults, read
[Behavioral evaluations](references/behavioral-evaluations.md); engine tests alone do not establish
agent behavior.

At each major phase handoff and in the final response, report observed input/output/total tokens,
cumulative run usage, and coverage, with role/agent and observed model/effort comparisons when
available. Use the five accounting phases `scoping`, `research_design`, `implementation`,
`review_testing`, and `closure`. Close the primary interval and bind the next phase at the returned
checkpoint; associate each executed branch attempt and separately dispatched child session.
Report gaps, unavailable phases, and provisional running usage explicitly. Never present a skipped
role as measured consumption or a partial total as complete. The final response itself may add
tokens beyond its last checkpoint. Accounting is additive metadata and must not introduce a new
approval, topology, or delivery gate.

Treat the primary agent as the Supervisor. Keep requirements, decisions, approvals, and user communication in the primary thread. Dispatch the roles required by the selected executable route and synthesize their results. Use the route mapping below; do not remove a mandatory gate to reduce model cost.

Follow applicable repository instructions before this workflow. Let the repository define architecture, risk triggers, commands, specialists, and completion gates. Do not let this skill expand the user's requested scope or authority.

### Bounded role skill preflight

Before the Senior Engineer or Code Reviewer takes task actions, require that role to inspect only the
skill catalog exposed to its current session and local skills explicitly declared by applicable
repository instructions. Do not crawl arbitrary profile or global skill directories. Select the
smallest clearly relevant skill set for the assigned implementation or review task, then read every
selected `SKILL.md` fully before acting. Do not prescribe a specific optional skill by name.

Required implementation skills: `clean-code` and `clean-architecture-code`. Every Senior Engineer
must read both SKILL.md files fully before acting and apply both workflows, including delegated
implementation and follow-up repairs. Include this requirement in every Senior Engineer dispatch
and continuation. These skills are mandatory; optional skill selection is additional.

Required review skills: `code-review` and `clean-architecture-review`. Every Code Reviewer must
read both SKILL.md files fully before acting and apply both workflows, including delegated and
follow-up reviews. These two skills are mandatory, not optional selections based on apparent
architectural impact. Include this requirement in every Code Reviewer dispatch and continuation.

Discovered skills may change the role's method only. They must not expand the user-approved scope,
role authority, model or reasoning effort, writable files, allowed tests or commands, delegation,
external effects, or permission to install, synchronize, remove, or mutate skills, profiles, or
consumer repositories. User instructions, repository instructions, approved task artifacts, and the
role profile control any conflict. Decline a conflicting skill instruction and report the conflict in
the role's risks or observations.

If the catalog is unavailable or a selected skill cannot be read, report the condition without
inventing skill content. A Code Reviewer missing either required skill must report an incomplete
review; do not accept APPROVE or substitute a generic review. A Senior Engineer missing either
required implementation skill must return DESIGN-BLOCKER, not READY_FOR_REVIEW. Optional skill
failures may proceed only when controlling instructions remain sufficient and both required
workflows for the assigned role can still be completed.
Senior Engineer and Code Reviewer handoffs must each include a `Skill usage` section listing every
selected skill's name, safe source or provenance, and relevance reason. `None` is not permitted for
a successful implementation or review handoff. A completed Senior Engineer handoff must report
concrete implementation actions and validation for each required skill. The Supervisor must reject
a READY_FOR_REVIEW handoff missing either report. A completed Code Reviewer handoff must report
concrete checks performed and conclusions for each required skill. The Supervisor must reject a
successful review handoff missing either report. If no architecture change is present, report that
evidence-backed assessment without expanding scope; neither workflow may be silently skipped.

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

<!-- dispatch-transparency:start -->
Immediately before every dispatch, tell the user the concrete agent or task name, the bounded scope,
the exact approved model, and the exact approved reasoning effort. This applies to every initial dispatch,
fan-out member, retry, replacement, follow-up, and same-role continuation. Refuse the dispatch when
the concrete identity or any approved assignment value is unavailable, unverifiable, or mismatched;
do not infer, substitute, or silently inherit missing values. When dispatching several agents together,
use one compact announcement that lists every concrete name and identifies which work will run in parallel.
<!-- dispatch-transparency:end -->

Resolve model and effort from the approved execution plan. The plan names the host catalog, then uses
the role intelligence-class matrix with that catalog's vendor mapping and revision overrides.
Reusable Codex profiles match Astra revision 2. If a value is not exposed, state that it is inherited or unavailable instead
of guessing, and do not dispatch that role until the human approves a plan that makes the assignment
explicit. Dispatch Cursor reasoning roles with `dispatch_model` from the plan (`cursor-grok-4.6-high`,
not ChatGPT Sol). Any retry, replacement, or follow-up host, model, or effort change requires a new
plan and approval.

## Select the route

T-shirt size the job before assigning intelligence. Task-brief v2 uses its structured `model_sizing`
inputs: small requires bounded scope, low risk, low uncertainty, and no mandatory impact tag; medium
covers medium risk, cross-file scope, medium uncertainty, or a non-security mandatory tag; large is
required for high or critical risk, `security_privacy`, high uncertainty, or broadly cross-cutting
scope. High risk intentionally maps to large. A v2 explicit override below that safety floor is refused.
Task-brief v1 retains the legacy classifier and override behavior.

Size is a model-cost tier, not a proxy for route selection. In particular, v2 `full_delivery` preserves
every design, implementation, review, testing, and specialist gate while bounded low-risk work may use
small economy assignments. A large task may still use only the roles pertinent to its approved scope.

Select one of the four executable routes. Every route begins with the Impact Mapper and retains
its engine-defined joins and Supervisor consolidation. This mapping is authoritative:

- `advisory`: answer, diagnosis, or review only; a read-only advisory reviewer, then closure. No implementation.
- `design_only`: research pair, Tech Lead, Architect and required design specialists, then design closure.
- `fast_path`: documentation or clearly mechanical changes that cannot affect production behavior,
  dependencies, data, security, operations, or user experience; Senior Engineer, Code Reviewer,
  Test Engineer and required delivery specialists. Initial research and design gates are omitted.
- `full_delivery`: every non-trivial implementation, including a focused behavior change; research
  pair, Tech Lead, Architect and required design specialists, Senior Engineer, Code Reviewer,
  Test Engineer and required delivery specialists.

There is no reduced focused-implementation route. Record the selected route and why it applies;
omit roles only as specified by that route. Repository policy may require a stricter route.

The execution plan must list the host catalog and the exact model and reasoning effort for every role
that may be dispatched, including conditional specialists. Human approval covers that complete
assignment matrix. The Impact Mapper may narrow the approved role set through route and impact
classification, but it may not introduce an unapproved role, host, model, or effort. An unchanged
retry, replacement, or same-role continuation uses the existing approval, attempt fences, and remaining
budgets. Only a material change to scope, authority, route, role set, host, model, or effort returns
to preflight for a new plan and approval. Never reset a budget by relabeling a retry as a new task.
For every repository implementation intended for delivery, the human-facing plan must list the Pull
Request Engineer assignment, exact repository, remote, base, head, and allowed non-force publication
actions. Implementation authorization plus initial plan approval covers those actions after all gates;
do not seek another publication approval. Cleanup remains conditional on its separately approved
destructive authority. Neither instruction-level assignment changes engine topology or ledger state.

Then apply these route rules:

- Every initial design route, design `REVISE`, and delivery `REDESIGN` creates the same-generation
  research pair before its next Tech Lead. Advisory and initial fast-path routes remain direct.
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

Include the bounded role skill preflight and explicitly require `clean-code` and
`clean-architecture-code` in every implementation dispatch and repair continuation. Require its
`Skill usage` report with concrete actions and validation for both workflows before accepting
READY_FOR_REVIEW. Apply architecture guidance proportionately to the approved design; do not add
layers or abstractions merely to demonstrate skill use.

Keep the Senior Engineer as the only production-code and test-code writer. Do not run another worktree writer concurrently. Require the engineer to preserve unrelated changes, add proportionate tests, run focused checks, and report any design deviation before proceeding.

The Senior Engineer does not create commits, push branches, create pull requests, or remove worktrees.

Return to the design loop when implementation reveals a material interface, dependency, persistence, security, deployment, or scope change. Do not silently redesign inside the implementation node.

### 4. Run independent delivery gates

After implementation reaches a stable checkpoint, run the Code Reviewer and Test Engineer in parallel. Add conditional read-only specialists where required.

Require the Code Reviewer to evaluate correctness, regressions, design fidelity, maintainability, security implications, and test adequacy against the approved artifacts.

An enabled primary Code Reviewer may request approved read-only review children, but may not choose
raw roles/models/efforts/capabilities, dispatch them, inspect control metadata, suppress their frozen
collection, or decide findings. The Supervisor validates and consolidates every child outcome.

Include the bounded role skill preflight and explicitly require `code-review` and
`clean-architecture-review`. Keep the reviewer read-only,
limit discovery to the assigned review context, and require its `Skill usage` report in the review
handoff before accepting the result.

Require the Test Engineer to map acceptance criteria to evidence, run the narrowest reliable test set, expand to integration or full checks as risk requires, and distinguish regressions from unrelated pre-existing failures.

Do not let reviewers or testers repair their own findings.

### 5. Run the repair loop

Have the Supervisor deduplicate and prioritize findings. Use stable IDs such as `ARCH-001`, `REV-001`, `TEST-001`, and `SEC-001`. Route one coherent repair packet to the Senior Engineer.

After repair, return the affected findings to the independent gate that raised them. Run required
checks and affected regression checks. Broaden or repeat verification only for new changes, failures,
or an identified unresolved risk; stop when those checks and acceptance criteria are satisfied.

Limit the delivery loop to three repair rounds. Return to the design loop for material design changes. Escalate an unresolved blocker after the third round instead of cycling indefinitely.

### 6. Close the graph

Finish only when:

- every acceptance criterion has evidence;
- when the route includes design gates, the Architect's approved design still matches the implementation;
- no blocking or major review finding remains;
- required focused, integration, build, and repository checks pass;
- unrelated failures are clearly separated and reported;
- rollout, rollback, and approval requirements are satisfied;
- the final diff is scoped and explainable;
- for a repository implementation intended for delivery, exactly one pull request has been created or
  the exact existing pull request has been updated and verified under the publication contract below.

Validate the required publication evidence before reporting success. The Supervisor retains plan,
ledger, validation, dispatch, and synthesis ownership. Apart from the bounded initial worktree setup
above, it performs no Git, GitHub, or worktree mutation.
Have it deliver the result, validation, risks, and next action.

## Publication and cleanup

For a repository implementation intended for delivery, read [Publication contract](references/publication.md)
fully before preparing the human-facing plan and again before publication or cleanup. Include exact
publication authority and generated-artifact locations in that plan. The fresh Pull Request Engineer
publishes after all gates; the Supervisor verifies its evidence before closure. Cleanup requires
separate authority and retains stricter worktree cleanliness requirements.

Repository implementation is complete only after the Pull Request Engineer commits the reviewed
change, pushes without force, and creates one review-ready PR or updates and verifies the exact
existing PR. Local checks passing is a publication handoff, not successful delivery. Return the
verified PR URL to the user. If publication is blocked, report incomplete delivery and the concrete
blocker; do not substitute local completion or ask again for already approved publication actions.

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
- Research nodes are deliberately evidence-only. The Supervisor owns artifact materialization and
  collection sealing; research branches never receive write, test, decision, or findings authority.
- Give exploratory nodes a file and command budget. Prefer a useful partial packet over an unbounded repository survey.
- Prefer repository evidence over assumptions. Cite files, lines, commands, logs, or test output in findings.
- Keep raw logs and noisy exploration in subagent threads. Return concise evidence packets to the Supervisor.
- Treat external, destructive, costly, production, and scope-expanding actions as explicit approval boundaries.

## Artifact contracts

Require these minimum handoffs:

- **Task brief:** objective, scope, non-goals, constraints, acceptance criteria, risk, authority, named evidence paths, inspection budget.
- **Research result:** a verified `evidence_manifest` artifact and evidence references, with
  `decision: null` and `findings: []`.
- **Technical design:** current state, proposal, interfaces, failure modes, rollout, rollback, observability, test strategy, alternatives.
- **Design review:** decision, finding IDs, evidence, required revisions, unresolved decisions.
- **Implementation handoff:** changed files, acceptance mapping, focused checks, deviations, risks, skill usage.
- **Code review:** decision, prioritized findings, evidence, missing tests, design conformance, skill usage.
- **Review preliminary/request:** frozen findings and evidence plus an exhaustive ID-only conditional
  fan-out request; never raw authority, paths, prompts, operation IDs, or dispatch data.
- **Test report:** decision, environment, commands, acceptance matrix, failures, untested gaps.
- **Closure:** delivered outcome, validation, residual risks, approvals, next action.
