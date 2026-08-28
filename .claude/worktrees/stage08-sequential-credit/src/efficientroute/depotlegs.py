"""Stage 4 items 2 and 3 — depot legs, routed rather than estimated.

Stage 2 estimated legs from straight-line distance bands because it had no
routing.  Stage 3 built `L(G)` into a graph with real manoeuvre costs.  So Stage 4
routes them: shortest time from the depot to each zone and back, over `L(G)`,
with turn penalties, one-way streets and turn restrictions all in force.

**Capture on the commute** (SPEC §7.1, mitigation 1) is the second half.  A depot
leg is only deadhead if the corridor it runs along is already covered.  Where it
is not, the leg can drive uncovered required arcs at capture speed instead of
passing them at deadhead speed, and the work stops being owed by a zone.

The accounting, deliberately conservative:

============================  =========================================
added to the leg              ``capture(e) − deadhead(e)`` — the arc is
                              driven slower than it would have been
removed from a zone           ``capture(e)`` — the traversal itself, and
                              *not* the deadhead the zone would have
                              spent reaching it
============================  =========================================

which nets to a saving of ``deadhead(e)`` per arc.  Crediting the zone's
repositioning too would produce a larger number that no measurement supports, so
the figure reported is a floor.

That accounting also makes the routing exact rather than heuristic: under it, the
net cost of traversing an uncovered required arc is **zero**, so the best
coverage-aware leg is an ordinary shortest path with those arcs free.  No
orienteering problem, no NP-hardness — one Dijkstra.  A wall-clock cap stops the
free arcs from buying an absurd detour.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from . import config as C


@dataclasses.dataclass(frozen=True)
class LegField:
    """Travel time from the depot to every L-node, and back, with paths."""

    depot_node: int
    depot_arc_id: str
    depot_offset_m: float
    out_s: np.ndarray
    out_pred: np.ndarray
    back_s: np.ndarray
    back_pred: np.ndarray


@dataclasses.dataclass(frozen=True)
class Leg:
    """One routed depot leg."""

    seconds: float
    node: int
    path: np.ndarray
    captured: np.ndarray
    capture_s: float
    deadhead_saving_s: float
    routed_for_coverage: bool

    def to_dict(self) -> dict:
        return {
            "seconds": self.seconds,
            "hours": self.seconds / 3600.0,
            "arcs": int(len(self.path)),
            "captured_arcs": int(len(self.captured)),
            "capture_s": self.capture_s,
            "deadhead_saving_s": self.deadhead_saving_s,
            "routed_for_coverage": self.routed_for_coverage,
        }


def find_depot_node(frame, graph) -> tuple[int, str, float]:
    """The L-node whose arc passes closest to the depot.

    The depot is a point and `L(G)` is a graph of streets, so the leg has to start
    somewhere real.  The offset is reported rather than absorbed: if the nearest
    drivable arc were far from the depot, every leg in this stage would be wrong
    by that much.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    arc_ids = graph.arc_index["arc_id"].to_numpy()
    rows = frame.set_index("arc_id").loc[arc_ids]
    geometry = gpd.GeoSeries(rows.geometry.values, crs="EPSG:4326").to_crs(C.METRIC_CRS)
    depot = (
        gpd.GeoSeries([Point(C.DEPOT_LON, C.DEPOT_LAT)], crs="EPSG:4326")
        .to_crs(C.METRIC_CRS)
        .iloc[0]
    )
    distance = geometry.distance(depot).to_numpy()
    node = int(np.argmin(distance))
    return node, str(arc_ids[node]), float(distance[node])


def manoeuvre_arrays(graph) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(from, to, turn penalty) for every legal manoeuvre, built once.

    Rebuilding this inside every Dijkstra is a Python loop over 120,000 edges and
    it dominated the stage; the arrays are the same every time, so they are
    hoisted out and handed in.
    """
    src, dst, penalty = [], [], []
    for a, row in enumerate(graph.adjacency):
        for b, (_code, turn) in row.items():
            src.append(a)
            dst.append(b)
            penalty.append(turn)
    return (
        np.asarray(src, dtype="int64"),
        np.asarray(dst, dtype="int64"),
        np.asarray(penalty, dtype="float64"),
    )


def _matrix(
    graph, arc_cost_s: np.ndarray, transpose: bool = False, arrays=None,
    epsilon: float = 0.0,
):
    """`L(G)` as a sparse cost matrix: leaving `a` for `b` costs turn + traverse `b`.

    `epsilon` exists for one case only.  A sparse matrix drops explicit zeros, so
    an edge that costs nothing is not an edge at all — and in the coverage-aware
    routing an uncovered required arc costs exactly nothing by design.  A
    millisecond keeps it in the matrix.  Deadhead costs are always positive, so
    the plain leg field is built with `epsilon = 0` and the times it reports are
    exact rather than a millisecond per manoeuvre too long.
    """
    import scipy.sparse as sp

    src, dst, penalty = manoeuvre_arrays(graph) if arrays is None else arrays
    cost = penalty + arc_cost_s[dst] + epsilon
    matrix = sp.coo_matrix(
        (cost, (src, dst)), shape=(graph.n_nodes, graph.n_nodes)
    ).tocsr()
    return matrix.T.tocsr() if transpose else matrix


def leg_field(graph, deadhead_s: np.ndarray, depot_node: int, depot_arc_id: str,
              depot_offset_m: float, arrays=None) -> LegField:
    """One Dijkstra out and one back, giving every zone's leg for free."""
    from scipy.sparse.csgraph import dijkstra

    arrays = manoeuvre_arrays(graph) if arrays is None else arrays
    out_s, out_pred = dijkstra(
        _matrix(graph, deadhead_s, arrays=arrays), indices=depot_node,
        return_predecessors=True,
    )
    back_s, back_pred = dijkstra(
        _matrix(graph, deadhead_s, transpose=True, arrays=arrays), indices=depot_node,
        return_predecessors=True,
    )
    return LegField(
        depot_node=depot_node,
        depot_arc_id=depot_arc_id,
        depot_offset_m=depot_offset_m,
        out_s=out_s,
        out_pred=out_pred,
        back_s=back_s,
        back_pred=back_pred,
    )


def nearest_in_zone(field: LegField, nodes: np.ndarray, outbound: bool) -> tuple[float, int]:
    """Cheapest entry into (or exit from) a set of L-nodes."""
    distance = (field.out_s if outbound else field.back_s)[nodes]
    finite = np.isfinite(distance)
    if not finite.any():
        return float("inf"), int(nodes[0])
    index = int(np.argmin(np.where(finite, distance, np.inf)))
    return float(distance[index]), int(nodes[index])


def _walk(
    predecessors: np.ndarray, source: int, target: int, outbound: bool = True
) -> np.ndarray:
    """The path, in the direction the car drives it.

    The return leg is found by a Dijkstra over the *transposed* graph, so its
    predecessor chain runs depot → zone.  That is the right path and the wrong
    way round: reversing it here means every caller — turn costs, the GPX, the
    coverage credit — sees a sequence of arcs in driving order, and none of them
    has to remember which end it came from.
    """
    path = [target]
    node = target
    while node != source:
        node = int(predecessors[node])
        if node < 0:
            raise ValueError("the predecessor chain does not reach the source")
        path.append(node)
    if outbound:
        path.reverse()
    return np.asarray(path, dtype="int64")


def plain_leg(field: LegField, node: int, outbound: bool) -> Leg:
    """The pure-deadhead leg: no coverage credit, the conservative baseline."""
    if outbound:
        path = _walk(field.out_pred, field.depot_node, node, outbound=True)
        seconds = float(field.out_s[node])
    else:
        path = _walk(field.back_pred, field.depot_node, node, outbound=False)
        seconds = float(field.back_s[node])
    return Leg(
        seconds=seconds,
        node=node,
        path=path,
        captured=np.zeros(0, dtype="int64"),
        capture_s=0.0,
        deadhead_saving_s=0.0,
        routed_for_coverage=False,
    )


def coverage_leg(
    graph,
    capture_s: np.ndarray,
    deadhead_s: np.ndarray,
    required: np.ndarray,
    covered: np.ndarray,
    depot_node: int,
    target_nodes: np.ndarray,
    outbound: bool,
    baseline: Leg,
    detour_cap: float = C.LEG_COVERAGE_DETOUR_CAP,
    arrays=None,
) -> Leg:
    """Route the leg through uncovered required arcs where it pays to.

    Falls back to `baseline` when the coverage-aware path would take longer on the
    clock than `detour_cap` times the plain leg — the saving is real but a day
    still has to close on time.
    """
    from scipy.sparse.csgraph import dijkstra

    free = required & ~covered
    net_cost = np.where(free, 0.0, deadhead_s)
    matrix = _matrix(graph, net_cost, transpose=not outbound, arrays=arrays, epsilon=1e-3)
    distance, predecessors = dijkstra(matrix, indices=depot_node, return_predecessors=True)

    reachable = target_nodes[np.isfinite(distance[target_nodes])]
    if reachable.size == 0:
        return baseline
    node = int(reachable[np.argmin(distance[reachable])])
    try:
        path = _walk(predecessors, depot_node, node, outbound=outbound)
    except ValueError:
        return baseline

    on_path = path[1:]
    captured = on_path[free[on_path]]
    seconds = float(
        sum(capture_s[n] if free[n] else deadhead_s[n] for n in on_path)
        + _turn_cost(graph, path)
    )
    if seconds > detour_cap * baseline.seconds:
        return baseline

    capture_total = float(capture_s[captured].sum())
    return Leg(
        seconds=seconds,
        node=node,
        path=path,
        captured=captured,
        capture_s=capture_total,
        deadhead_saving_s=float(deadhead_s[captured].sum()),
        routed_for_coverage=True,
    )


def _turn_cost(graph, path: np.ndarray) -> float:
    return float(
        sum(graph.adjacency[int(a)][int(b)][1] for a, b in zip(path, path[1:]))
    )
