"""Host expansions for intelligence-class assignments.

The size matrix assigns each role an intelligence class and requested effort.
This table maps that pair onto a concrete vendor model for the selected host.

Tests and default runs use the Codex catalog (`gpt-5.6-luna` / `gpt-5.6-sol`).
Cursor can dispatch those same models, so Codex-config tests are valid on both
hosts. The Cursor catalog is the cheaper runtime mapping for `--host cursor`.
"""

from typing import Dict, Optional, Tuple


INTELLIGENCE_CLASSES = ("economy", "reasoning", "primary-thread")
DEFAULT_HOST = "codex"
REASONING_DISPATCH_WEIGHTS = {"high": 3, "xhigh": 4, "max": 5}

# (intelligence_class, requested_effort) -> (model, reasoning_effort, dispatch_model)
HOST_MATRIX: Dict[str, Dict[Tuple[str, str], Tuple[str, str, str]]] = {
    "codex": {
        ("economy", "max"): ("gpt-5.6-luna", "max", "gpt-5.6-luna"),
        ("reasoning", "medium"): ("gpt-5.6-sol", "medium", "gpt-5.6-sol"),
        ("reasoning", "high"): ("gpt-5.6-sol", "high", "gpt-5.6-sol"),
        ("reasoning", "xhigh"): ("gpt-5.6-sol", "xhigh", "gpt-5.6-sol"),
        ("reasoning", "max"): ("gpt-5.6-sol", "max", "gpt-5.6-sol"),
        ("primary-thread", "inherited"): ("primary-thread", "inherited", "primary-thread"),
    },
    "cursor": {
        ("economy", "max"): ("composer-2.5", "high", "composer-2.5"),
        ("reasoning", "medium"): ("cursor-grok-4.6", "medium", "cursor-grok-4.6-medium"),
        ("reasoning", "high"): ("cursor-grok-4.6", "high", "cursor-grok-4.6-high"),
        ("reasoning", "xhigh"): ("cursor-grok-4.6", "xhigh", "cursor-grok-4.6-xhigh"),
        ("reasoning", "max"): ("cursor-grok-4.6", "xhigh", "cursor-grok-4.6-xhigh"),
        ("primary-thread", "inherited"): ("primary-thread", "inherited", "primary-thread"),
    },
}

SUPERVISOR_CLASS = {
    "codex": ("reasoning", "xhigh"),
    "cursor": ("reasoning", "high"),
}
PUBLICATION_CLASS = {
    "codex": ("economy", "max"),
    "cursor": ("economy", "max"),
}


def known_hosts() -> Tuple[str, ...]:
    return tuple(sorted(HOST_MATRIX))


def catalog_for(host: str) -> Dict[Tuple[str, str], Tuple[str, str, str]]:
    catalog = HOST_MATRIX.get(host)
    if catalog is None:
        raise ValueError("HOST_UNSUPPORTED")
    return catalog


def resolve_row(host: str, intelligence_class: str, requested_effort: str) -> Tuple[str, str, str]:
    row = catalog_for(host).get((intelligence_class, requested_effort))
    if row is None:
        raise ValueError("MODEL_ASSIGNMENT_INVALID")
    return row


def resolve_assignment(host: str, intelligence_class: str, requested_effort: str) -> Tuple[str, str]:
    model, effort, _dispatch = resolve_row(host, intelligence_class, requested_effort)
    return model, effort


def dispatch_model(host: str, model: str, effort: str) -> str:
    for row in catalog_for(host).values():
        if row[0] == model and row[1] == effort:
            return row[2]
    raise ValueError("MODEL_ASSIGNMENT_INVALID")


def classify(host: str, model: str) -> Optional[str]:
    for (intelligence_class, _requested), row in catalog_for(host).items():
        if row[0] == model:
            return intelligence_class
    return None


def economy_effort(host: str) -> str:
    for (intelligence_class, _requested), row in catalog_for(host).items():
        if intelligence_class == "economy":
            return row[1]
    raise ValueError("MODEL_ASSIGNMENT_INVALID")


def supervisor_recommendation(host: str) -> Tuple[str, str, str]:
    catalog_for(host)
    return resolve_row(host, *SUPERVISOR_CLASS[host])


def publication_assignment(host: str) -> Tuple[str, str, str]:
    catalog_for(host)
    return resolve_row(host, *PUBLICATION_CLASS[host])


def dispatch_weight_for(model: str, effort: str) -> Optional[int]:
    """Return the engine delegation weight for a concrete host model pair."""
    if model == "primary-thread":
        return None
    for host in HOST_MATRIX:
        intelligence_class = classify(host, model)
        if intelligence_class is None:
            continue
        if intelligence_class == "economy":
            return 3 if effort == economy_effort(host) else None
        if intelligence_class == "reasoning":
            return REASONING_DISPATCH_WEIGHTS.get(effort)
    return None


def supported_dispatch_weights() -> Dict[Tuple[str, str], int]:
    weights: Dict[Tuple[str, str], int] = {}
    for catalog in HOST_MATRIX.values():
        for (intelligence_class, _requested), row in catalog.items():
            if intelligence_class == "economy":
                weights[(row[0], row[1])] = 3
            elif intelligence_class == "reasoning":
                weight = REASONING_DISPATCH_WEIGHTS.get(row[1])
                if weight is not None:
                    weights[(row[0], row[1])] = weight
    return weights
