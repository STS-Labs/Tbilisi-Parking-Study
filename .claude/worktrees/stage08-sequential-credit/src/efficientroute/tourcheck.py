"""Stage 3 — the invariant suite for a tour.

Written before the solver, deliberately.  A wrong tour is entirely convincing:
it has a plausible length, a plausible deadhead ratio and a plausible map.  The
only thing that separates it from a right one is a check that was written without
knowing how the tour would be produced, so nothing here consults the solver, the
flow, or any intermediate the solver kept.  Everything is recomputed from the
tour and from `L*`.

A tour is a **closed sequence of L-node indices** — the arcs driven, in order.
The manoeuvre between consecutive entries is implied, including the one from the
last entry back to the first, which is what makes it closed.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from .lstar import LStar


@dataclasses.dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.passed


@dataclasses.dataclass(frozen=True)
class TourAudit:
    checks: tuple[Check, ...]
    visit_counts: np.ndarray
    capture_s: float
    deadhead_s: float
    turn_s: float

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    @property
    def total_s(self) -> float:
        return self.capture_s + self.deadhead_s + self.turn_s

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise AssertionError(
                "tour invariants failed:\n"
                + "\n".join(f"  {c.name}: {c.detail}" for c in self.failures)
            )


def manoeuvre_keys(graph) -> np.ndarray:
    """Sorted encoding of every legal manoeuvre of L, for O(log n) membership.

    Encoded as ``a * n + b`` rather than held as a set of tuples: the tour has
    hundreds of thousands of steps and this keeps the I2 check vectorised.
    """
    n = graph.n_nodes
    keys = [a * n + b for a, row in enumerate(graph.adjacency) for b in row]
    return np.sort(np.asarray(keys, dtype="int64"))


def _is_legal(pairs: np.ndarray, keys: np.ndarray, n: int) -> np.ndarray:
    encoded = pairs[:, 0] * n + pairs[:, 1]
    position = np.searchsorted(keys, encoded)
    position = np.clip(position, 0, len(keys) - 1)
    return keys[position] == encoded


def steps(tour: np.ndarray) -> np.ndarray:
    """Consecutive (from, to) pairs including the closing wrap-around."""
    tour = np.asarray(tour, dtype="int64")
    return np.column_stack([tour, np.roll(tour, -1)])


# ------------------------------------------------------------------ the checks


def check_i6_nodes_exist(tour: np.ndarray, star: LStar) -> Check:
    """I6 — every arc in the plan exists in the base network."""
    tour = np.asarray(tour, dtype="int64")
    if tour.size == 0:
        return Check("I6", False, "the tour is empty")
    bad = np.flatnonzero((tour < 0) | (tour >= star.n_arc_nodes))
    return Check(
        "I6",
        bad.size == 0,
        "" if bad.size == 0 else f"{bad.size} entries are not L-nodes, first at step {bad[0]}",
    )


def check_i2_manoeuvres_are_legal(tour: np.ndarray, graph) -> Check:
    """I2 — every consecutive arc pair is a legal edge of L."""
    tour = np.asarray(tour, dtype="int64")
    if tour.size < 2:
        return Check("I2", False, "a tour of fewer than two arcs has no manoeuvres")
    pairs = steps(tour)
    legal = _is_legal(pairs, manoeuvre_keys(graph), graph.n_nodes)
    bad = np.flatnonzero(~legal)
    if bad.size == 0:
        return Check("I2", True)
    first = bad[0]
    return Check(
        "I2",
        False,
        f"{bad.size} illegal manoeuvres; first at step {first}: "
        f"{pairs[first, 0]} -> {pairs[first, 1]}",
    )


def check_closed(tour: np.ndarray, graph) -> Check:
    """The tour returns to where it began by a legal manoeuvre, not by assertion."""
    tour = np.asarray(tour, dtype="int64")
    if tour.size < 2:
        return Check("closed", False, "a tour of fewer than two arcs cannot close")
    pair = np.array([[tour[-1], tour[0]]], dtype="int64")
    legal = bool(_is_legal(pair, manoeuvre_keys(graph), graph.n_nodes)[0])
    return Check(
        "closed",
        legal,
        "" if legal else f"no legal manoeuvre {tour[-1]} -> {tour[0]} to close the circuit",
    )


def visit_counts(tour: np.ndarray, star: LStar) -> np.ndarray:
    counts = np.zeros(star.n_arc_nodes, dtype="int64")
    np.add.at(counts, np.asarray(tour, dtype="int64"), 1)
    return counts


def check_i1_coverage(counts: np.ndarray, star: LStar) -> Check:
    """I1 — SPEC §8 as written, not as the solver oriented it.

    "Every arc is traversed ≥ its `min_passes`; every narrow pair ≥ 1."  The
    orientation the solver chose is one way to satisfy the pair half; this checks
    the requirement itself, so a tour that covered the *other* direction of a
    pair still passes and a tour that covered neither still fails.

    Restricted to `star.in_scope`.  An arc that no closed tour can contain is not
    a coverage failure of *this* tour, and burying it here would hide it; it is
    counted and reported instead.
    """
    scope = star.in_scope
    shared = (star.pair_requirement > 0) & scope
    solo = (star.pair_requirement == 0) & scope

    # Coverage is a property of the arc, so variants of one arc are summed
    # before anything is compared: a required pass driven through a restriction
    # clone still drove the street.
    group = star.arc_group
    by_arc = np.bincount(group, weights=counts, minlength=int(group.max()) + 1)
    arc_counts = by_arc[group].astype("int64")

    short_solo = np.flatnonzero(solo & (arc_counts < star.min_passes))
    partner = star.partner
    has_partner = shared & (partner >= 0)
    pair_total = arc_counts.copy()
    pair_total[has_partner] += arc_counts[partner[has_partner]]
    short_pair = np.flatnonzero(shared & (pair_total < 1))

    orphan_pair = np.flatnonzero(shared & (partner < 0) & (arc_counts < 1))

    problems = []
    if short_solo.size:
        problems.append(
            f"{short_solo.size} arcs below min_passes (first: "
            f"{star.arc_id[short_solo[0]]}, {arc_counts[short_solo[0]]} < "
            f"{star.min_passes[short_solo[0]]})"
        )
    if short_pair.size:
        problems.append(
            f"{short_pair.size // 2} narrow pairs uncovered in both directions "
            f"(first: {star.arc_id[short_pair[0]]})"
        )
    if orphan_pair.size:
        problems.append(
            f"{orphan_pair.size} pair arcs with no partner in L and no traversal "
            f"(first: {star.arc_id[orphan_pair[0]]})"
        )
    return Check("I1", not problems, "; ".join(problems))


def check_lower_bounds_met(counts: np.ndarray, star: LStar) -> Check:
    """The oriented problem the solver was actually given.

    Weaker than I1 in one direction and stronger in another, so both are checked:
    this one fails if the flow did not deliver the lower bounds it was set.
    """
    lower = star.lower[: star.n_arc_nodes]
    short = np.flatnonzero(counts < lower)
    return Check(
        "lower_bounds",
        short.size == 0,
        "" if short.size == 0 else
        f"{short.size} arcs below the oriented lower bound (first: "
        f"{star.arc_id[short[0]]}, {counts[short[0]]} < {lower[short[0]]})",
    )


def tour_time_s(counts: np.ndarray, tour: np.ndarray, star: LStar, graph) -> tuple[float, float, float]:
    """Recompute the tour's time from the arcs and manoeuvres it actually contains.

    Independent of the solver's objective by construction: it reads the tour, not
    the flow.  The first `lower` visits of an arc are the required capture passes
    and are priced at the capped speed; everything beyond them is deadhead and is
    priced uncapped (SPEC §6).
    """
    lower = star.lower[: star.n_arc_nodes]
    captured = np.minimum(counts, lower)
    extra = counts - captured

    capture_cost = star.cost_s[: star.n_arc_nodes]
    deadhead_cost = star.cost_s[star.n_arc_nodes : 2 * star.n_arc_nodes]
    capture_s = float((captured * capture_cost).sum())
    deadhead_s = float((extra * deadhead_cost).sum())

    pairs = steps(np.asarray(tour, dtype="int64"))
    turn_s = float(sum(graph.adjacency[int(a)][int(b)][1] for a, b in pairs))
    return capture_s, deadhead_s, turn_s


def audit(tour: np.ndarray, star: LStar, graph) -> TourAudit:
    """Run every invariant.  Cheap checks first, so a broken tour fails fast."""
    tour = np.asarray(tour, dtype="int64")
    checks = [check_i6_nodes_exist(tour, star)]
    if not checks[0].passed:
        return TourAudit(tuple(checks), np.zeros(star.n_arc_nodes, dtype="int64"), 0.0, 0.0, 0.0)

    checks.append(check_i2_manoeuvres_are_legal(tour, graph))
    checks.append(check_closed(tour, graph))

    counts = visit_counts(tour, star)
    checks.append(check_i1_coverage(counts, star))
    checks.append(check_lower_bounds_met(counts, star))

    if checks[1].passed and checks[2].passed:
        capture_s, deadhead_s, turn_s = tour_time_s(counts, tour, star, graph)
    else:
        capture_s = deadhead_s = turn_s = float("nan")
    return TourAudit(tuple(checks), counts, capture_s, deadhead_s, turn_s)


def check_matches_flow(counts: np.ndarray, flow: np.ndarray, star: LStar) -> Check:
    """The tour traverses each arc exactly as often as the flow paid for.

    A tour that is legal, closed and covering can still not be the solution that
    was priced — if Hierholzer dropped edges, the tour is cheaper than the flow
    and the reported optimality gap is a fiction.
    """
    flow = np.asarray(flow, dtype="int64")
    expected = flow[: star.n_arc_nodes] + flow[star.n_arc_nodes : 2 * star.n_arc_nodes]
    bad = np.flatnonzero(counts != expected)
    return Check(
        "matches_flow",
        bad.size == 0,
        "" if bad.size == 0 else
        f"{bad.size} arcs differ from the flow (first: {star.arc_id[bad[0]]}, "
        f"tour {counts[bad[0]]} vs flow {expected[bad[0]]})",
    )
