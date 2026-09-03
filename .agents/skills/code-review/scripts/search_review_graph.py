#!/usr/bin/env python3
"""Search a bounded, manifest-backed graph for code-review design checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_MANIFEST = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "review-graph.manifest.json"
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "when",
        "where",
        "with",
    }
)
SEARCHABLE_LIST_FIELDS = ("aliases", "cues", "guardrails", "applicability")
RELATION_WEIGHTS = {
    "suggests": 12.0,
    "complements": 4.0,
    "alternative-to": 3.0,
}


class ManifestError(ValueError):
    """Raised when a review graph manifest violates its contract."""


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    rationale: str


@dataclass(frozen=True)
class Visit:
    node_id: str
    depth: int
    score: float
    parent_id: str | None = None
    relation: str | None = None
    direction: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class ReviewGraph:
    version: int
    nodes: dict[str, dict[str, Any]]
    edges: tuple[Edge, ...]


def _require_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{location} must be a non-empty string")
    return value.strip()


def _require_string_list(value: Any, location: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{location} must be a non-empty string array")
    return [_require_string(item, f"{location}[]") for item in value]


def load_manifest(path: Path) -> ReviewGraph:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"Unable to read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError("manifest root must be an object")
    version = raw.get("version")
    if type(version) is not int or version != 2:
        raise ManifestError("manifest version must be 2")

    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ManifestError("nodes must be a non-empty array")

    nodes: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(raw_nodes):
        location = f"nodes[{index}]"
        if not isinstance(node, dict):
            raise ManifestError(f"{location} must be an object")
        node_id = _require_string(node.get("id"), f"{location}.id")
        if node_id in nodes:
            raise ManifestError(f"duplicate node id: {node_id}")
        kind = _require_string(node.get("kind"), f"{location}.kind")
        supported_kinds = {"review-signal", "principle", "pattern"}
        if kind not in supported_kinds:
            raise ManifestError(
                f"{location}.kind is unsupported for manifest version {version}"
            )
        _require_string(node.get("name"), f"{location}.name")
        _require_string(node.get("summary"), f"{location}.summary")
        _require_string_list(node.get("aliases"), f"{location}.aliases")
        if kind == "review-signal":
            _require_string_list(node.get("cues"), f"{location}.cues")
        elif kind == "principle":
            for field in ("cues", "guardrails"):
                _require_string_list(node.get(field), f"{location}.{field}")
        else:
            for field in ("applicability", "tradeoffs", "avoid_when"):
                _require_string_list(node.get(field), f"{location}.{field}")
        nodes[node_id] = node

    raw_edges = raw.get("edges")
    if not isinstance(raw_edges, list) or not raw_edges:
        raise ManifestError("edges must be a non-empty array")

    edges: list[Edge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for index, edge in enumerate(raw_edges):
        location = f"edges[{index}]"
        if not isinstance(edge, dict):
            raise ManifestError(f"{location} must be an object")
        source = _require_string(edge.get("from"), f"{location}.from")
        target = _require_string(edge.get("to"), f"{location}.to")
        relation = _require_string(edge.get("relation"), f"{location}.relation")
        rationale = _require_string(edge.get("rationale"), f"{location}.rationale")
        if source not in nodes or target not in nodes:
            raise ManifestError(
                f"{location} references an unknown node: {source} -> {target}"
            )
        identity = (source, target, relation)
        if identity in seen_edges:
            raise ManifestError(f"duplicate edge: {source} -[{relation}]-> {target}")
        seen_edges.add(identity)
        edges.append(Edge(source, target, relation, rationale))

    return ReviewGraph(version=version, nodes=nodes, edges=tuple(edges))


def tokenize(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in TOKEN_PATTERN.findall(value.casefold())
        if token not in STOP_WORDS and len(token) > 1
    )


def _normalized(value: str) -> str:
    return " ".join(tokenize(value))


def _list_text(node: dict[str, Any], field: str) -> str:
    value = node.get(field, [])
    return " ".join(value) if isinstance(value, list) else ""


def score_node(node: dict[str, Any], query: str) -> float:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0

    normalized_query = _normalized(query)
    name = str(node["name"])
    aliases = _list_text(node, "aliases")
    identity_text = f"{node['id']} {name} {aliases}".casefold()
    summary_text = str(node["summary"]).casefold()
    detail_text = " ".join(
        _list_text(node, field) for field in SEARCHABLE_LIST_FIELDS
    ).casefold()

    score = 0.0
    if normalized_query and normalized_query == " ".join(tokenize(name)):
        score += 40.0
    elif normalized_query and normalized_query in " ".join(tokenize(identity_text)):
        score += 18.0

    identity_tokens = set(tokenize(identity_text))
    summary_tokens = set(tokenize(summary_text))
    detail_tokens = set(tokenize(detail_text))
    matched: set[str] = set()
    for token in query_tokens:
        if token in identity_tokens:
            score += 7.0
            matched.add(token)
        if token in summary_tokens:
            score += 3.0
            matched.add(token)
        if token in detail_tokens:
            score += 2.0
            matched.add(token)

    coverage = len(matched) / len(query_tokens)
    return round(score * (1.0 + coverage), 3)


def _is_exact_reference(node: dict[str, Any], query: str) -> bool:
    normalized_query = _normalized(query)
    references = [node["id"], node["name"], *node.get("aliases", [])]
    return bool(normalized_query) and any(
        normalized_query == _normalized(str(reference)) for reference in references
    )


def _adjacent(graph: ReviewGraph, node_id: str) -> Iterable[tuple[str, Edge, str]]:
    for edge in graph.edges:
        if edge.source == node_id:
            yield edge.target, edge, "outbound"
        elif edge.target == node_id:
            yield edge.source, edge, "inbound"


def traverse(
    graph: ReviewGraph,
    query: str,
    *,
    max_depth: int = 1,
    max_nodes: int = 8,
    max_seeds: int = 3,
) -> tuple[Visit, ...]:
    if not 0 <= max_depth <= 3:
        raise ValueError("max_depth must be between 0 and 3")
    if not 1 <= max_nodes <= 50:
        raise ValueError("max_nodes must be between 1 and 50")
    if not 1 <= max_seeds <= 5:
        raise ValueError("max_seeds must be between 1 and 5")

    exact_matches = sorted(
        node_id
        for node_id, node in graph.nodes.items()
        if _is_exact_reference(node, query)
    )
    if exact_matches:
        node_id = exact_matches[0]
        seeds = [(score_node(graph.nodes[node_id], query), node_id)]
    else:
        ranked = sorted(
            (
                (score_node(node, query), node_id)
                for node_id, node in graph.nodes.items()
                if node["kind"] in {"review-signal", "principle"}
            ),
            key=lambda item: (-item[0], item[1]),
        )
        top_score = ranked[0][0] if ranked else 0.0
        threshold = max(4.0, top_score * 0.6)
        seeds = [
            (score, node_id)
            for score, node_id in ranked
            if score >= threshold
        ][:max_seeds]
    if not seeds:
        return ()

    visits: list[Visit] = []
    visited: set[str] = set()
    queue: deque[Visit] = deque()
    for score, node_id in seeds:
        if len(visits) >= max_nodes:
            break
        visit = Visit(node_id=node_id, depth=0, score=score)
        visits.append(visit)
        visited.add(node_id)
        queue.append(visit)

    while queue and len(visits) < max_nodes:
        current = queue.popleft()
        if current.depth >= max_depth:
            continue
        candidates: list[tuple[float, str, Edge, str]] = []
        for neighbor_id, edge, direction in _adjacent(graph, current.node_id):
            if neighbor_id in visited:
                continue
            neighbor = graph.nodes[neighbor_id]
            score = score_node(neighbor, query) + RELATION_WEIGHTS.get(
                edge.relation, 1.0
            )
            if edge.relation == "suggests" and neighbor["kind"] == "pattern":
                score += 8.0
            candidates.append((score, neighbor_id, edge, direction))

        for score, neighbor_id, edge, direction in sorted(
            candidates, key=lambda item: (-item[0], item[1])
        ):
            if neighbor_id in visited or len(visits) >= max_nodes:
                continue
            visit = Visit(
                node_id=neighbor_id,
                depth=current.depth + 1,
                score=round(score, 3),
                parent_id=current.node_id,
                relation=edge.relation,
                direction=direction,
                rationale=edge.rationale,
            )
            visits.append(visit)
            visited.add(neighbor_id)
            queue.append(visit)

    return tuple(visits)


def result_payload(
    graph: ReviewGraph, query: str, visits: tuple[Visit, ...]
) -> dict[str, Any]:
    traversal = []
    candidates = []
    principles = []
    for visit in visits:
        node = graph.nodes[visit.node_id]
        item = {
            "id": visit.node_id,
            "kind": node["kind"],
            "name": node["name"],
            "depth": visit.depth,
            "score": visit.score,
            "parent_id": visit.parent_id,
            "relation": visit.relation,
            "direction": visit.direction,
            "rationale": visit.rationale,
        }
        traversal.append(item)
        if node["kind"] == "pattern":
            candidates.append(
                {
                    **item,
                    "summary": node["summary"],
                    "applicability": node["applicability"],
                    "tradeoffs": node["tradeoffs"],
                    "avoid_when": node["avoid_when"],
                }
            )
        elif node["kind"] == "principle":
            principles.append(
                {
                    **item,
                    "summary": node["summary"],
                    "cues": node["cues"],
                    "guardrails": node["guardrails"],
                }
            )
    candidates.sort(key=lambda item: (-item["score"], item["id"]))
    principles.sort(key=lambda item: (-item["score"], item["id"]))
    return {
        "query": query,
        "traversal": traversal,
        "principles": principles,
        "candidates": candidates,
    }


def _print_text(payload: dict[str, Any]) -> None:
    if not payload["traversal"]:
        print("No graph nodes matched the review pressure.")
        return
    for item in payload["traversal"]:
        route = "seed"
        if item["relation"]:
            arrow = "->" if item["direction"] == "outbound" else "<-"
            route = f"{item['parent_id']} {arrow}[{item['relation']}]"
        print(
            f"depth={item['depth']} | {item['kind']} | {item['id']} | "
            f"{item['name']} | score={item['score']:.3f} | {route}"
        )
    if payload["candidates"]:
        print("Candidates:")
        for candidate in payload["candidates"]:
            print(f"- {candidate['name']}: {candidate['summary']}")
    if payload["principles"]:
        print("Principles:")
        for principle in payload["principles"]:
            print(f"- {principle['name']}: {principle['summary']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the code-review design graph"
    )
    parser.add_argument("query", nargs="?", help="Observed design pressure")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Review graph manifest JSON",
    )
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--max-nodes", type=int, default=8)
    parser.add_argument("--max-seeds", type=int, default=3)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the manifest without searching",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        graph = load_manifest(args.manifest.resolve())
        if args.validate:
            print(
                f"Valid review graph: {len(graph.nodes)} nodes, "
                f"{len(graph.edges)} edges."
            )
            return 0
        if not args.query:
            raise ValueError("query is required unless --validate is used")
        visits = traverse(
            graph,
            args.query,
            max_depth=args.depth,
            max_nodes=args.max_nodes,
            max_seeds=args.max_seeds,
        )
        payload = result_payload(graph, args.query, visits)
    except (ManifestError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
