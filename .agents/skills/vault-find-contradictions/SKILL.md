---
name: vault-find-contradictions
description: Find and record dated contradictions, changed beliefs, preference shifts, repeated mistakes, unresolved disagreements, and decisions that conflict with later actions in the local knowledge vault. Use when the user asks what changed, what conflicts, what they believed before versus now, or whether later evidence contradicts earlier notes.
---

# Find Knowledge Vault Contradictions

Use the vault's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Unix for vault commands. If it is missing, report the setup requirement instead of silently using system Python.

1. Locate the repository root containing `AGENTS.md` and `vault.config.json`, then read
   `AGENTS.md` completely.
2. Apply any user-supplied topic or date range; otherwise examine the maintained vault.
3. Search dated source statements and knowledge-note evidence for direct
   contradictions, changed preferences, repeated mistakes, unresolved disagreements,
   and decisions that conflict with later actions.
4. Require dated source evidence for both sides. Include the topic, both positions or
   action and decision, exact dates, source-note links, whether the change appears
   intentional, and unresolved questions.
5. Distinguish direct contradictions from inferred tensions, changed context, and
   differently worded compatible statements.
6. Preserve both positions and create or update records under
   `Reviews/Contradictions/`. Report ambiguous candidates separately.
7. Keep content local and run vault validation before reporting results.
