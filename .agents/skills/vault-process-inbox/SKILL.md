---
name: vault-process-inbox
description: Deterministically process the local knowledge vault Inbox, then invoke the semantic graph-building workflow for newly ingested sources. Use when the user asks to ingest, import, extract, archive, deduplicate, organize, or fully process new Markdown, text, JSON, CSV, PDF, DOCX, EPUB, transcript, conversation, ebook, or project-document sources in this repository.
---

# Process the Knowledge Vault Inbox

## Establish scope

1. Locate the repository root containing `AGENTS.md` and `vault.config.json`.
2. Read `AGENTS.md` completely and work only inside that vault root.
3. Inspect Git status and create the required local checkpoint before broad edits.
4. Inspect every file under `Inbox/` and report unsupported or risky formats.

## Process and verify

1. Run `python -m vault_tools process-inbox` from the vault root. Do not force known
   content unless the user intentionally requested a rebuild.
2. Confirm successfully processed and duplicate inputs moved to
   `Inbox/.processed/<content-hash>/`. Leave unsupported or failed inputs visible in
   the active Inbox for correction.
3. Verify each new source note against its preserved original and surface extraction
   or OCR warnings.
4. Treat mechanical summaries, topics, entities, and explicit structured signals as
   navigation aids rather than a complete semantic review.
5. Always invoke `$vault-build-graph` in the same task for every newly processed
   source note. For a long source, complete one bounded semantic chunk and record its
   resume cursor; do not pretend the whole source was reviewed.
6. For a duplicate source, resume `$vault-build-graph` only when its semantic status
   is absent or `in-progress`. Do not re-review a source marked `complete` unless the
   user intentionally requests a rebuild.
7. Treat the Inbox task as complete only after graph building runs, or after reporting
   a concrete blocker such as missing readable local evidence. Unsupported and failed
   ingestion items do not proceed to graph building.

Keep all content local. Preserve stored originals under `Sources/*/_originals/`; treat
the hidden processed-Inbox copy as disposable convenience state. Run vault validation
and report processed, archived, skipped, unsupported, and uncertain items; extraction
warnings; graph nodes and relationships created or reused; semantic resume cursors;
and validation results.
