---
name: sync-agents-md
description: Audit, compare, create, and synchronize AGENTS.md-style instruction markdown across repositories and profile-level AI agent tools. Use when the user asks to sync AGENTS.md, agent instructions, Copilot/VS Code prompts, Cursor rules, Claude instructions, Codex instructions, or wants an inventory, migration, backup, or consistency check for agent-facing markdown guidance.
---

# Sync AGENTS.md

## Overview

Synchronize agent-facing markdown instructions while preserving each tool's native discovery rules, local repo context, and user-owned files.

Prefer inventory and comparison before editing. Use the most recently edited relevant instruction file as the default source when the user does not name one.

Ensure that updates are applied to all installed AI agent tools, including Claude, Cursor, Codex, and Copilot/VS Code prompts, while respecting each tool's discovery model and file format.

## Source Model

- The user's explicit source or target always wins.
- When the user does not name a source, inventory candidate `AGENTS.md` files and treat the last edited file as the priority source.
- Compare candidates by topic before writing. If the newest file is clearly partial, stale, generated, or tool-specific, report that risk before using another source.
- By default, synchronize the priority `AGENTS.md` to profile-level Claude, Cursor, and Codex instruction locations.
- Copy the canonical content directly when the target supports markdown instructions; transform only when a tool requires a different wrapper or filename.

## Profile Sync Targets

Use these as default profile-level targets after confirming what exists locally:

- Codex: `~/.codex/instructions.md`
- Claude: `~/.claude/CLAUDE.md`
- Cursor: `~/.cursor/AGENTS.md` or the existing profile rule/instruction file under `~/.cursor` or `%APPDATA%/Cursor/User`

Create missing parent directories when the target path is clear. Back up existing target files before overwriting them.

## Workflow

1. Locate candidate instruction files before editing, latest edited wins.
2. Inventory each file's path, size, modified time, and apparent purpose. Use `rg --files -g "AGENTS.md" -g "CLAUDE.md" -g "copilot-instructions.md"` for fast discovery — avoid `Get-ChildItem -Recurse` which is slow.
3. Identify the source from the user's request. If none is named, use the candidate `AGENTS.md` with the latest modified time as the priority source.
4. Identify profile-level targets for Claude, Cursor, and Codex. Prefer existing user profile instruction files; otherwise use the defaults above.
5. Compare overlapping guidance by topic, not only by filename.
6. Decide whether to copy verbatim, merge, or transform:
   - Copy when the target also supports `AGENTS.md` semantics.
   - Merge when the priority source and target both contain useful non-conflicting guidance.
   - Transform when the target uses another format such as Cursor rules, VS Code prompts, or Claude user instructions.
7. Before writes, state each target path and whether the operation will create, copy, merge, transform, or replace.
8. Back up existing targets with timestamped names before replacement or substantial rewrite.
9. Validate by rereading changed files and checking that markdown/frontmatter remains syntactically sane.

## File Discovery

Read `references/profile-files.md` when choosing target paths or when the user's request mentions VS Code, Cursor, Claude, Codex, Copilot, profile instructions, or cross-tool sync.

For repository-local work, check likely paths:

```text
AGENTS.md
.agents/AGENTS.md
.codex/instructions.md
.github/copilot-instructions.md
.github/prompts/*.prompt.md
.cursor/rules/*.mdc
.cursor/rules/*.md
CLAUDE.md
```

Use `rg --files -g "AGENTS.md" -g "CLAUDE.md" -g "copilot-instructions.md" -g "*.prompt.md" -g "*.mdc"` from the relevant root. This is significantly faster than `Get-ChildItem -Recurse` on Windows.

## Merge Rules

Keep shared guidance portable:

- Preserve concrete project facts, commands, conventions, and safety rules.
- Preserve the priority `AGENTS.md` as the canonical content when copying to profile-level tools.
- Remove chat-history details, stale task notes, and one-off implementation plans unless the user asks to keep them.
- Remove duplicated guidance unless it is needed by the target tool's discovery model.
- Avoid secrets, tokens, private URLs, and credentials.
- Avoid absolute machine paths unless the file is explicitly profile-local.
- Prefer concise imperative instructions.
- Keep tool-specific sections thin and clearly labeled.

When conflicts appear, report the conflict and use the more specific local instruction for that target unless the user names a different source of truth.

## Write Safety

Use dry-run style reporting before cross-profile writes. Do not delete unrelated profile files. Do not overwrite a target without a backup. Do not modify global editor settings unless the request explicitly includes discovery or settings sync.
