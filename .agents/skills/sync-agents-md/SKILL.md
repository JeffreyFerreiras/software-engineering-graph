---
name: sync-agents-md
description: Audit, compare, create, and synchronize AGENTS.md-style instruction markdown across repositories and profile-level AI agent tools. Use when the user asks to sync AGENTS.md, agent instructions, Copilot/VS Code prompts, Cursor rules, Claude instructions, Codex instructions, or wants an inventory, migration, backup, or consistency check for agent-facing markdown guidance.
---

# Sync AGENTS.md

## Overview

Synchronize agent-facing markdown instructions while preserving each tool's native discovery rules, local repo context, and user-owned files.

Prefer inventory and comparison before editing. Use the user's explicit source, otherwise the canonical `ai-skills/AGENTS.md`. Timestamps indicate drift, not authority.

Apply updates only to the requested tools and repositories. Inventory other installed tools without writing to them unless cross-tool sync was requested. For skill-folder synchronization, use `sync-agent-skills` instead.

## Master Repository (`ai-skills`)

The master canonical copy for portable agent instructions (`AGENTS.md`) is maintained in the `ai-skills` git repository:
- Git URL: `https://github.com/JeffreyFerreiras/ai-skills.git`
- Master instruction file: `AGENTS.md` in the repository root.

When updating agent instructions across local repositories or profile-level tools, treat `ai-skills/AGENTS.md` as the authoritative master copy unless the user specifies a different source.

## Source Model

- The user's explicit source or target always wins.
- By default, treat the `AGENTS.md` from the master repository (`https://github.com/JeffreyFerreiras/ai-skills.git`) as the canonical source.
- When syncing a local project repository or personal profiles, synchronize guidance from `ai-skills/AGENTS.md` while preserving project-specific instructions (such as build commands, test steps, or local architecture notes) in repository-level files.
- Compare candidate files before writing. If local files contain unique project facts, preserve or merge them rather than obliterating project-specific context.
- Copy the canonical content directly when the target supports markdown instructions; transform only when a tool requires a different wrapper or filename.

## Profile Sync Targets

Use these as default profile-level targets after confirming what exists locally:

- Codex: `$CODEX_HOME/AGENTS.md`, defaulting to `~/.codex/AGENTS.md`. Inspect `AGENTS.override.md` for precedence and preserve explicitly configured alternatives.
- Claude: `~/.claude/CLAUDE.md`
- Cursor: `~/.cursor/AGENTS.md` or the existing profile rule/instruction file under `~/.cursor` or `%APPDATA%/Cursor/User`

Create missing parent directories when the target path is clear. Back up existing target files before overwriting them.

## Workflow

1. Locate candidate instruction files before editing. Identify the master `ai-skills` repository (`https://github.com/JeffreyFerreiras/ai-skills.git`) or target repository files.
2. Inventory each file's path, size, modified time, and apparent purpose. Use `rg --files -g "AGENTS.md" -g "CLAUDE.md" -g "copilot-instructions.md"` for fast discovery — avoid `Get-ChildItem -Recurse` which is slow.
3. Identify the source from the user's request. If none is named, treat `ai-skills/AGENTS.md` as the authoritative master copy.
4. Identify targets:
   - Repository-local targets in target projects: `AGENTS.md`, `.cursor/rules/`, `.github/copilot-instructions.md`, `CLAUDE.md`.
   - Profile-level targets for requested tools: `$CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`), `~/.claude/CLAUDE.md`, and the verified Cursor instruction location. Prefer configured active files over assumed defaults.
5. Compare overlapping guidance by topic, not only by filename.
6. Decide whether to copy verbatim, merge, or transform:
   - Copy when the target also supports `AGENTS.md` semantics.
   - Merge when master `AGENTS.md` updates should be applied while preserving repo-specific build/test/run guidance.
   - Transform when the target uses another format such as Cursor rules, VS Code prompts, or Claude user instructions.
7. Before writes, state each target path and whether the operation will create, copy, merge, transform, or replace.
8. Back up existing targets with timestamped names before replacement or substantial rewrite.
9. Validate by rereading changed files and checking markdown/frontmatter. Verify the target tool loads the destination, including any override precedence; file existence alone is not discovery evidence.

## File Discovery

Read `references/profile-files.md` when choosing target paths or when the user's request mentions VS Code, Cursor, Claude, Codex, Copilot, profile instructions, or cross-tool sync.

For repository-local work, check likely paths:

```text
AGENTS.md
.agents/AGENTS.md
AGENTS.override.md
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
