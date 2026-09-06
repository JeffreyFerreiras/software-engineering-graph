---
name: vault-daily-review
description: Create an evidence-backed daily review for the local knowledge vault. Use when the user asks for today's review, a review for a specified date, a summary of recent vault changes, new decisions, changed opinions, contradictions, or unresolved questions from a day of activity.
---

# Review the Knowledge Vault by Day

Use the vault's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Unix for vault commands. If it is missing, report the setup requirement instead of silently using system Python.

1. Locate the repository root containing `AGENTS.md` and `vault.config.json`, then read
   `AGENTS.md` completely.
2. Use the date or scope supplied by the user; otherwise use the vault's local date.
3. Review matching source notes, knowledge notes, contradiction records, and Git
   changes. Read every source needed to support important conclusions.
4. Summarize new knowledge, decisions and their status, changed opinions with older
   and newer dates, unresolved questions, and contradictions.
5. Separate direct evidence from interpretation. Cite source-note wiki links beside
   important conclusions and say when evidence is insufficient.
6. Create or update `Reviews/Daily/Daily Review - YYYY-MM-DD.md` using the daily-review
   template and a stable ID. Never rewrite historical evidence.
7. Keep content local, validate the vault, and report the review path and unresolved
   issues.
