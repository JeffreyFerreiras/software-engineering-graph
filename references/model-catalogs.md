# Model catalogs

The CLI's existing `--host` field selects a catalog. `codex` remains the default; `codex-astra`
is an explicit alternative for the same Codex runtime. `cursor` retains its existing assignments.
Selecting a catalog does not switch the primary agent's actual model or install role profiles.

The Astra catalog maps reasoning roles to `gpt-6-astra` at the same requested `medium`, `high`,
`xhigh`, or `max` effort. The Supervisor recommendation is Astra `xhigh`. Economy roles and the
publication role retain `gpt-5.6-luna` `max`; Supervisor consolidation remains inherited.
The seven reusable profiles retain the default medium Codex assignments. If a named profile pins
different values, use a host-supported bounded fresh agent with the approved role contract and
explicit assignment. If the host cannot honor that assignment, stop that dispatch and report the
specific mismatch; never silently fall back or claim the model was changed.

Before plan approval, verify each exact assignment against the current host's exposed capabilities.
An approved plan is not proof of model availability. Missing Supervisor model metadata selects
advisory mode but does not cancel existing approval or block unrelated authorized preparation.
Unknown branch assignments still block that dispatch. Do not request the same approval again.

Catalog selection is frozen in the plan digest. Resuming a run retains its original catalog;
changing catalog requires a new plan. Existing `codex` and `cursor` plan shapes and digests are
unchanged. Reviewer delegation can explicitly approve Astra `high`, `xhigh`, or `max` with the
existing engine weights 3, 4, or 5. These are dispatch-budget weights, not price estimates.

Official guidance checked September 5, 2026:
[Astra model](https://developers.openai.com/api/docs/models/gpt-6-astra) and
[Astra prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra).
The published API efforts include `low`, `medium`, `high`, `xhigh`, and `max`. This graph uses
only the efforts in its existing class matrix; host-specific additional efforts are not implied.
This engine coordinates agents and makes no API requests, so API transport or parameter migration
does not belong in the ledger.

Before promoting Astra to the default, run the behavioral evaluation protocol in
[behavioral-evaluations.md](behavioral-evaluations.md) with both catalogs under equivalent host
capabilities. Record task completion, unauthorized effects, avoidable approval pauses, verification
repeats, dispatch accuracy, elapsed time, and measured usage. Do not claim quality or cost benefits
from catalog/unit tests alone. No live-model evaluation has been established by this catalog change.
