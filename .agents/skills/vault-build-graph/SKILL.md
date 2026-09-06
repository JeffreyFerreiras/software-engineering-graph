---
name: vault-build-graph
description: Semantically review ingested source notes and build an evidence-backed knowledge graph. Use when the user asks to connect sources, add relationships, build or rebuild the graph, review isolated source notes, create semantic notes from PDF, DOCX, or EPUB sources, or enrich the vault after ingestion or reset.
---

# Build the Knowledge Graph

Use this semantic stage after deterministic Inbox ingestion. Create or reuse meaningful
notes, connect them with source-supported relationships, and checkpoint long reviews so
the work can resume without rereading completed sections.

## Workflow

Use the vault's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Unix for every `python` command below. If it is missing, report the setup requirement instead of silently using system Python.

1. Locate the vault root containing `AGENTS.md` and `vault.config.json`, read
   `AGENTS.md` completely, and inspect Git status before making broad edits.
2. Refresh the derived graph index, then identify the requested sources or the most
   valuable isolated and under-connected source notes. Use
   `python -m vault_tools traverse` to inspect their existing database-backed
   neighborhoods.
3. Review one source at a time in bounded chapter or section chunks. Never load or
   summarize an entire long book in one context. Resume from the source note's
   `semantic_review_cursor` or `reviewed_sections` when present.
4. Before creating a node, search existing notes by stable ID, title, aliases, and
   meaning. Reuse and improve an existing note whenever it represents the same idea.
5. Create or update only significant concepts, people, projects, systems, decisions,
   questions, recurring problems, patterns, opinions, and lessons. Do not create a
   note for every noun or extracted entity.
6. Add every material relationship supported by the reviewed passage. Put the source
   citation on the same evidence or relationship bullet, and prefix interpretive
   edges with `inferred:`. Do not add speculative or merely conceivable links.
7. Maintain both discovery directions: each atomic note must cite the source note,
   and the source note's `links_to_generated_notes` must include every created or
   reused note materially discussed by that source. Preserve existing links and
   dated history.
8. Maintain `semantic_topics` as a short reviewed list of canonical `[[Concept]]`
   links or intentional topic labels. Do not promote mechanically extracted
   `key_topics` to reviewed relationships without evidence; those remain
   low-confidence discovery nodes in the derived database.
9. Update the source note's semantic-review metadata after each bounded chunk:
   - `semantic_review_status`: `in-progress` or `complete`;
   - `semantic_review_version`: the workflow or prompt version used;
   - `semantic_reviewed_at`: the current ISO timestamp;
   - `semantic_review_cursor` or `reviewed_sections`: the next resumable location.
10. Mark a source `complete` only after the full intended scope has been reviewed.
   Partial review is useful and must remain explicitly `in-progress`.
11. Run `python -m vault_tools refresh-graph` after all note and relationship writes.
    Then traverse each reviewed source one or two hops from SQLite, resolve broken
    links, and run `python -m vault_tools validate`. Traversal is
    database-only unless an explicit refresh flag is supplied.

## Report

Report the sources and sections reviewed, progress cursor, nodes created or reused,
relationships added, inferred links, unresolved uncertainty, remaining isolated
sources, and validation result. Keep all source content and derived knowledge local.
