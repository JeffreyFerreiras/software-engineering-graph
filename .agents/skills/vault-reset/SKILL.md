---
name: vault-reset
description: Safely preview and reset a local knowledge vault while retaining a recoverable backup. Use when the user explicitly asks to reset, wipe, clear, start over, or reinitialize the vault and its generated SQLite state.
---

# Vault Reset

Reset the vault only through the Python module interface and preserve a recoverable
history.

## Workflow

Use the vault's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Unix for every `python` command below. If it is missing, report the setup requirement instead of silently using system Python.

1. Locate the vault root containing `AGENTS.md` and `vault.config.json`.
2. Read `AGENTS.md` and follow its repository rules.
3. Inspect the working tree and explain the reset scope before applying it:
   - Vault content and SQLite state move into a timestamped `.vault/resets/<timestamp>/` backup.
   - `Inbox/`, including its hidden `.processed/` holding area, remains in place unless
     the user explicitly asks to include it.
   - Application code, configuration, templates, and skills remain unchanged.
4. Preview the operation from the vault root with `python -m vault_tools reset`.
5. Review the preview with the user. Require explicit intent to reset, wipe, clear, start over, or reinitialize before applying it. Never infer reset authorization from a maintenance, cleanup, validation, or repair request.
6. Apply the reset only after that explicit intent with
   `python -m vault_tools reset --confirm RESET`. Add `--include-inbox` only when the
   user explicitly requests Inbox archival.
7. Validate the recreated vault with `python -m vault_tools validate`. Confirm that
   the expected directories and fresh SQLite databases exist, and report the
   timestamped backup location.
8. If sources are reingested and the semantic layer should also be rebuilt, invoke
   `$vault-build-graph` after deterministic Inbox processing. A reset does not imply
   authorization to invent or restore relationships without reviewing their evidence.

Do not delete the backup or bypass the reset script.
