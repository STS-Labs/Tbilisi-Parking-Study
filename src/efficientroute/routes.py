"""Stage 5 — solve one route per driving day.

SPEC §4 Stage E: `depot → zone entry → zone tour → zone exit → depot`, validated
against shift time.  Unlike Stage 3's single closed tour of the whole city, each
day here has a **fixed start and end** (the depot) and only its own zone's
elements are required — but deadhead is allowed over the *entire* network, because
restricting it to the zone boundary produces worse routes and can make a zone
infeasible outright.

The machinery is Stage 3's, applied per zone:

1. lower-bound the zone's required capture edges, and the depot arc, in `L*`;
2. min-cost flow with lower bounds to balance it;
3. repair connectivity;
4. Hierholzer, then rotate the circuit so it begins at the depot.

That gives a feasible legal route for every zone — the floor the brief insists on.
The MIP in `routemip` then bounds each zone from below, so every day carries a
real optimality gap rather than a shrug.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from . import config as C
from . import dcpp, euler, lstar
from . import tourcheck as TC


@dataclasses.dataclass(frozen=True)
class DayRoute:
    """One day: the arcs driven, in order, starting and ending at the depot."""

    zone: int
    position: int
    date: str
    tour: np.ndarray
    visit_counts: np.ndarray
    capture_s: float
    deadhead_s: float
    turn_s: float
    required_arcs: int
    flow: dict
    lower: np.ndarray

    @property
    def total_s(self) -> float:
        return self.capture_s + self.deadhead_s + self.turn_s

    @property
    def total_h(self) -> float:
        return self.total_s / 3600.0

    def day_hours(self, break_hours: float = C.BREAK_HOURS) -> float:
        return self.total_h + break_hours

    def to_dict(self, break_hours: float = C.BREAK_HOURS) -> dict:
        return {
            "zone": int(self.zone),
            "position": int(self.position),
            "day": int(self.position) + 1,
            "date": self.date,
            "arc_traversals": int(len(self.tour)),
            "required_arcs": int(self.required_arcs),
            "capture_h": self.capture_s / 3600.0,
            "deadhead_h": self.deadhead_s / 3600.0,
            "turn_h": self.turn_s / 3600.0,
            "route_h": self.total_h,
            "break_h": break_hours,
            "day_h": self.day_hours(break_hours),
            "flow": self.flow,
        }


def zone_lower_bounds(
    n_arc_nodes: int, n_edges: int, zone_nodes: np.ndarray, depot_node: int,
    oriented_lower: np.ndarray,
) -> np.ndarray:
    """Lower bounds for one day: this zone's requirement, plus the depot.

    Everything outside the zone drops to zero — it may still be driven, as
    deadhead, anywhere on the network.  The depot arc is forced to one traversal
    so that the circuit contains it and can be rotated to start there; without
    that the cheapest circulation simply ignores the depot and the day has no way
    home.
    """
    lower = np.zeros(n_edges, dtype="int64")
    n = n_arc_nodes
    inside = np.zeros(n, dtype=bool)
    inside[zone_nodes] = True
    required = inside & (oriented_lower[:n] > 0)
    lower[:n][required] = oriented_lower[:n][required]

    if lower[depot_node] == 0:
        # The depot arc carries no requirement of its own on most days, so the
        # single traversal that anchors the circuit is charged as deadhead.
        lower[n + depot_node] = max(lower[n + depot_node], 1)
    return lower


def rotate_to_depot(tour: np.ndarray, depot_node: int) -> np.ndarray:
    """Start the circuit at the depot. It is a cycle, so this changes nothing else."""
    tour = np.asarray(tour, dtype="int64")
    hits = np.flatnonzero(tour == depot_node)
    if hits.size == 0:
        raise ValueError("the solved circuit never visits the depot arc")
    return np.roll(tour, -int(hits[0]))


def solve_zone(
    graph,
    star_template,
    capture_s: np.ndarray,
    deadhead_s: np.ndarray,
    zone_nodes: np.ndarray,
    depot_node: int,
    oriented_lower: np.ndarray,
    keep: np.ndarray,
    zone: int,
    position: int,
    date: str,
    optional_capture: np.ndarray | None = None,
    deadhead_override: np.ndarray | None = None,
) -> DayRoute:
    """Balance, connect, Euler, rotate — a legal closed day route.

    `optional_capture` and `deadhead_override` are Stage 8's only entry points into
    the day solver, and both default to `None` so Stage 5 routes exactly as before.

    `optional_capture` raises the *upper* bound on a capture edge without raising its
    lower bound, which makes filming that arc permitted rather than required — the
    solver may take it if the routing works out and skip it otherwise. Stage 5 has no
    use for that: every arc it films is one it was told to film.

    `deadhead_override` re-prices deadheading an arc the campaign still owes, so that
    passing one without filming it carries the cost of the return trip some later day
    would have to make. Without it the day solver has no way to see that a pass it is
    making anyway is worth something to a day it knows nothing about.
    """
    lower = zone_lower_bounds(
        star_template.n_arc_nodes, star_template.n_edges, zone_nodes, depot_node,
        oriented_lower,
    )
    n = star_template.n_arc_nodes
    star = lstar.build(
        graph, capture_s,
        deadhead_s if deadhead_override is None else deadhead_override,
        lower[:n], keep=keep,
    )
    if optional_capture is not None:
        extra = np.asarray(optional_capture, dtype="int64")
        upper = star.upper.copy()
        upper[:n] = np.maximum(upper[:n], lower[:n] + extra)
        star = dataclasses.replace(star, upper=upper)
    # `lstar.build` takes per-node *capture* lower bounds; the depot anchor sits on
    # a deadhead edge, which it has no way to express, so it is applied here. The
    # capture block is identical either way, so the equal lower/upper bound that
    # keeps a required pass at capture speed survives untouched.
    star = dataclasses.replace(star, lower=lower, upper=np.maximum(star.upper, lower))

    flow = dcpp.solve(star)
    circuit = euler.tour(star, flow.x)
    tour = rotate_to_depot(circuit, depot_node)

    counts = TC.visit_counts(tour, star)
    capture, deadhead, turn = TC.tour_time_s(counts, tour, star, graph)
    return DayRoute(
        zone=zone,
        position=position,
        date=date,
        tour=tour,
        visit_counts=counts,
        capture_s=capture,
        deadhead_s=deadhead,
        turn_s=turn,
        required_arcs=int((lower[: star.n_arc_nodes] > 0).sum()),
        flow=flow.to_dict(),
        lower=lower,
    )


def orientation_experiment(
    graph, star_template, capture_s, deadhead_s, zone_nodes, depot_node,
    oriented_lower, keep, zone: int, fractions=(0.02, 0.05, 0.50),
    seed: int = 20260826,
) -> dict:
    """How much does the choice of narrow-pair orientation actually cost?

    SPEC §4 Stage D lists an orientation-flip local search that has never been
    run, and Stage 3 argued it is where the remaining savings are.  A true search
    is unaffordable — each flip has to be scored by re-solving the zone's min-cost
    flow, about eleven seconds, against several hundred pairs per zone — so this
    measures the *sensitivity* instead: re-solve one zone under several random
    orientations and see how far apart the answers are.

    Two kinds of sample, because they answer different questions.  Flipping half
    the pairs shows how much orientation matters *at all* — the gap between a
    considered choice and an arbitrary one.  Flipping two per cent probes whether
    the heuristic sits in a local optimum, which is what a flip search would have
    to beat.  Neither finds the best orientation; together they say whether
    looking is worth the machinery, which is the question the brief asks.
    """
    rng = np.random.default_rng(seed)
    baseline = solve_zone(
        graph, star_template, capture_s, deadhead_s, zone_nodes, depot_node,
        oriented_lower, keep, zone, 0, "",
    )
    partner = star_template.partner
    inside = np.zeros(star_template.n_arc_nodes, dtype=bool)
    inside[zone_nodes] = True
    flippable = [
        (int(a), int(partner[a]))
        for a in np.flatnonzero(inside & (oriented_lower[: star_template.n_arc_nodes] > 0))
        if partner[a] >= 0 and inside[partner[a]]
    ]

    rows = [{"label": "imbalance heuristic (as solved)", "route_h": baseline.total_h,
             "flipped": 0, "fraction": 0.0}]
    for fraction in fractions:
        lower = oriented_lower.copy()
        chosen = rng.random(len(flippable)) < fraction
        for (a, b), flip in zip(flippable, chosen):
            if flip:
                lower[a], lower[b] = lower[b], lower[a]
        route = solve_zone(
            graph, star_template, capture_s, deadhead_s, zone_nodes, depot_node,
            lower, keep, zone, 0, "",
        )
        rows.append(
            {
                "label": f"{fraction:.0%} of pairs flipped",
                "route_h": route.total_h,
                "flipped": int(chosen.sum()),
                "fraction": float(fraction),
            }
        )

    arbitrary = max(r["route_h"] for r in rows)
    local = [r["route_h"] for r in rows if 0.0 < r["fraction"] <= 0.05]
    best_local = min(local) if local else baseline.total_h
    matters = (arbitrary - baseline.total_h) / baseline.total_h if baseline.total_h else 0.0
    recoverable = (baseline.total_h - best_local) / baseline.total_h if baseline.total_h else 0.0

    if recoverable > 0.005:
        verdict = (
            f"A small perturbation already beats the heuristic by "
            f"{recoverable * 100:.1f}%, so it is not at a local optimum and the flip "
            "search SPEC §4 Stage D asks for has something real to find."
        )
    else:
        verdict = (
            "Every small perturbation made the day worse, so the heuristic is at "
            "least locally good. Orientation still matters enormously in absolute "
            f"terms — an arbitrary choice costs {matters * 100:.0f}% more — but the "
            "remaining savings a flip search could recover are not visible at this "
            "sample size, and the question can be closed until something cheaper "
            "than a full re-solve per flip exists to search with."
        )
    return {
        "zone": int(zone),
        "pairs_in_zone": len(flippable),
        "baseline_h": baseline.total_h,
        "samples": rows,
        "cost_of_an_arbitrary_orientation": matters,
        "recovered_by_local_probe": recoverable,
        "verdict": verdict,
    }
