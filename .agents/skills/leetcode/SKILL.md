---
name: leetcode
description: Solve, explain, optimize, debug, or review LeetCode-style coding interview problems and algorithm challenges. Use when the user asks for help with LeetCode, HackerRank, CodeSignal, coding interview prep, data structures and algorithms, complexity analysis, edge cases, proof of correctness, test cases, or translating an algorithm into code.
---

# LeetCode

## Workflow

1. Restate the problem constraints and required output before solving. If the prompt is incomplete, state the missing assumptions and proceed with the most common LeetCode interpretation.
2. Identify the core pattern, such as two pointers, sliding window, binary search, dynamic programming, graph traversal, heap, monotonic stack, union-find, backtracking, trie, prefix sums, or greedy.
3. Derive the approach in plain terms before writing code. Prefer the simplest accepted solution unless the user asks for the most optimal one.
4. Provide code in the user's requested language. If no language is specified, use Python for explanation-first answers and match the repository language when working in a codebase.
5. Include time and space complexity with the variables they depend on.
6. Call out edge cases that commonly fail submissions.

## Answer Style

- When the user asks to learn, explain the intuition and tradeoffs before the final code.
- When the user asks for just the answer, keep the explanation short and lead with the implementation.
- When debugging a wrong answer or TLE, inspect the user's code first, identify the smallest failing case, then patch the logic.
- When asked for interview prep, include how to narrate the solution and why alternatives are weaker.
- Avoid overengineering. Do not introduce classes, helpers, or abstractions unless the platform or language requires them.

## Verification

For implementation tasks, include representative tests or dry-run cases:

- Empty or minimum-size input when allowed.
- Duplicate values.
- Negative numbers when applicable.
- Boundary values near constraints.
- Cases that distinguish a naive solution from the intended optimized pattern.

For dynamic programming and graph problems, explicitly define the state or traversal invariant before code.
