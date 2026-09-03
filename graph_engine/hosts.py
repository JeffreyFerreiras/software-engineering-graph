"""Host model catalogs for environment-agnostic intelligence classes.

The graph assigns roles an intelligence class and a requested effort. A host
catalog maps that class onto a concrete vendor model. Codex remains the default
host so existing plans, profiles, and envelopes stay unchanged unless a run
explicitly selects another catalog.
"""

from typing import Dict, Mapping, Optional, Sequence, Tuple


INTELLIGENCE_CLASSES = ("economy", "reasoning", "primary-thread")
DEFAULT_HOST = "codex"
REASONING_DISPATCH_WEIGHTS = {"high": 3, "xhigh": 4, "max": 5}


class HostCatalog:
    """Concrete vendor mapping for one agent runtime."""

    def __init__(
        self,
        host_id: str,
        economy_model: str,
        economy_effort: str,
        reasoning_model: str,
        reasoning_efforts: Sequence[str],
        supervisor_recommendation: Tuple[str, str],
        publication: Tuple[str, str],
        effort_aliases: Optional[Mapping[str, str]] = None,
        dispatch_glue: str = "",
    ) -> None:
        self.host_id = host_id
        self.economy_model = economy_model
        self.economy_effort = economy_effort
        self.reasoning_model = reasoning_model
        self.reasoning_efforts = tuple(reasoning_efforts)
        self.supervisor_recommendation = supervisor_recommendation
        self.publication = publication
        self.effort_aliases = dict(effort_aliases or {})
        self.dispatch_glue = dispatch_glue

    def resolve(self, intelligence_class: str, requested_effort: str) -> Tuple[str, str]:
        if intelligence_class == "primary-thread":
            if requested_effort != "inherited":
                raise ValueError("SUPERVISOR_EFFORT_INVALID")
            return "primary-thread", "inherited"
        if intelligence_class == "economy":
            return self.economy_model, self.economy_effort
        if intelligence_class == "reasoning":
            effort = self.effort_aliases.get(requested_effort, requested_effort)
            if effort not in self.reasoning_efforts:
                raise ValueError("MODEL_ASSIGNMENT_INVALID")
            return self.reasoning_model, effort
        raise ValueError("MODEL_ASSIGNMENT_INVALID")

    def classify(self, model: str) -> Optional[str]:
        if model == "primary-thread":
            return "primary-thread"
        if model == self.economy_model:
            return "economy"
        if model == self.reasoning_model:
            return "reasoning"
        return None

    def dispatch_model(self, model: str, effort: str) -> str:
        if self.dispatch_glue and model == self.reasoning_model:
            return model + self.dispatch_glue + effort
        return model


HOST_CATALOGS: Dict[str, HostCatalog] = {
    "codex": HostCatalog(
        "codex",
        economy_model="gpt-5.6-luna",
        economy_effort="max",
        reasoning_model="gpt-5.6-sol",
        reasoning_efforts=("medium", "high", "xhigh", "max"),
        supervisor_recommendation=("gpt-5.6-sol", "xhigh"),
        publication=("gpt-5.6-luna", "max"),
    ),
    "cursor": HostCatalog(
        "cursor",
        economy_model="composer-2.5",
        economy_effort="high",
        reasoning_model="cursor-grok-4.6",
        reasoning_efforts=("medium", "high", "xhigh"),
        supervisor_recommendation=("cursor-grok-4.6", "high"),
        publication=("composer-2.5", "high"),
        effort_aliases={"max": "xhigh"},
        dispatch_glue="-",
    ),
}


def known_hosts() -> Tuple[str, ...]:
    return tuple(sorted(HOST_CATALOGS))


def catalog_for(host: str) -> HostCatalog:
    catalog = HOST_CATALOGS.get(host)
    if catalog is None:
        raise ValueError("HOST_UNSUPPORTED")
    return catalog


def resolve_assignment(host: str, intelligence_class: str, requested_effort: str) -> Tuple[str, str]:
    return catalog_for(host).resolve(intelligence_class, requested_effort)


def dispatch_model(host: str, model: str, effort: str) -> str:
    return catalog_for(host).dispatch_model(model, effort)


def dispatch_weight_for(model: str, effort: str) -> Optional[int]:
    """Return the engine delegation weight for a concrete host model pair."""
    if model == "primary-thread":
        return None
    for catalog in HOST_CATALOGS.values():
        intelligence_class = catalog.classify(model)
        if intelligence_class is None:
            continue
        if intelligence_class == "economy":
            return 3 if effort == catalog.economy_effort else None
        if intelligence_class == "reasoning":
            mapped = catalog.effort_aliases.get(effort, effort)
            return REASONING_DISPATCH_WEIGHTS.get(mapped)
    return None


def supported_dispatch_weights() -> Dict[Tuple[str, str], int]:
    weights: Dict[Tuple[str, str], int] = {}
    for catalog in HOST_CATALOGS.values():
        weights[(catalog.economy_model, catalog.economy_effort)] = 3
        for effort in catalog.reasoning_efforts:
            weight = REASONING_DISPATCH_WEIGHTS.get(effort)
            if weight is not None:
                weights[(catalog.reasoning_model, effort)] = weight
    return weights
