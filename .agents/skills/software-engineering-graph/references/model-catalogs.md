# Model catalogs

The CLI's existing `--host` field selects a catalog. `codex-astra` is the default;
`codex` is the explicit Luna/Sol fallback for the same Codex runtime. `cursor` retains its existing assignments.
Selecting a catalog does not switch the primary agent's actual model or install role profiles.

The default Astra catalog revision 2 applies this table at every size:

| Assignments | Model and effort |
| --- | --- |
| Impact Mapper and both design research nodes | Luna `max` |
| Tech Lead, Senior Engineer, Test Engineer | Astra `low` |
| Architect, Code Reviewer, Security Reviewer | Astra `medium` |

Unlisted advisory and specialist assignments retain the baseline size matrix, with reasoning
classes mapped to Astra. The Supervisor recommendation stays Astra `xhigh`, publication stays
Luna `max`, and Supervisor consolidation remains inherited. Sizing and graph topology are unchanged.
The seven reusable profiles match the default Astra assignments; installed profiles are not updated
by changing this repository. If a named profile pins
different values, use a host-supported bounded fresh agent with the approved role contract and
explicit assignment. If the host cannot honor that assignment, stop that dispatch and report the
specific mismatch; never silently fall back or claim the model was changed.

Before plan approval, verify each exact assignment against the current host's exposed capabilities.
An approved plan is not proof of model availability. Missing Supervisor model metadata selects
advisory mode but does not cancel existing approval or block unrelated authorized preparation.
Unknown branch assignments still block that dispatch. Do not request the same approval again.

Catalog selection is frozen in the plan digest. New Astra plans include `catalog_revision: 2`;
unversioned historical Astra plans reconstruct the original size matrix without changing bytes,
digests, or approvals. Resuming retains that catalog generation; changing it requires a new plan.
Existing `codex` and `cursor` plan shapes and digests remain unchanged. Older engines cannot read
revision 2 Astra plans. Do not rewrite approvals to make a rollback work.
Reviewer delegation can explicitly approve Astra `medium` or `high` at weight 3, `xhigh` at 4,
or `max` at 5. Astra `low` and Sol `medium` remain unsupported for delegation. These are
dispatch-budget weights, not price estimates; token accounting is unchanged.

Official guidance checked September 5, 2026:
[Astra model](https://developers.openai.com/api/docs/models/gpt-6-astra) and
[Astra prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra).
The published API efforts include `low`, `medium`, `high`, `xhigh`, and `max`. This graph uses
only its catalog's explicit assignments; host-specific additional efforts are not implied.
This engine coordinates agents and makes no API requests, so API transport or parameter migration
does not belong in the ledger.

Astra is the default at the user's explicit request after confirming account access.
This preference change does not establish comparative quality, latency, or cost benefits.
Use [behavioral-evaluations.md](behavioral-evaluations.md) with both catalogs under equivalent host
capabilities before making an evidence-based recommendation. Record task completion, unauthorized
effects, avoidable approval pauses, verification repeats, dispatch accuracy, elapsed time, and measured
usage. No live-model evaluation has been established by this default change.
