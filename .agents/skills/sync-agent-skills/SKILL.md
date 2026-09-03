---
name: sync-agent-skills
description: Audit, compare, and synchronize profile-level AI agent skills, instructions, prompts, and rules across Codex, Claude, Cursor, and VS Code. Use when the user asks to sync agent skills/configs between `.codex`, `.claude`, `.cursor`, VS Code/Copilot profile locations, or wants an inventory, migration, backup, or consistency check for personal agent capability files.
---

# Sync Agent Skills

## Overview

Coordinate profile-level agent capability files across local assistants while preserving each tool's native format and avoiding destructive overwrites.

Prefer an inventory-first workflow. Treat `.codex/skills`, `.claude`, `.cursor`, and VS Code user-profile files as user-owned configuration unless the user explicitly asks to replace or normalize them.

## Workflow

1. Locate the relevant profile roots before editing:
   - Codex: `$CODEX_HOME/skills` when set, otherwise `~/.codex/skills`.
   - Claude: `~/.claude` and likely skill/instruction subfolders.
   - Cursor: `~/.cursor` and Cursor user profile settings/rules folders.
   - VS Code: user profile folders such as `%APPDATA%\Code\User` on Windows.
2. Run an inventory and inspect existing formats, names, and duplicate concepts.
3. When VS Code should see Codex skills, run `doctor-vscode` before troubleshooting content. VS Code does not discover `~/.codex/skills` unless `chat.agentSkillsLocations` includes it.
4. Decide the direction of sync with the user request as the source of truth. Do not assume Codex's skill format can be copied directly into every target.
5. Transform content only when needed:
   - Codex skills require a folder with `SKILL.md` frontmatter.
   - Cursor commonly uses rule or instruction files.
   - VS Code/Copilot commonly uses prompt or instruction markdown files.
   - Claude commonly uses project/user instructions, commands, or skill-like markdown assets depending on the installed product surface.
6. Before writes, state the target paths and whether the operation will copy, transform, or replace files.
7. Preserve existing files with timestamped backups before replacement.
8. Validate by re-running inventory and, where applicable, checking that generated markdown/frontmatter is syntactically valid.
9. When the user asks to publish profile changes, also update the skills repository:
   - Use the repository specified by the user or discover the current `ai-skills` checkout.
   - Mirror each changed skill folder into `<repo>\skills\<skill-name>`.
   - Inspect `git status --short --branch` before staging so unrelated user changes are visible.
   - Commit only the mirrored skill changes with a focused message when the user requests a commit.
   - Push only when the user explicitly requests publication, using the repository's configured branch.
   - Never force-push, rewrite history, or include unrelated repo changes unless the user explicitly asks.

## Helper Script

Use `scripts/sync_agent_skills.py` for repeatable local filesystem operations:

```powershell
$syncScript = Join-Path $HOME '.codex\skills\sync-agent-skills\scripts\sync_agent_skills.py'
python $syncScript inventory
```

Common operations:

```powershell
# Inventory known profile roots as JSON.
python <skill-dir>\scripts\sync_agent_skills.py inventory --json

# Use broader or narrower bounded scans when profile folders are large.
python <skill-dir>\scripts\sync_agent_skills.py inventory --max-depth 3 --max-files 100

# Inventory explicit roots.
python <skill-dir>\scripts\sync_agent_skills.py inventory --root "codex=$HOME\.codex\skills" --root "vscode=$env:APPDATA\Code\User"

# Check whether VS Code will discover Codex skills.
python <skill-dir>\scripts\sync_agent_skills.py doctor-vscode

# Apply the VS Code discovery settings after backing up settings.json.
python <skill-dir>\scripts\sync_agent_skills.py doctor-vscode --apply

# Dry-run a copy from a source skill/file into a target root.
python <skill-dir>\scripts\sync_agent_skills.py sync --source "$HOME\.codex\skills\my-skill" --target-root "$HOME\.claude\skills"

# Apply the copy. Existing targets are backed up first.
python <skill-dir>\scripts\sync_agent_skills.py sync --source "$HOME\.codex\skills\my-skill" --target-root "$HOME\.claude\skills" --apply --force
```

The script does not convert formats. Use it to inventory, compare checksums, and copy a finalized artifact after deciding that a direct copy is appropriate.

## Repository Update

When updating the repository mirror, keep the profile path and repository skill folder aligned:

```powershell
$repo = (git rev-parse --show-toplevel).Trim()
$skillName = "sync-agent-skills"
$source = Join-Path $HOME ".codex\skills\$skillName"
$target = Join-Path $repo "skills\$skillName"

python (Join-Path $source "scripts\sync_agent_skills.py") sync --source $source --target-root (Join-Path $repo "skills") --apply --force
git -C $repo status --short --branch
```

Stage, commit, or push only when requested. Resolve the configured remote and target branch instead of assuming `master` or `main`.

## Format Guidance

Read `references/profile-locations.md` when choosing target paths or converting between tool-specific formats.

Keep synced content portable:

- Put long procedural knowledge in markdown.
- Avoid absolute paths unless they are intentionally machine-specific.
- Avoid secrets, tokens, private URLs, and local credentials.
- Keep tool-specific wrappers thin; duplicate the capability intent, not unnecessary metadata.

## Safety Rules

- Default to dry-runs for copy/sync operations.
- Never delete unrelated profile files.
- Never overwrite a target without a backup.
- Do not change global VS Code, Cursor, Claude, or Codex settings unless the request explicitly includes settings sync.
- If multiple files express the same concept, report the candidates and pick the newest or most complete only when the user's intent is clear.
