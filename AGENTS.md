# Repository contributor constraints

- This repository is authoritative. The installed profile remains untouched unless separately
  approved work explicitly changes it.
- Keep `profile-agents/` limited to the seven exact reusable role TOMLs already present.
- Retain optional specialist protocol identifiers and current executable behavior.
- Use Python 3.9 or newer and the standard library only. Add no dependency or packaging system.
- Do not add cache, bytecode, virtual environment, database, run-state, inbox, secret, environment,
  coverage, build, or temporary artifacts.
- Run only the focused test suite explicitly enumerated in `README.md`, with
  `PYTHONDONTWRITEBYTECODE=1`. Run hygiene separately and last after final review.
- Do not mutate a profile, consumer repository, or remote system without separately approved scope.
