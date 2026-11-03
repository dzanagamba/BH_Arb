"""Contradiction checks over accepted team aliases.

An alias ledger can merge clubs transitively: A=B and B=C implies A=C. That is
correct only while A and C are never listed as opponents. This module builds the
accepted alias graph, finds an opponent pair inside one connected component, and
revokes the weakest edge on the path until the component splits.

The resolver is deliberately conservative. It does not guess which edge is
"really" wrong; it removes the least-supported edge on the shortest path and
repeats. Every revocation is recorded in the ledger with the contradiction that
caused it, so the next scan can compare against it.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from engine.mapping_evidence import MappingClaim, MappingLedger


@dataclass(frozen=True)
class AliasEdge:
    left: str
    right: str
    claim: MappingClaim

    @property
    def key(self) -> str:
        return f"{self.left}|{self.right}"


def accepted_alias_edges(ledger: MappingLedger) -> list[AliasEdge]:
    edges: list[AliasEdge] = []
    for claim in ledger.claims.values():
        if claim.kind != "team_alias" or not claim.is_authoritative():
            continue
        parts = claim.key.split("|")
        if len(parts) != 2 or not all(parts):
            continue
        edges.append(AliasEdge(parts[0], parts[1], claim))
    return edges


def _adjacency(edges: list[AliasEdge]) -> dict[str, list[AliasEdge]]:
    graph: dict[str, list[AliasEdge]] = defaultdict(list)
    for edge in edges:
        graph[edge.left].append(edge)
        graph[edge.right].append(edge)
    return graph


def _path(
    graph: dict[str, list[AliasEdge]], start: str, goal: str
) -> list[AliasEdge] | None:
    if start == goal:
        return []
    queue: deque[str] = deque([start])
    seen = {start}
    previous: dict[str, tuple[str, AliasEdge]] = {}
    while queue:
        node = queue.popleft()
        for edge in graph.get(node, []):
            other = edge.right if edge.left == node else edge.left
            if other in seen:
                continue
            seen.add(other)
            previous[other] = (node, edge)
            if other == goal:
                path: list[AliasEdge] = []
                current = goal
                while current != start:
                    parent, edge = previous[current]
                    path.append(edge)
                    current = parent
                return list(reversed(path))
            queue.append(other)
    return None


def connected_components(edges: list[AliasEdge]) -> dict[str, frozenset[str]]:
    graph = _adjacency(edges)
    components: dict[str, frozenset[str]] = {}
    seen: set[str] = set()
    for node in graph:
        if node in seen:
            continue
        component: set[str] = set()
        queue: deque[str] = deque([node])
        seen.add(node)
        while queue:
            current = queue.popleft()
            component.add(current)
            for edge in graph.get(current, []):
                other = edge.right if edge.left == current else edge.left
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        frozen = frozenset(component)
        for member in frozen:
            components[member] = frozen
    return components


def revoke_contradictions(
    ledger: MappingLedger, opponent_pairs: set[frozenset[str]]
) -> list[str]:
    """Revoke the weakest alias on every path between two listed opponents.

    Returns the revoked claim keys. The caller keeps the evidence that caused
    each revocation in the ledger's tombstone.
    """
    revoked: list[str] = []
    while True:
        edges = accepted_alias_edges(ledger)
        graph = _adjacency(edges)
        component_of = connected_components(edges)
        contradiction: tuple[str, str] | None = None
        for pair in opponent_pairs:
            if len(pair) != 2:
                continue
            left, right = sorted(pair)
            if left not in component_of or right not in component_of:
                continue
            if component_of[left] is not component_of[right]:
                continue
            contradiction = (left, right)
            break
        if contradiction is None:
            return revoked

        left, right = contradiction
        path = _path(graph, left, right)
        if not path:
            return revoked
        weakest = min(path, key=lambda edge: (edge.claim.confidence, edge.key))
        ledger.revoke(
            "team_alias",
            weakest.key,
            "opponent_contradiction",
        )
        revoked.append(weakest.key)
