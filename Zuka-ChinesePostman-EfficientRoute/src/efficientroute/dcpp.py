"""Stage 3 item 2.2 — the Directed Chinese Postman as min-cost flow.

Given `L*` with lower bounds on its capture edges, find the cheapest way to make
every node balanced.  Balanced *and connected* is Eulerian, and an Euler circuit
of the augmented multigraph is a closed tour driving every required arc at least
as often as required.

Balance is the easy half: min-cost flow with lower bounds solves it exactly in
polynomial time.  **Connectivity is the hard half, and it is where the NP-hardness
lives.**  Only some edges are required — the unoriented half of every narrow pair
is free, and so is every manoeuvre — so the cheapest circulation is free to fall
into many separately-balanced pieces, each internally Eulerian and mutually
unreachable.  On Tbilisi it does exactly that: one component of 264,572 nodes and
about 1,150 small ones.

The repair is iterative and deliberately not clever:

1. Solve the flow.
2. If the used edges are weakly connected, stop.
3. Otherwise force a cheapest entry path from the main component into each
   stranded one by raising its lower bounds, and solve again.  The re-solve
   rebalances everything, including finding its own way back out.

Forcing lower bounds can only raise the cost, which is the price of connectivity
and is reported separately from the flow optimum.  This is a heuristic; a better
one would produce a cheaper tour.  The result stays a valid **upper** bound
either way, which is all the constructive half of Stage 3 claims.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from . import lstar as LS
from .lstar import LStar

#: The connectivity repair is a fixed point; in practice it converges in two or
#: three rounds.  The cap exists so a pathological network fails loudly.
MAX_CONNECT_ROUNDS = 12


@dataclasses.dataclass(frozen=True)
class FlowSolution:
    """Per-edge traversal counts, and how they were arrived at."""

    x: np.ndarray
    cost_ms: int
    balance_cost_ms: int
    components_initial: int
    rounds: int
    forced_edges: int
    stranded_nodes: int

    @property
    def connectivity_cost_ms(self) -> int:
        return int(self.cost_ms - self.balance_cost_ms)

    def to_dict(self) -> dict:
        return {
            "components_initial": int(self.components_initial),
            "connect_rounds": int(self.rounds),
            "forced_edges": int(self.forced_edges),
            "stranded_nodes": int(self.stranded_nodes),
            "balance_cost_s": self.balance_cost_ms / LS.MS_PER_S,
            "connectivity_cost_s": self.connectivity_cost_ms / LS.MS_PER_S,
            "total_cost_s": self.cost_ms / LS.MS_PER_S,
        }


def solve(star: LStar) -> FlowSolution:
    """Balance, then connect, then balance again until one component remains."""
    lower = star.lower.copy()
    lookup = _augmentable_edge_lookup(star)

    components_initial = 0
    balance_cost = 0
    stranded = 0
    forced = 0

    for round_index in range(1, MAX_CONNECT_ROUNDS + 1):
        x, cost = _min_cost_flow(star, lower)
        count, labels, touched = _weak_components(star, x > 0)
        if round_index == 1:
            components_initial = count
            balance_cost = cost
        if count <= 1:
            return FlowSolution(
                x=x,
                cost_ms=cost,
                balance_cost_ms=balance_cost,
                components_initial=components_initial,
                rounds=round_index - 1,
                forced_edges=forced,
                stranded_nodes=stranded,
            )

        added, stranded_now = _force_entries(star, lower, labels, touched, lookup)
        if added == 0:
            raise RuntimeError(
                f"{count} components remain and no connecting path could be forced; "
                "L* is not strongly connected over the arcs the tour must cover"
            )
        forced += added
        if round_index == 1:
            stranded = stranded_now

    raise RuntimeError(
        f"connectivity repair did not converge in {MAX_CONNECT_ROUNDS} rounds"
    )


def _min_cost_flow(star: LStar, lower: np.ndarray) -> tuple[np.ndarray, int]:
    from ortools.graph.python import min_cost_flow

    residual = star.upper - lower
    if np.any(residual < 0):
        raise ValueError("a lower bound exceeds its edge's capacity")
    live = np.flatnonzero(residual > 0)

    solver = min_cost_flow.SimpleMinCostFlow()
    solver.add_arcs_with_capacity_and_unit_cost(
        star.tail[live], star.head[live], residual[live], star.cost_ms[live]
    )
    supply = np.zeros(star.n_nodes, dtype="int64")
    np.add.at(supply, star.head, lower)
    np.subtract.at(supply, star.tail, lower)
    solver.set_nodes_supplies(np.arange(star.n_nodes, dtype="int64"), supply)

    status = solver.solve()
    if status != solver.OPTIMAL:
        raise RuntimeError(
            f"min-cost flow did not reach optimality (status {status}); the "
            "balancing problem is infeasible over this L*"
        )

    x = lower.copy()
    x[live] += np.asarray(solver.flows(np.arange(len(live))), dtype="int64")
    LS.assert_no_saturation(x, star)
    cost = int(solver.optimal_cost() + int((lower * star.cost_ms).sum()))
    return x, cost


def _weak_components(star: LStar, used: np.ndarray):
    """Components of the used-edge multigraph, ignoring direction.

    A balanced digraph is Eulerian exactly when its used edges are *weakly*
    connected, so weak connectivity is the right question.  Untouched nodes are
    not components: an arc the tour never drives is not a piece of the tour.
    """
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components

    tail, head = star.tail[used], star.head[used]
    matrix = sp.coo_matrix(
        (np.ones(len(tail), dtype="int8"), (tail, head)),
        shape=(star.n_nodes, star.n_nodes),
    ).tocsr()
    _count, labels = connected_components(matrix, directed=False)

    touched = np.zeros(star.n_nodes, dtype=bool)
    touched[tail] = True
    touched[head] = True
    return int(len(np.unique(labels[touched]))), labels, touched


def _augmentable_edge_lookup(star: LStar) -> dict[tuple[int, int], int]:
    """Cheapest edge per (tail, head) that can still carry more flow.

    Capture edges are excluded by construction: their lower and upper bounds are
    equal, so raising a lower bound on one would ask for a traversal the edge is
    not allowed to make.  For a split arc that leaves the deadhead edge, which is
    also the cheaper of the two and therefore the right one to route through.
    """
    best: dict[tuple[int, int], int] = {}
    augmentable = np.flatnonzero(star.upper > star.lower)
    for index in augmentable:
        key = (int(star.tail[index]), int(star.head[index]))
        current = best.get(key)
        if current is None or star.cost_ms[index] < star.cost_ms[current]:
            best[key] = int(index)
    return best


def _force_entries(star, lower, labels, touched, lookup) -> tuple[int, int]:
    """Raise lower bounds along a cheapest path into each stranded component.

    One multi-source Dijkstra from *every* node of the main component at once, so
    each stranded piece is connected to its nearest neighbour in the main body
    rather than to some arbitrary anchor.  Only the way *in* is forced; the
    re-solve finds its own way back out, and finds the cheapest one.
    """
    import scipy.sparse as sp
    from scipy.sparse.csgraph import dijkstra

    sizes = np.bincount(labels[touched], minlength=int(labels.max()) + 1)
    main_label = int(np.argmax(sizes))
    main_nodes = np.flatnonzero(touched & (labels == main_label))

    source = star.n_nodes
    live = np.flatnonzero(star.upper > 0)
    # +1 ms on every edge: a zero-cost straight-on manoeuvre would otherwise be
    # dropped as an explicit zero by the sparse matrix and the path would be
    # unreachable through it.
    weights = np.concatenate([
        star.cost_ms[live].astype("float64") + 1.0,
        np.ones(len(main_nodes), dtype="float64"),
    ])
    rows = np.concatenate([star.tail[live], np.full(len(main_nodes), source)])
    cols = np.concatenate([star.head[live], main_nodes])
    matrix = sp.coo_matrix(
        (weights, (rows, cols)), shape=(star.n_nodes + 1, star.n_nodes + 1)
    ).tocsr()

    distance, predecessor = dijkstra(matrix, indices=source, return_predecessors=True)

    added = 0
    stranded = 0
    for label in np.unique(labels[touched]):
        if label == main_label:
            continue
        members = np.flatnonzero(touched & (labels == label))
        stranded += len(members)
        reachable = members[np.isfinite(distance[members])]
        if reachable.size == 0:
            continue
        target = int(reachable[np.argmin(distance[reachable])])
        added += _force_path(star, lower, lookup, predecessor, source, target)
    return added, stranded


def _force_path(star, lower, lookup, predecessor, source, target) -> int:
    """Walk the predecessor chain back to the main component, forcing each edge."""
    node = target
    forced = 0
    while True:
        previous = int(predecessor[node])
        if previous == source or previous < 0:
            return forced
        index = lookup.get((previous, node))
        if index is None:
            raise RuntimeError(
                f"the Dijkstra path uses {previous} -> {node}, which no augmentable "
                "edge of L* provides"
            )
        lower[index] += 1
        if lower[index] > star.upper[index]:
            raise RuntimeError("forcing a connecting path exceeded an edge capacity")
        forced += 1
        node = previous
