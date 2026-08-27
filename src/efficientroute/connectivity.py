"""Strongly connected components over the directed arc graph.

SPEC §3.1: take the largest strongly connected component, and report everything
that falls out — "orphan fragments in the hillside districts are a data-quality
signal, not noise".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import networkx as nx

ArcTriple = tuple[str, int, int]  # (arc_id, from_node, to_node)


def node_components(arcs: Iterable[ArcTriple]) -> list[set[int]]:
    """Node-level strongly connected components, ranked largest first.

    Ties break on the lowest node id so that the ranking — and therefore every
    component index written to the arc table — is deterministic (CLAUDE.md
    rule 5).
    """
    graph = nx.DiGraph()
    for _, tail, head in arcs:
        graph.add_edge(tail, head)
    components = [set(c) for c in nx.strongly_connected_components(graph)]
    components.sort(key=lambda c: (-len(c), min(c)))
    return components


def label_components(arcs: Sequence[ArcTriple]) -> dict[str, int]:
    """Map each arc to its component index, or -1 when it spans two components.

    An arc lies *inside* a component only when both endpoints do; an arc between
    two components is a one-way bridge that no closed tour can use, so it belongs
    to neither.
    """
    arcs = list(arcs)
    components = node_components(arcs)
    membership: dict[int, int] = {}
    for index, component in enumerate(components):
        for node in component:
            membership[node] = index

    labels: dict[str, int] = {}
    for arc_id, tail, head in arcs:
        tail_component = membership.get(tail, -1)
        head_component = membership.get(head, -1)
        labels[arc_id] = tail_component if tail_component == head_component else -1
    return labels
