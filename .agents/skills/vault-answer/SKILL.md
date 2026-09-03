---
name: vault-answer
description: Answer questions strictly from evidence in the local knowledge vault. Use when the user asks what their notes, sources, projects, decisions, opinions, or history say; requests a vault-grounded answer; or wants conclusions with source-note citations, dates, uncertainty, and direct-evidence-versus-inference separation.
---

# Answer from the Knowledge Vault

1. Locate the repository root containing `AGENTS.md` and `vault.config.json`. Use the
   repository instructions already present in the active context; read `AGENTS.md`
   from disk only when they are absent. If the user supplied no question, ask for one.
2. Use the repository virtual environment for every vault command: on Windows use
   `.\.venv\Scripts\python.exe`; on macOS or Linux use `./.venv/bin/python`. If that
   interpreter is missing, report that repository setup is required. Do not silently
   fall back to a system Python whose dependencies may be incomplete.
3. Translate the user's wording into two or three likely vault terms before searching;
   include common domain synonyms such as `method`/`function`. Probe likely titles or
   aliases first. Run `-m vault_tools search --title "specific phrase" --limit 10`
   once. Use a narrow multi-term content query only when the title probe does not
   produce an exact, high-confidence maintained note. When a source or author is
   known, add `--type source`. Do not force `--type concept`: the best maintained
   note may be a problem, pattern, practice, decision, or question. Avoid one-word
   and broad exploratory searches.
4. Select a result by the exact relative path printed by search, its displayed
   frontmatter title, alias, or stable ID. Never construct a path from the displayed
   title: generated filenames can be shortened while titles remain complete.
5. Use the fast path for a narrow question when the exact high-confidence maintained
   note appears to answer it: read that note, choose its most directly relevant cited
   source, and run `-m vault_tools passages "<source reference>" "specific terms"
   --limit 5` once. If the passage directly supports the answer and the command emits
   no processing or semantic-review warning, answer immediately. Do not traverse the
   graph, read related notes, or query additional sources on the fast path.
6. Escalate only when the title match is absent or ambiguous, the note or passage is
   insufficient, the source emits a warning, evidence conflicts, or the question asks
   for comparison, history, causes, relationships, or multi-note synthesis. Choose the
   smallest useful next action: one narrow content search, one precise passage-query
   variant, or one graph traversal. Do not perform all escalation actions by default.
7. When graph discovery is necessary, traverse one hop with a narrow node limit.
   Treat maps and source notes as leaves when starting from a maintained note because
   they are high-degree hubs. If another hop is necessary, start a new one-hop
   traversal from the selected non-hub neighbor. A source may be the start node for a
   source-specific question.
8. On the escalated path, inspect source `processing_status`, semantic-review scope,
   and extraction warnings before relying on passages. Try at most two precise query
   variants against the resolved source. If extraction is malformed, incomplete, or
   truncated, inspect the preserved local original with the appropriate document or
   PDF workflow. If primary text remains unavailable, rely only on explicitly reviewed
   atomic-note evidence, disclose the unavailable passage, and lower the conclusion.
   Mechanical summaries, topics, and entities are navigation aids, not evidence. Do
   not substitute broad repository search or a generic repository-search subagent.
9. Separate direct evidence from inference and include relevant dates. When editing
   vault files, keep portable Obsidian `[[wiki links]]`. In chat responses, cite notes
   and sources with standard Markdown links to their absolute local file paths so the
   rendered citations are clickable; use the vault note title as the link label. Do
   not use a bare `[[wiki link]]` as the only citation in chat. Surface contradictions
   with their temporal order.
10. Say plainly when evidence is missing, ambiguous, stale, or insufficient. Do not
   supplement the answer with general model knowledge unless the user requests it.
11. Keep content local and end with relevant unresolved questions when they affect the
   answer.
