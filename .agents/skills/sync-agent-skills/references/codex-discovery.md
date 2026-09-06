# Verify Codex Skill Discovery

File synchronization and runtime enablement are separate checks. Identical repository and profile copies can both appear in the skill catalog. A successful copy, clean Git status, or existing chat's catalog does not prove that a new process will load the intended skills.

## Fresh-process check

1. Record `codex --version`. Start a new `codex app-server --stdio` process with the user's actual Codex home and configuration profile. Check the installed command's help if transport options differ. On Windows, use the installed native CLI executable when a shell wrapper prevents reliable stdio communication; do not hard-code another machine's executable path.
2. Complete the JSON-RPC initialization handshake, then call `skills/list` with the affected repository/worktree paths and `forceReload: true`. This reads discovery state without starting a model turn. For example, send these newline-delimited messages, waiting for each request's response before proceeding:

```json
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"skill-sync-check","version":"1.0"},"capabilities":{"experimentalApi":true}}}
{"method":"initialized"}
{"id":2,"method":"skills/list","params":{"cwds":["/absolute/path/to/repository"],"forceReload":true}}
```

3. Inspect each returned cwd separately. Record discovery errors and each skill's `name`, `path`, `scope`, and `enabled` state. Group enabled entries by name and report names with multiple distinct paths. Do not count disabled entries as active duplicates; they may still be listed. Do not silently choose a winner based on matching names or hashes.
4. Compare the result with the user's intended scope. If repository skills should be disabled, verify every discovered repository path in the requested roots is disabled and the intended profile replacements remain enabled. Treat an empty result, missing expected skill, discovery error, or missing cwd response as incomplete verification. Preserve existing enablement outside the requested roots.
5. Bound response waits (for example, 30 seconds per request), handle process exit and protocol errors, and close the process when finished. If the CLI is unavailable or verification fails, report the limitation; do not declare discovery fixed or recommend another restart as a verified solution.

## Apply an authorized exclusion

Change enablement only when the user requests it. An ordinary content sync does not authorize disabling repository or profile skills. Preserve any preference already authorized for the target roots, including when later syncs introduce new skills.

Back up the active user `config.toml` outside repositories before editing. Use the exact discovered skill paths in individual `[[skills.config]]` entries, or use `skills/config/write` with `path` and `enabled`. Preserve unrelated settings and existing skill overrides. Keep machine-specific absolute paths in local configuration, not in the portable repository skill.

```toml
[[skills.config]]
path = "/absolute/path/to/repository/skills/example/SKILL.md"
enabled = false
```

Codex CLI 0.145.0 was tested with a wildcard skill path: the setting was accepted but did not disable the matching skill. An exact discovered `SKILL.md` path worked. Do not assume glob or directory-wide exclusions work; enumerate paths unless the installed version's behavior is independently verified. Junctions and symlinks may resolve to canonical paths in discovery results.

After writing, stop the inspection process and repeat the check in a fresh process without temporary `-c` overrides. Confirm persisted exclusions, enabled replacements, and duplicate counts. Newly added skills and new worktree paths need fresh checks and, where already authorized, additional exact-path exclusions. Report the tested CLI version, affected cwd values, counts, remaining duplicates, and backup location. A successful CLI check establishes local CLI discovery; the desktop app may need a restart and can differ in version or extra discovery roots.

Official references: [skill enablement](https://developers.openai.com/codex/skills/#enable-or-disable-local-codex-skills) and [app-server skill discovery](https://developers.openai.com/codex/app-server/#skills). Recheck the documentation if the installed protocol changes.
