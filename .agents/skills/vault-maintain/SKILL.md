---
name: vault-maintain
description: Audit and safely maintain the local knowledge vault. Use when the user asks to clean up, validate, repair, deduplicate, reorganize, refresh maps or graph indexes, find broken links or orphaned notes, check unsupported claims, identify stale project notes, or perform general vault maintenance.
---

# Maintain the Knowledge Vault

1. Locate the repository root containing `AGENTS.md` and `vault.config.json`, then read
   `AGENTS.md` completely.
2. Inspect Git status and create the required local checkpoint before broad work.
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
