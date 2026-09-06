---
name: sync-agent-skills
description: Audit, compare, and synchronize AI agent skills across installed profiles and local Git repositories/worktrees for Codex, Claude, Cursor, and VS Code. Use for skill sync, inventory, migration, backup, or consistency checks. An unqualified sync includes both profile and repository installations; honor explicit narrower targets.
---

# Sync Agent Skills

## Overview

Coordinate profile and repository skill installations across local assistants while preserving each tool's native format and avoiding destructive overwrites.

An unqualified request to sync skills includes installed profiles and local Git repositories/worktrees. Do not finish after profile sync alone. A request naming only one profile or repository stays limited to that target.

Use this skill for skill folders and their discovery settings. Use `sync-agents-md` for instruction-document synchronization. Restrict writes to the requested tools and roots; an inventory does not authorize synchronization.

Prefer an inventory-first workflow. Treat `.codex/skills`, `.claude`, `.cursor`, and VS Code user-profile files as user-owned configuration unless the user explicitly asks to replace or normalize them.

## Master Repository (`ai-skills`)

The master canonical copy for all skills is the `ai-skills` git repository:
- Git URL: `https://github.com/JeffreyFerreiras/ai-skills.git`
- Master skills folder: `skills/` within the repository root.

When updating installed skills in local project repositories (such as `.cursor/skills`, `.agents/skills`, `.codex/skills`, `.claude/skills`, or `.github/skills`) or personal assistant profile roots (`~/.codex/skills`, etc.), treat `ai-skills` as the authoritative master copy.

## Workflow

1. Locate the relevant roots before editing:
   - Master repository: discover or clone `https://github.com/JeffreyFerreiras/ai-skills.git` (or the local checkout of `ai-skills`).
   - Installed repository roots: for broad sync, discover repositories beneath the user's known checkout directories (infer from the current checkout or saved projects) and registered worktrees from `git worktree list --porcelain`. Search to a bounded depth, skip caches/build outputs, and report the searched roots and any limits rather than scanning the whole machine. Recognize both `.git` directories and worktree `.git` files.
   - Inspect each discovered repository for `.cursor/skills`, `.agents/skills`, `.codex/skills`, `.claude/skills`, `.github/skills`, or `skills/`. Deduplicate resolved roots and exclude the canonical source tree itself. Include worktrees with installed copies; do not create skill folders in repositories that have none.
   - Profile roots:
     - Codex: `$CODEX_HOME/skills` when set, otherwise `~/.codex/skills`.
     - Claude: `~/.claude` and skill/instruction subfolders.
     - Cursor: `~/.cursor` and Cursor user profile settings/rules folders.
     - VS Code: user profile folders such as `%APPDATA%\Code\User` on Windows.
2. Run an inventory and inspect existing formats, names, and duplicate concepts.
3. When VS Code should see Codex skills, run `doctor-vscode` before troubleshooting content. VS Code does not discover `~/.codex/skills` unless `chat.agentSkillsLocations` includes it.
4. Decide the direction of sync with the user request as the source of truth. When syncing to local repos or profiles, pull latest versions from the master `ai-skills` repository.
5. Transform content only when needed:
   - Codex skills require a folder with `SKILL.md` frontmatter.
   - Cursor commonly uses rule or instruction files.
   - VS Code/Copilot commonly uses prompt or instruction markdown files.
   - Claude commonly uses project/user instructions, commands, or skill-like markdown assets depending on the installed product surface.
6. Before writes, state the target paths and whether the operation will copy, transform, or replace files.
7. Preserve existing files with timestamped backups before replacement.
   - Read each target repository's applicable instructions and Git status. Preserve unrelated edits and repository-only skills. Show differing installed skill paths in the dry run; a broad sync authorizes updating those copies from the canonical source with recoverable backups.
   - Keep backups outside consumer repositories when their hygiene rules prohibit generated artifacts. Do not stage, commit, push, switch consumer branches, or update their application code as part of sync unless separately requested.
8. Validate by re-running inventory and, where applicable, checking that generated markdown/frontmatter is syntactically valid.
   - Verify both profile and repository copies against the source. Report counts for updated profiles, repositories/worktrees, skipped external skills, and any inaccessible or excluded roots. State explicitly if either profile or repository synchronization remains incomplete.
9. When the user asks to update installed skills in a local repository or profile from master:
   - Identify the local `ai-skills` checkout (`https://github.com/JeffreyFerreiras/ai-skills.git`).
   - Run `sync_agent_skills.py sync-from-master --master <ai-skills-path> --target-repo <target-repo-path>` or `--target-root <target-skills-path>`.
   - By default this updates existing installed skills to the latest master version. Use `--all` if newly added skills from master should also be installed.
10. When the user asks to publish profile changes back to master:
   - Use the repository specified by the user or discover the current `ai-skills` checkout (`https://github.com/JeffreyFerreiras/ai-skills.git`).
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

Target names must be single filenames. The helper rejects overlapping trees, linked source/target entries, and linked backup paths. Skills with `external-source.json` are reported and skipped even with `--force`; use their dependency resolver rather than replacing an installed engine with a stub.

## Repository and Profile Update from Master

To update installed skills in a project repository or profile from the master repository (`https://github.com/JeffreyFerreiras/ai-skills.git`):

```powershell
$masterRepo = (git rev-parse --show-toplevel).Trim() # or path to cloned ai-skills repo
$syncScript = Join-Path $masterRepo 'skills\sync-agent-skills\scripts\sync_agent_skills.py'

# Dry-run updating installed skills in a target project repo
python $syncScript sync-from-master --master $masterRepo --target-repo 'C:\path\to\my-project'

# Apply updates to all installed skills in target project repo
python $syncScript sync-from-master --master $masterRepo --target-repo 'C:\path\to\my-project' --apply --force

# Dry-run updating installed skills in a user profile root
python $syncScript sync-from-master --master $masterRepo --target-root "$HOME\.codex\skills"

# Apply updates to profile root
python $syncScript sync-from-master --master $masterRepo --target-root "$HOME\.codex\skills" --apply --force
```

## Publishing Profile Changes to Master Repository

When contributing profile changes back into the master repository (`https://github.com/JeffreyFerreiras/ai-skills.git`), keep the profile path and repository skill folder aligned:

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
