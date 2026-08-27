# Repository contributor constraints

- Preserve byte parity with the approved profile skill for runtime modules, scripts, schemas,
  copied tests, fixtures, and metadata. Only the `SKILL.md` human heading differs.
- Keep `profile-agents/` limited to the seven exact reusable role TOMLs already present.
- Retain optional specialist protocol identifiers and current executable behavior.
- Use Python 3.9 or newer and the standard library only. Add no dependency or packaging system.
- Do not add cache, bytecode, virtual environment, database, run-state, inbox, secret, environment,
  coverage, build, or temporary artifacts.
- Run only the explicitly enumerated standalone acceptance tests in `README.md`, with
  `PYTHONDONTWRITEBYTECODE=1`, then run hygiene last.
- Do not mutate a profile, consumer repository, or remote system without separately approved scope.
