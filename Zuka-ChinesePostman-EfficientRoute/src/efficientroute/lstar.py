"""Stage 3 item 1 — the node-split transform, L → L*.

`L(G)` has **nodes** that must be visited.  Postman problems are defined over
**edges**.  Every arc-routing formulation that tries to cover nodes directly is
solving a different problem than the one it thinks it is, so the split comes
first and everything else is built on top of it.

Each L-node `a` becomes two L*-nodes joined by the edges that price a traversal::

    a_in ──[ capture:  lower = upper = min_passes(a), cost = capture_time_s(a) ]──▶ a_out
         └─[ deadhead: lower = 0, upper = ∞,          cost = deadhead_time_s(a) ]─┘

and each legal manoeuvre `a → b` becomes `a_out → b_in` at the turn penalty.

"Cover arc `a` at least `k` times" is now exactly "traverse the required edge
`(a_in, a_out)` `k` times", which is a Directed Chinese Postman with lower
bounds — solved exactly by min-cost flow with lower bounds.

**Two edges, not one.**  The stage brief describes a single required edge at
`capture_time_s`.  SPEC §6 is more specific: "Hard-capped at `capture_speed_max`
on every **required** traversal.  Deadhead segments are uncapped."  A repeat pass
that no requirement asked for is a deadhead segment, so it is priced at the
uncapped speed.  Splitting the edge in two is the only way to charge the two
kinds of traversal differently, and since `deadhead_time_s ≤ capture_time_s`
always, the flow uses the capture edge exactly `min_passes` times without needing
to be told to.

Costs are integer **milliseconds**: min-cost flow needs integers, and a
millisecond is four orders of magnitude below anything the model can resolve.
Reported totals are recomputed in seconds from the original floats, so the
discretisation never reaches a number a reader sees.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

#: Edge kinds, used as an array code rather than a string for compactness.
CAPTURE, DEADHEAD, MANOEUVRE = 0, 1, 2
KIND_NAMES = ("capture", "deadhead", "manoeuvre")

#: A finite stand-in for ∞.  Finite so that a runaway flow is a caught assertion
#: rather than a silently enormous answer; `assert_no_saturation` checks it.
CAPACITY_INF = 10_000

MS_PER_S = 1000.0


def to_ms(seconds: np.ndarray) -> np.ndarray:
    """Round-half-even to integer milliseconds. Deterministic (CLAUDE.md rule 5)."""
    return np.rint(np.asarray(seconds, dtype="float64") * MS_PER_S).astype("int64")


@dataclasses.dataclass(frozen=True)
class LStar:
    """`L*` as flat arrays: one row per edge, three contiguous blocks.

    Block layout is fixed and relied upon by everything downstream:

    ==============  ==================================  =====================
    edge index      kind                                count
    ==============  ==================================  =====================
    ``[0, n)``      capture  (a_in → a_out)             one per L-node
    ``[n, 2n)``     deadhead (a_in → a_out)             one per L-node
    ``[2n, m)``     manoeuvre (a_out → b_in)            one per legal turn
    ==============  ==================================  =====================
    """

    n_arc_nodes: int
    tail: np.ndarray
    head: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    cost_ms: np.ndarray
    cost_s: np.ndarray
    kind: np.ndarray
    #: For capture/deadhead edges, the L-node it prices; for manoeuvres, its source.
    edge_from_node: np.ndarray
    #: For manoeuvres, the L-node it leads to; -1 otherwise.
    edge_to_node: np.ndarray
    arc_id: np.ndarray
    #: Per L-node: index into `arc_id` of the pair partner, or -1.
    partner: np.ndarray
    #: Per L-node: a group id shared by every variant of the same arc.  A
    #: restriction clone is a second routing context for one street, not a second
    #: street, so coverage is counted per group and never per node.
    arc_group: np.ndarray
    #: Per L-node: min_passes as SPEC §2.1 assigns it, before any orientation.
    min_passes: np.ndarray
    #: Per L-node: 1 where the arc belongs to a shared narrow pair.
    pair_requirement: np.ndarray
    #: Per L-node: True where the arc is inside the strongly connected component
    #: the tour lives in.  Arcs outside it are legal traps — enterable but not
    #: leavable, or the reverse — which Stage 1 already found and attributed.  A
    #: closed tour cannot contain one, so their requirement is out of scope here
    #: and is reported rather than silently met (CLAUDE.md rule 4).
    in_scope: np.ndarray

    # ------------------------------------------------------------------ shape

    @property
    def n_nodes(self) -> int:
        return 2 * self.n_arc_nodes

    @property
    def n_edges(self) -> int:
        return int(len(self.tail))

    @property
    def n_manoeuvres(self) -> int:
        return self.n_edges - 2 * self.n_arc_nodes

    def node_in(self, arc_node: np.ndarray | int):
        return arc_node

    def node_out(self, arc_node: np.ndarray | int):
        return self.n_arc_nodes + np.asarray(arc_node) if isinstance(
            arc_node, np.ndarray
        ) else self.n_arc_nodes + arc_node

    def capture_edge(self, arc_node: int) -> int:
        return arc_node

    def deadhead_edge(self, arc_node: int) -> int:
        return self.n_arc_nodes + arc_node

    # ------------------------------------------------------------- supplies

    def mcf_supplies(self) -> np.ndarray:
        """Node supply for the min-cost flow, in the solver's sign convention.

        Substituting ``x_e = l_e + y_e`` turns "traverse each required edge at
        least `l_e` times, and balance every node" into an ordinary min-cost flow
        in `y ≥ 0` whose node divergence is set by the lower bounds::

            outflow(y, v) − inflow(y, v) = Σ_in l − Σ_out l

        which is what OR-Tools calls the node's *supply*.  Only capture edges
        carry a lower bound, so the arithmetic collapses to: `a_out` is a source
        of `l_a` (having driven the arc, the car is somewhere and must go on) and
        `a_in` is a sink of the same (the arc has to be reached before it can be
        driven).  Positive is a source, negative a sink.
        """
        supply = np.zeros(self.n_nodes, dtype="int64")
        np.add.at(supply, self.head, self.lower)
        np.subtract.at(supply, self.tail, self.lower)
        return supply


def largest_strong_component(graph) -> np.ndarray:
    """Boolean mask of the L-nodes in the largest strongly connected component.

    Recomputed here rather than read from Stage 1's audit: each scope variant
    builds its own `L`, and a mask copied from variant A would quietly be wrong
    for D and C.
    """
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components

    src = [a for a, row in enumerate(graph.adjacency) for _ in row]
    dst = [b for row in graph.adjacency for b in row]
    matrix = sp.coo_matrix(
        (np.ones(len(src), dtype="int8"), (src, dst)),
        shape=(graph.n_nodes, graph.n_nodes),
    ).tocsr()
    _count, labels = connected_components(matrix, directed=True, connection="strong")
    sizes = np.bincount(labels)
    return labels == int(np.argmax(sizes))


def build(
    graph,
    capture_s: np.ndarray,
    deadhead_s: np.ndarray,
    lower_bounds: np.ndarray,
    keep: np.ndarray | None = None,
) -> LStar:
    """Split every node of `graph` (a `turngraph.TurnGraph`).

    `capture_s`, `deadhead_s` and `lower_bounds` are per-L-node arrays in the
    graph's own node order, so the caller decides the orientation (which of a
    narrow pair carries the requirement) and this function stays a pure
    transform.

    `keep` marks the L-nodes a closed tour can reach.  Nodes outside it keep
    their index — so a tour is always expressed in L-node terms and nothing
    downstream has to translate — but every edge that touches one is given zero
    capacity, which isolates it from the flow without renumbering anything.
    """
    n = graph.n_nodes
    for name, array in (
        ("capture_s", capture_s), ("deadhead_s", deadhead_s), ("lower_bounds", lower_bounds)
    ):
        if len(array) != n:
            raise ValueError(f"{name} has {len(array)} rows for {n} L-nodes")

    capture_s = np.asarray(capture_s, dtype="float64")
    deadhead_s = np.asarray(deadhead_s, dtype="float64")
    if np.any(deadhead_s > capture_s + 1e-9):
        raise ValueError(
            "a deadhead traversal is slower than a capture traversal on some arc; "
            "the capture cap can only reduce speed (SPEC §6)"
        )
    lower = np.asarray(lower_bounds, dtype="int64").copy()
    if np.any(lower < 0):
        raise ValueError("a negative lower bound is not a coverage requirement")

    in_scope = np.ones(n, dtype=bool) if keep is None else np.asarray(keep, dtype=bool)
    if len(in_scope) != n:
        raise ValueError(f"keep has {len(in_scope)} rows for {n} L-nodes")
    lower[~in_scope] = 0

    src, dst, penalty_s = [], [], []
    for a, row in enumerate(graph.adjacency):
        for b, (_code, penalty) in row.items():
            src.append(a)
            dst.append(b)
            penalty_s.append(penalty)
    order = np.lexsort((np.asarray(dst, dtype="int64"), np.asarray(src, dtype="int64")))
    src = np.asarray(src, dtype="int64")[order]
    dst = np.asarray(dst, dtype="int64")[order]
    penalty_s = np.asarray(penalty_s, dtype="float64")[order]

    node_in = np.arange(n, dtype="int64")
    node_out = node_in + n

    tail = np.concatenate([node_in, node_in, node_out[src]])
    head = np.concatenate([node_out, node_out, node_in[dst]])
    lower_all = np.concatenate([lower, np.zeros(n, dtype="int64"),
                                np.zeros(len(src), dtype="int64")])
    upper_all = np.concatenate([
        lower,
        np.where(in_scope, CAPACITY_INF, 0).astype("int64"),
        np.where(in_scope[src] & in_scope[dst], CAPACITY_INF, 0).astype("int64"),
    ])
    cost_s = np.concatenate([capture_s, deadhead_s, penalty_s])
    kind = np.concatenate([
        np.full(n, CAPTURE, dtype="int8"),
        np.full(n, DEADHEAD, dtype="int8"),
        np.full(len(src), MANOEUVRE, dtype="int8"),
    ])
    edge_from = np.concatenate([node_in, node_in, src])
    edge_to = np.concatenate([np.full(n, -1, dtype="int64"), np.full(n, -1, dtype="int64"), dst])

    index = graph.arc_index
    arc_id = index["arc_id"].to_numpy()
    partner = _partner_index(index)
    arc_group = pd.factorize(pd.Index(arc_id), sort=True)[0].astype("int64")

    return LStar(
        n_arc_nodes=n,
        tail=tail,
        head=head,
        lower=lower_all,
        upper=upper_all,
        cost_ms=to_ms(cost_s),
        cost_s=cost_s,
        kind=kind,
        edge_from_node=edge_from,
        edge_to_node=edge_to,
        arc_id=arc_id,
        partner=partner,
        arc_group=arc_group,
        min_passes=index["min_passes"].to_numpy(dtype="int64"),
        pair_requirement=index["pair_requirement"].to_numpy(dtype="int64"),
        in_scope=in_scope,
    )


def _partner_index(index: pd.DataFrame) -> np.ndarray:
    """Per L-node, the row of its narrow-pair partner, or -1.

    Restriction clones share an `arc_id` with their original, so the lookup is
    built on the primary variant only and every variant of an arc points at the
    primary variant of its partner.
    """
    partner = np.full(len(index), -1, dtype="int64")
    primary = index.index[index["variant"].to_numpy() == 0]
    row_of_arc = {index.at[i, "arc_id"]: int(i) for i in primary}

    pair_id = index["pair_id"].fillna("").to_numpy()
    arc_id = index["arc_id"].to_numpy()
    members: dict[str, list[str]] = {}
    for i in primary:
        key = pair_id[i]
        if key:
            members.setdefault(key, []).append(arc_id[i])

    twin_of: dict[str, str] = {}
    for key, arcs in members.items():
        if len(arcs) == 2:
            twin_of[arcs[0]], twin_of[arcs[1]] = arcs[1], arcs[0]

    for i in range(len(index)):
        twin = twin_of.get(arc_id[i])
        if twin is not None and twin in row_of_arc:
            partner[i] = row_of_arc[twin]
    return partner


def assert_no_saturation(flow: np.ndarray, star: LStar) -> None:
    """A flow at the sentinel capacity means `CAPACITY_INF` became a real constraint."""
    saturated = np.flatnonzero(np.asarray(flow) >= CAPACITY_INF)
    if saturated.size:
        raise AssertionError(
            f"{saturated.size} edges hit the CAPACITY_INF sentinel; the answer is "
            "capacity-constrained rather than cost-optimal"
        )
