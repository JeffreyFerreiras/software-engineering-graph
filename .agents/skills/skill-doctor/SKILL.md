---
name: skill-doctor
description: Validate and audit an AI-agent skills repository for malformed frontmatter, folder/name mismatches, missing or stale OpenAI UI metadata, broken resource references, Python syntax errors, placeholder content, overlapping trigger descriptions, and optional installed-profile drift. Use when creating, reviewing, troubleshooting, or preparing to publish or synchronize skills.
---

# Skill Doctor

## Workflow

1. Run the bundled validator from the repository root:

```powershell
python skills/skill-doctor/scripts/skill_doctor.py .
```

2. Add `--profile-root <path>` when repository-to-profile parity matters.
3. Fix errors before publishing or synchronizing. Review warnings for trigger overlap, portability concerns, and profile drift.
4. Re-run the validator after changes and report the final error and warning counts.

Use `--json` for automation and `--strict` when warnings must also fail the command.

## Validation Policy

- Require `SKILL.md` frontmatter with only `name` and `description`.
- Require the folder name and frontmatter name to match.
- Require `agents/openai.yaml` with matching UI metadata.
- Verify referenced `scripts/`, `references/`, and `assets/` files exist and the README catalog matches the skill folders.
- Compile Python sources without writing bytecode.
- Flag unresolved placeholders, machine-specific paths, and highly similar trigger descriptions.
- Compare complete skill-folder content when a profile root is supplied, excluding generated cache files.

The validator is read-only. Do not automatically rewrite skills or synchronize profiles as part of diagnosis.
