# Profile Locations and Format Notes

Use this as a starting map, then verify paths on the local machine. Agent products change their profile layouts over time, and users may override defaults.

## Master Skills Repository

- Git URL: `https://github.com/JeffreyFerreiras/ai-skills.git`
- Canonical skills tree: `skills/` within the repository root.
- All skills in profile directories or repository-local folders should sync against this master repository.

## Repository-Local Skill Roots

When working in a project repository, installed skills commonly reside in:

- `.cursor/skills` (Cursor Desktop and Cursor Cloud project skills)
- `.agents/skills` (Cross-agent project skills)
- `.codex/skills` (Codex workspace skills)
- `.claude/skills` (Claude Code workspace skills)
- `.github/skills` (GitHub Copilot project skills)

`sync_agent_skills.py` scans these locations when using `--target-repo <path>`.

## Codex

- Primary skill root: `$CODEX_HOME/skills`.
- Fallback skill root: `~/.codex/skills`.
- Skill shape: one folder per skill with required `SKILL.md` frontmatter containing `name` and `description`.
- Optional resources: `scripts/`, `references/`, `assets/`, and `agents/openai.yaml`.

## Claude

- Start with `~/.claude`.
- Look for markdown instructions, command folders, or skill-like folders already present before creating new structure.
- Preserve Claude-specific file names and metadata instead of forcing Codex `SKILL.md` layout.

## Cursor

- Start with `~/.cursor`.
- If `~/.cursor/skills-cursor` exists, treat it as the active Cursor-managed global skills folder and prefer it over creating a new global folder.
- Project skills for Cursor Desktop and Cursor Cloud live under workspace `.cursor/skills` (also `.agents/skills`, `.claude/skills`, and `.codex/skills`). Cloud Agents do not receive local `~/.cursor/skills`.
- In this repository, `.cursor/skills` is a symlink to the canonical `skills/` tree so every mirrored skill is discoverable in Cursor Cloud without duplicating folders.
- Some Cursor setups also use `~/.cursor/skills`; verify what exists locally before copying.
- Also inspect Cursor application user data when relevant, especially on Windows under `%APPDATA%\Cursor\User`.
- Cursor rule files may use `.mdc` or markdown-like instruction formats. Preserve existing frontmatter conventions.

## VS Code and GitHub Copilot

- On Windows, start with `%APPDATA%\Code\User`.
- Also check profile-specific folders if the user uses VS Code profiles.
- Prompt and instruction files are commonly markdown-based. Preserve file suffixes already used in the profile, such as `.prompt.md` or `.instructions.md`.
- Agent skills are discovered from `chat.agentSkillsLocations`. The documented default locations include `.github/skills`, `.claude/skills`, `~/.copilot/skills`, and `~/.claude/skills`; add `~/.codex/skills` when the user wants VS Code to see Codex profile skills directly.
- Check `chat.useAgentSkills` is `true`. If using the dedicated skill tool, check `github.copilot.chat.skillTool.enabled` as well.
- If skills do not appear, first run `scripts/sync_agent_skills.py doctor-vscode`, then reload VS Code with `Developer: Reload Window`.

## Sync Strategy

Choose one of three strategies per target:

1. Direct copy: only when both tools can consume the same file or folder structure.
2. Thin wrapper: create a native target file that points to or summarizes the shared source.
3. Native conversion: rewrite the content into the target tool's expected markdown/frontmatter style.

Prefer thin wrappers or native conversion when syncing Codex skills into Cursor, Claude, or VS Code. Codex `SKILL.md` frontmatter is useful for Codex triggering but may be irrelevant elsewhere.
