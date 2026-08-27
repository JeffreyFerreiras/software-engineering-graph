# Software Engineering Graph

This repository is the canonical source checkout for the Software Engineering Graph workflow and
its seven reusable profile-agent definitions. The separate profile installation is not modified or
managed by this repository.

## Requirements

- Python 3.9 or newer
- Python standard library only

## Source-level validation

Supported use from this checkout is limited to imports, tests, and displaying CLI help. Operational
commands require a separate consumer repository with its own `.codex/engineering-graph.json` policy
and may discover profile-local state.

Run the standalone checks with bytecode disabled and explicit read-only source locations:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:SEG_SOURCE_SKILL = '<absolute-path-to-approved-skill-source>'
$env:SEG_SOURCE_AGENTS = '<absolute-path-to-approved-agent-source>'
python -m unittest -v `
  tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_source_parity `
  tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_imports_and_help_do_not_mutate_sources
python -m unittest -v `
  tests.test_standalone_acceptance.StandaloneAcceptanceTests.test_hygiene
```

The second command is intentionally last so the successful validation ends with a clean checkout.
