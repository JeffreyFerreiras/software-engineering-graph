---
name: recommend-model-effort
description: Recommend the lowest sufficient Codex or model reasoning-effort level for a supplied task using the active model's supported options, task complexity, ambiguity, risk, verification burden, and latency or cost priorities. Use when the user asks which effort or reasoning level to choose, whether low, medium, high, xhigh, max, or ultra is appropriate, or wants task-to-effort triage before starting work.
---

# Recommend Model Effort

Assess the task without performing it unless the user also asks for execution. Recommend one exact effort level that the active or requested model supports.

## Workflow

1. Identify the active or requested model and its exposed effort options from available context. Never invent support. If exact availability is unknown, recommend a relative tier and state that uncertainty; consult current official model documentation only when exact mapping matters.
2. Infer the user's priority from the prompt: latency or cost, balanced, or quality first. Assume balanced when unstated.
3. Evaluate the work by its hardest reasoning demand, not by prompt length:
   - depth of dependent reasoning
   - ambiguity, novelty, or competing hypotheses
   - breadth of interacting components and constraints
   - difficulty of verifying the result
   - consequence of a plausible error
   - duration and autonomy required
4. Choose the lowest tier that reliably covers those demands using the ladder below.
5. Raise one tier when errors are costly, feedback is weak, constraints conflict, or adversarial edge cases matter. Lower one tier when the work is mechanical, tightly bounded, familiar, and cheaply verified. Do not count the same factor twice.
6. If the ideal tier is unavailable, use the nearest supported tier. Round up for quality-first or high-consequence work; round down for explicitly latency- or cost-sensitive work.

## Effort Ladder

- **None or minimal:** Use only when exposed, for direct extraction, formatting, classification, or deterministic transformations needing essentially no deliberation.
- **Low:** Use for simple, bounded, familiar tasks with obvious success criteria, little ambiguity, and fast verification. Examples include a small rename, a direct lookup, or a routine explanation.
- **Medium:** Use as the balanced default for ordinary non-trivial work with several steps or local tradeoffs. Examples include a conventional feature with tests, a focused code review, or analysis using well-understood methods.
- **High:** Use for complex debugging, design, refactoring, or analysis that requires reconciling several constraints, exploring plausible alternatives, or checking cross-component effects.
- **Xhigh:** Use for genuinely difficult, uncertain, long-horizon, or high-consequence work where deeper search and verification are likely to improve reliability materially.
- **Max:** Reserve for the hardest quality-first work where marginal reliability matters more than latency or token use and substantial exploration or verification can change the outcome. Do not choose it merely because a task is large.
- **Ultra:** Use only when the active host exposes it and current host-specific guidance establishes its meaning and appropriate use. Do not infer that it enables delegation or requires parallel work. If its semantics are unavailable, state the uncertainty and recommend another supported level from the task demands.

Task length, file count, or tool count alone never justifies high effort. Easy-to-test bulk work can remain low or medium. A short task can warrant xhigh or max when a subtle error would be costly and hard to detect.

Do not confuse reasoning effort with response length. Recommend verbosity separately only when asked.

## Response Format

Lead with one recommendation:

```text
Recommended effort: <supported level>
Why: <one sentence naming the decisive task signals>
```

Add at most one of these when material:

```text
Assumption: <missing constraint you inferred>
Use <adjacent level> instead if: <single boundary condition>
```

Ask one concise question only when a missing fact could shift the recommendation by two or more tiers. Otherwise, state the assumption and recommend directly.
