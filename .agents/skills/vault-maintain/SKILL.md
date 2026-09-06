---
name: vault-maintain
description: Audit and safely maintain the local knowledge vault. Use when the user asks to clean up, validate, repair, deduplicate, reorganize, refresh maps or graph indexes, find broken links or orphaned notes, check unsupported claims, identify stale project notes, or perform general vault maintenance.
---

# Maintain the Knowledge Vault

Select audit or repair mode from the user's request. Audits, checks, and diagnosis are read-only: report evidence and proposed repairs without checkpoints, note edits, or index refreshes. Apply the write steps below only when repair or maintenance is authorized. Run read-only validation in audit mode, or report that the available validator requires writes.

Use the vault's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Unix for every vault command. If it is missing, report the setup requirement instead of silently using system Python. Create a checkpoint only when the vault's actual repository rules require one for the authorized writes.

1. Locate the repository root containing `AGENTS.md` and `vault.config.json`, then read
   `AGENTS.md` completely.
2. Inspect Git status and follow any applicable checkpoint rule before authorized broad edits.
3. Run vault validation and investigate duplicate stable IDs, near-duplicate titles or
   aliases, broken links, orphaned generated notes, missing source references, stale
   summaries, contradictions, and map or graph-index drift.
4. Check important claims against resolvable source notes. Mark or report unsupported
   claims instead of inventing support.
5. Apply only safe, evidence-backed repairs. Preserve content outside generated blocks.
6. Never silently merge, delete, or historically rewrite ambiguous notes. Propose those
   changes with supporting evidence.
7. After maintained links change, run `python -m vault_tools maintain` once at the
   write boundary to refresh generated maps, refresh the derived graph exactly once,
   and validate. Use database-only traversal for subsequent graph checks; do not
   repeatedly scan Markdown for each query.
8. Keep content local, run the narrowest relevant tests, run final vault validation,
   and report fixes, remaining issues, and evidence gaps.
9. Treat vault reset as a separate destructive-intent workflow. Never apply it unless
   the user explicitly asks; preview first, explain the timestamped local backup and
   Inbox-preservation default, and require the reset command's confirmation token.
