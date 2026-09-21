"""Stage 4 item 1 — partition the required network into shift-sized zones.

SPEC §4 Stage B: connected, compact zones of roughly one shift each, weighted by
**capture time** and partitioned **over the network**, not over the map.  The
reason is in the spec: the Mtkvari and the ridgelines mean two points 500 m apart
can be 6 km apart by road, so a geometric cluster is not a day's work.

The unit of partition is a **segment** — one physical street piece, carrying one
or two directed arcs — rather than an L-node.  Both directions of a street are
driven on the same day by anyone sane, and splitting them across zones would
manufacture deadhead that no route solver could recover.

Two things are asked of the partition that METIS gives directly:

``contiguous``
    parts must be connected.  Without it METIS will happily return a zone in two
    pieces on opposite sides of the river, which is a day no driver can drive.

``tpwgts``
    per-part target weights.  Not used for the first partition — the far zones
    are not known until the legs are routed — but it is what makes SPEC §7.1
    mitigation 3 ("zone sizing on net productive time") expressible at all.

Balance is then finished by a local search over **day duration**, not over capture
weight, because a far zone with the same capture time is a longer day.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from . import config as C


@dataclasses.dataclass(frozen=True)
class ZoneGraph:
    """Segments of the chosen variant, and how they connect in `L(G)`."""

    segment_id: np.ndarray
    #: Required capture seconds carried by each segment.
    weight_s: np.ndarray
    #: CSR adjacency for METIS, both directions stored.
    xadj: np.ndarray
    adjncy: np.ndarray
    eweights: np.ndarray
    #: Per L-node: its segment index, or -1 if the node is out of scope.
    segment_of_node: np.ndarray
    #: Per segment: the L-node indices it carries.
    nodes_of_segment: list[np.ndarray]
    length_m: np.ndarray

    @property
    def n_segments(self) -> int:
        return len(self.segment_id)

    @property
    def total_weight_s(self) -> float:
        return float(self.weight_s.sum())

    def neighbours(self, segment: int) -> np.ndarray:
        return self.adjncy[self.xadj[segment] : self.xadj[segment + 1]]


def required_traversals(index: pd.DataFrame) -> np.ndarray:
    """Traversals each L-node contributes (SPEC §2.1, §3.4).

    A narrow pair's shared requirement sits on the representative, so the twin
    contributes nothing — the pair is still driven once, and the segment that
    carries both arcs is weighted for exactly that.
    """
    shared = index["pair_requirement"].to_numpy() > 0
    representative = index["is_pair_representative"].to_numpy(dtype=bool)
    return np.where(
        shared,
        np.where(representative, index["pair_requirement"].to_numpy(), 0),
        index["min_passes"].to_numpy(),
    ).astype("int64")


def build(graph, keep: np.ndarray, capture_s: np.ndarray, length_m: np.ndarray) -> ZoneGraph:
    """Collapse `L(G)` onto segments and record how they connect."""
    index = graph.arc_index
    keep = np.asarray(keep, dtype=bool)

    way = index["way_id"].to_numpy()
    seg = index["seg_index"].to_numpy()
    keys = np.array([f"{w}:{s}" for w, s in zip(way, seg)], dtype=object)

    in_scope = np.flatnonzero(keep)
    unique_keys, inverse = np.unique(keys[in_scope], return_inverse=True)

    segment_of_node = np.full(graph.n_nodes, -1, dtype="int64")
    segment_of_node[in_scope] = inverse

    traversals = required_traversals(index)
    weight = np.zeros(len(unique_keys), dtype="float64")
    np.add.at(weight, inverse, capture_s[in_scope] * traversals[in_scope])

    # Length is per physical piece, so it is taken once rather than summed over
    # the one or two arcs that share it.
    seg_length = np.zeros(len(unique_keys), dtype="float64")
    seg_length[inverse] = length_m[in_scope]

    nodes_of_segment: list[list[int]] = [[] for _ in unique_keys]
    for node in in_scope:
        nodes_of_segment[segment_of_node[node]].append(int(node))

    pairs: dict[tuple[int, int], int] = {}
    for a, row in enumerate(graph.adjacency):
        sa = segment_of_node[a]
        if sa < 0:
            continue
        for b in row:
            sb = segment_of_node[b]
            if sb < 0 or sb == sa:
                continue
            key = (sa, sb) if sa < sb else (sb, sa)
            pairs[key] = pairs.get(key, 0) + 1

    degree = np.zeros(len(unique_keys) + 1, dtype="int64")
    for a, b in pairs:
        degree[a + 1] += 1
        degree[b + 1] += 1
    xadj = np.cumsum(degree)
    adjncy = np.zeros(xadj[-1], dtype="int64")
    eweights = np.zeros(xadj[-1], dtype="int64")
    cursor = xadj[:-1].copy()
    for (a, b), count in sorted(pairs.items()):
        adjncy[cursor[a]] = b
        eweights[cursor[a]] = count
        cursor[a] += 1
        adjncy[cursor[b]] = a
        eweights[cursor[b]] = count
        cursor[b] += 1

    return ZoneGraph(
        segment_id=unique_keys,
        weight_s=weight,
        xadj=xadj,
        adjncy=adjncy,
        eweights=eweights,
        segment_of_node=segment_of_node,
        nodes_of_segment=[np.asarray(v, dtype="int64") for v in nodes_of_segment],
        length_m=seg_length,
    )


def partition(zones: ZoneGraph, n_parts: int, tpwgts=None, seed: int | None = None) -> np.ndarray:
    """METIS, seeded, with contiguous parts required.

    Vertex weights are integer seconds of capture time; METIS needs integers and
    a second is four orders of magnitude below a shift.
    """
    import pymetis

    if n_parts < 1:
        raise ValueError("a partition needs at least one part")
    if n_parts == 1:
        return np.zeros(zones.n_segments, dtype="int64")

    options = pymetis.Options()
    options.seed = C.METIS_SEED if seed is None else seed
    options.contig = True

    weights = np.maximum(np.rint(zones.weight_s).astype("int64"), 1)
    result = pymetis.part_graph(
        n_parts,
        adjacency=pymetis.CSRAdjacency(zones.xadj, zones.adjncy),
        vweights=weights,
        eweights=zones.eweights,
        tpwgts=None if tpwgts is None else list(tpwgts),
        options=options,
    )
    return np.asarray(result.vertex_part, dtype="int64")


def components_of(zones: ZoneGraph, members: np.ndarray) -> list[np.ndarray]:
    """Connected components of a set of segments, within the zone graph."""
    member_set = set(members.tolist())
    seen: set[int] = set()
    out = []
    for start in members.tolist():
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component = []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbour in zones.neighbours(node).tolist():
                if neighbour in member_set and neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        out.append(np.asarray(sorted(component), dtype="int64"))
    return sorted(out, key=len, reverse=True)


def disconnected_zones(zones: ZoneGraph, labels: np.ndarray) -> dict[int, int]:
    """Zone id → component count, for every zone that is in more than one piece."""
    out = {}
    for zone in np.unique(labels):
        members = np.flatnonzero(labels == zone)
        pieces = components_of(zones, members)
        if len(pieces) > 1:
            out[int(zone)] = len(pieces)
    return out


def repair_connectivity(zones: ZoneGraph, labels: np.ndarray) -> tuple[np.ndarray, int]:
    """Reattach any stranded fragment to the neighbouring zone it touches most.

    METIS with `contig` should not produce these, but "should not" is not an
    invariant.  The repair moves work between zones, so the balance pass runs
    after it, never before.
    """
    labels = labels.copy()
    moved = 0
    for zone, _count in sorted(disconnected_zones(zones, labels).items()):
        members = np.flatnonzero(labels == zone)
        pieces = components_of(zones, members)
        for fragment in pieces[1:]:
            counts: dict[int, int] = {}
            for segment in fragment.tolist():
                for neighbour in zones.neighbours(segment).tolist():
                    other = int(labels[neighbour])
                    if other != zone:
                        counts[other] = counts.get(other, 0) + 1
            if not counts:
                continue
            target = max(sorted(counts.items()), key=lambda kv: kv[1])[0]
            labels[fragment] = target
            moved += len(fragment)
    return labels, moved


def is_connected(zones: ZoneGraph, members: np.ndarray) -> bool:
    """Whether a set of segments forms one connected piece of the zone graph."""
    if len(members) <= 1:
        return True
    member_set = set(members.tolist())
    stack = [int(members[0])]
    seen = {int(members[0])}
    while stack:
        node = stack.pop()
        for neighbour in zones.neighbours(node).tolist():
            if neighbour in member_set and neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return len(seen) == len(member_set)


def articulation_points(zones: ZoneGraph, members: np.ndarray) -> set[int]:
    """Segments whose removal would split their zone.

    The balance pass may move any boundary segment except these; moving one would
    leave a day in two pieces, which is the thing `contig` was asked to prevent.
    Iterative Tarjan — the recursive form overflows on a zone of a few thousand.
    """
    member_set = set(members.tolist())
    discovery: dict[int, int] = {}
    low: dict[int, int] = {}
    parent: dict[int, int] = {}
    points: set[int] = set()
    timer = 0

    for root in members.tolist():
        if root in discovery:
            continue
        stack = [(root, iter(zones.neighbours(root).tolist()))]
        discovery[root] = low[root] = timer
        timer += 1
        root_children = 0

        while stack:
            node, iterator = stack[-1]
            advanced = False
            for neighbour in iterator:
                if neighbour not in member_set:
                    continue
                if neighbour not in discovery:
                    parent[neighbour] = node
                    discovery[neighbour] = low[neighbour] = timer
                    timer += 1
                    if node == root:
                        root_children += 1
                    stack.append((neighbour, iter(zones.neighbours(neighbour).tolist())))
                    advanced = True
                    break
                if neighbour != parent.get(node):
                    low[node] = min(low[node], discovery[neighbour])
            if not advanced:
                stack.pop()
                if stack:
                    up = stack[-1][0]
                    low[up] = min(low[up], low[node])
                    if up != root and low[node] >= discovery[up]:
                        points.add(up)
        if root_children > 1:
            points.add(root)
    return points


def zone_table(zones: ZoneGraph, labels: np.ndarray) -> pd.DataFrame:
    """Per-zone capture seconds, segment count and centreline km."""
    frame = pd.DataFrame(
        {
            "zone": labels,
            "weight_s": zones.weight_s,
            "length_m": zones.length_m,
        }
    )
    grouped = frame.groupby("zone", sort=True).agg(
        segments=("weight_s", "size"),
        capture_s=("weight_s", "sum"),
        centerline_km=("length_m", lambda s: float(s.sum() / 1000.0)),
    )
    return grouped.reset_index()


#: Moves before a zone's articulation points are recomputed during rebalancing.
#: Small enough that the safe set never drifts far, large enough that the pass
#: does not spend all its time in Tarjan.
ARTICULATION_REFRESH = 25


@dataclasses.dataclass(frozen=True)
class Balance:
    """What the rebalancing pass did, and what it left."""

    labels: np.ndarray
    passes: int
    moves: int
    stdev_before_h: float
    stdev_after_h: float
    max_before_h: float
    max_after_h: float

    def to_dict(self) -> dict:
        return {
            "passes": int(self.passes),
            "segments_moved": int(self.moves),
            "day_stdev_before_h": self.stdev_before_h,
            "day_stdev_after_h": self.stdev_after_h,
            "longest_day_before_h": self.max_before_h,
            "longest_day_after_h": self.max_after_h,
        }


def boundary_segments(zones: ZoneGraph, labels: np.ndarray, zone: int) -> dict[int, set[int]]:
    """Segments of `zone` that touch another zone → the zones they touch."""
    out: dict[int, set[int]] = {}
    for segment in np.flatnonzero(labels == zone).tolist():
        others = {
            int(labels[n]) for n in zones.neighbours(segment).tolist() if labels[n] != zone
        }
        if others:
            out[segment] = others
    return out


def zone_durations(
    zones: ZoneGraph,
    labels: np.ndarray,
    zone_ids: np.ndarray,
    leg_out_s: np.ndarray,
    leg_back_s: np.ndarray,
    overhead: float,
    break_hours: float,
    commute_allowance: float = 0.0,
) -> np.ndarray:
    """Hours a day costs: capture × overhead + both depot legs + the break.

    `commute_allowance` reserves a fraction of each zone's leg time on top, so
    that a leg routed through uncovered required arcs (SPEC §7.1 mitigation 1)
    has room to be longer than the plain one it replaces.  It is proportional to
    the leg, so the far zones — the ones with corridors worth capturing and the
    ones sequenced first, while those corridors are still uncovered — reserve the
    most, and the near zones reserve almost nothing.

    The legs are the *cheapest* way in and out of the zone, so they are a minimum
    over its segments — which is why a zone's duration does not fall neatly as
    segments leave it, and why the balance pass has to re-derive this rather than
    track it incrementally.
    """
    slot = np.searchsorted(zone_ids, labels)
    capture = np.zeros(len(zone_ids), dtype="float64")
    np.add.at(capture, slot, zones.weight_s)

    out = np.full(len(zone_ids), np.inf)
    back = np.full(len(zone_ids), np.inf)
    np.minimum.at(out, slot, leg_out_s)
    np.minimum.at(back, slot, leg_back_s)
    legs = np.where(np.isfinite(out), out, 0.0) + np.where(np.isfinite(back), back, 0.0)
    return (
        capture / 3600.0 * overhead
        + legs / 3600.0 * (1.0 + commute_allowance)
        + break_hours
    )


def rebalance(
    zones: ZoneGraph,
    labels: np.ndarray,
    leg_out_s: np.ndarray,
    leg_back_s: np.ndarray,
    overhead: float,
    break_hours: float,
    window_hours: float,
    max_passes: int = 30,
    commute_allowance: float = 0.0,
) -> Balance:
    """Even out **day durations**, not capture weight.

    METIS balances the thing it was given, and a far zone with the same capture
    time is a longer day because two depot legs sit inside the shift (SPEC §5).
    The leg-amortised weights handed to METIS get most of the way; this pass
    finishes it on the quantity that actually has to fit.

    Three rules keep the search honest:

    - a segment never moves if it is an **articulation point** of its zone, so
      connectivity survives by construction rather than by a check afterwards;
    - a move is refused if it would push the receiving zone **over its window**,
      because reducing the spread by creating an overrun is not an improvement;
    - durations are **re-derived**, not tracked incrementally.  A zone's leg is a
      minimum over its segments, so moving its nearest segment away lengthens the
      leg — an earlier version of this pass tracked capture only and made the
      partition worse while reporting that it had improved it.
    """
    labels = labels.copy()
    zone_ids = np.unique(labels)

    def durations(current: np.ndarray) -> np.ndarray:
        return zone_durations(
            zones, current, zone_ids, leg_out_s, leg_back_s, overhead, break_hours,
            commute_allowance,
        )

    initial = durations(labels)
    stdev_before, max_before = float(initial.std()), float(initial.max())
    best_labels = labels.copy()
    best_score = (max_before, stdev_before)

    moves = 0
    completed = 0
    for completed in range(1, max_passes + 1):
        current = durations(labels)
        target = float(current.mean())
        improved = 0

        for slot in np.argsort(-current):
            zone = int(zone_ids[slot])
            if current[slot] <= target:
                break
            members = np.flatnonzero(labels == zone)
            if len(members) <= 1:
                continue
            fixed = articulation_points(zones, members)
            candidates = boundary_segments(zones, labels, zone)
            since_refresh = 0

            for segment, neighbours in sorted(candidates.items()):
                if current[slot] <= target:
                    break
                if labels[segment] != zone or segment in fixed:
                    continue
                delta = zones.weight_s[segment] / 3600.0 * overhead
                if delta <= 0:
                    continue
                best = None
                for other in sorted(neighbours):
                    other_slot = int(np.searchsorted(zone_ids, other))
                    if other_slot >= len(zone_ids) or zone_ids[other_slot] != other:
                        continue
                    if current[other_slot] + delta > window_hours:
                        continue
                    before = _spread(current[slot], current[other_slot], target)
                    after = _spread(current[slot] - delta, current[other_slot] + delta, target)
                    if after < before - 1e-12 and (best is None or after < best[1]):
                        best = (other_slot, after)
                if best is None:
                    continue
                labels[segment] = zone_ids[best[0]]
                # The articulation set is a fast filter, refreshed periodically,
                # so it can be stale by a few moves.  This is the guarantee: if
                # the donor zone came apart, put the segment back.  Without it a
                # stranded fragment survives to the connectivity repair, which
                # reattaches it wholesale and can undo the whole pass.
                if not is_connected(zones, np.flatnonzero(labels == zone)):
                    labels[segment] = zone
                    fixed.add(segment)
                    continue
                current[slot] -= delta
                current[best[0]] += delta
                improved += 1
                moves += 1
                since_refresh += 1
                if since_refresh >= ARTICULATION_REFRESH:
                    current = durations(labels)
                    fixed = articulation_points(zones, np.flatnonzero(labels == zone))
                    since_refresh = 0

        exact = durations(labels)
        score = (float(exact.max()), float(exact.std()))
        if score < best_score:
            best_score = score
            best_labels = labels.copy()
        if improved == 0:
            break

    final = durations(best_labels)
    return Balance(
        labels=best_labels,
        passes=completed,
        moves=moves,
        stdev_before_h=stdev_before,
        stdev_after_h=float(final.std()),
        max_before_h=max_before,
        max_after_h=float(final.max()),
    )


def _spread(a: float, b: float, target: float) -> float:
    """Squared deviation of two durations from the mean — the objective, locally."""
    return (a - target) ** 2 + (b - target) ** 2


# ------------------------------------------------------------------ the plan


@dataclasses.dataclass(frozen=True)
class ZonePlan:
    """A partition that fits, and what it took to find it."""

    labels: np.ndarray
    n_zones: int
    durations_h: np.ndarray
    weighting: str
    balance: Balance
    attempts: int
    feasible: bool

    def to_dict(self) -> dict:
        return {
            "n_zones": int(self.n_zones),
            "weighting": self.weighting,
            "attempts": int(self.attempts),
            "feasible": bool(self.feasible),
            "day_hours_min": float(self.durations_h.min()),
            "day_hours_max": float(self.durations_h.max()),
            "day_hours_mean": float(self.durations_h.mean()),
            "day_hours_stdev": float(self.durations_h.std()),
            "total_hours": float(self.durations_h.sum()),
            "balance": self.balance.to_dict(),
        }


def _amortised_weights(
    zones: ZoneGraph, leg_s: np.ndarray, overhead: float, mean_capture_s: float
) -> np.ndarray:
    """Capture weight plus each segment's share of the leg its zone will pay.

    SPEC §7.1 mitigation 3 — "zone sizing on net productive time" — expressed in
    the only language METIS speaks.  A segment far from the depot costs its zone
    more than its capture time alone, so it carries more weight and the zone ends
    up with less work in it.  The alternative, balancing capture and fixing it
    afterwards, moves a quarter of a million seconds one segment at a time.
    """
    return zones.weight_s * overhead + leg_s * zones.weight_s / max(mean_capture_s, 1.0)


def _zone_leg_s(
    zones: ZoneGraph, labels: np.ndarray, leg_out_s: np.ndarray, leg_back_s: np.ndarray
):
    ids = np.unique(labels)
    slot = np.searchsorted(ids, labels)
    out = np.full(len(ids), np.inf)
    back = np.full(len(ids), np.inf)
    np.minimum.at(out, slot, leg_out_s)
    np.minimum.at(back, slot, leg_back_s)
    legs = np.where(np.isfinite(out), out, 0.0) + np.where(np.isfinite(back), back, 0.0)
    capture = np.zeros(len(ids))
    np.add.at(capture, slot, zones.weight_s)
    return ids, slot, legs, capture


def solve_zones(
    zones: ZoneGraph,
    n_parts: int,
    leg_out_s: np.ndarray,
    leg_back_s: np.ndarray,
    overhead: float,
    break_hours: float,
    window_hours: float,
    fixed_point_rounds: int = 3,
    commute_allowance: float = C.COMMUTE_ALLOWANCE,
) -> ZonePlan:
    """Partition into `n_parts`, trying more than one weighting and keeping the best.

    METIS is not monotone in the number of parts and is sensitive to the weights
    it is handed, so a single attempt is a coin toss.  Three are tried — capture
    only, leg-amortised, and leg-amortised iterated to a fixed point — and the one
    with the shortest longest day wins.  Ties break on the standard deviation,
    which is what the gate measures.
    """
    leg_s = np.where(np.isfinite(leg_out_s), leg_out_s, 0.0) + np.where(
        np.isfinite(leg_back_s), leg_back_s, 0.0
    )
    mean_capture = zones.total_weight_s / max(n_parts, 1)

    candidates: list[tuple[str, np.ndarray, int]] = [
        ("capture", zones.weight_s * overhead, C.METIS_SEED),
        ("leg_amortised", _amortised_weights(zones, leg_s, overhead, mean_capture), C.METIS_SEED),
    ]

    weights = candidates[-1][1]
    for _round in range(fixed_point_rounds):
        labels = partition(
            dataclasses.replace(zones, weight_s=np.maximum(weights, 1e-6)), n_parts
        )
        labels, _ = repair_connectivity(zones, labels)
        _ids, slot, legs, capture = _zone_leg_s(zones, labels, leg_out_s, leg_back_s)
        weights = zones.weight_s * overhead + legs[slot] * zones.weight_s / np.maximum(
            capture[slot], 1.0
        )
    # METIS is chaotic in its inputs: a millisecond of difference in a leg time
    # can flip the partition and move the day spread by half an hour.  Extra
    # seeds on the best weighting cost a tenth of a second each and take most of
    # that variance out of the answer.
    for offset, seed in enumerate(C.METIS_SEEDS):
        candidates.append((f"leg_fixed_point/{offset}" if offset else "leg_fixed_point",
                           weights, seed))

    best: ZonePlan | None = None
    for name, weight, seed in candidates:
        labels = partition(
            dataclasses.replace(zones, weight_s=np.maximum(weight, 1e-6)), n_parts, seed=seed
        )
        labels, _ = repair_connectivity(zones, labels)
        balance = rebalance(
            zones, labels, leg_out_s, leg_back_s, overhead, break_hours, window_hours,
            commute_allowance=commute_allowance,
        )
        labels, _ = repair_connectivity(zones, balance.labels)
        ids = np.unique(labels)
        durations = zone_durations(
            zones, labels, ids, leg_out_s, leg_back_s, overhead, break_hours,
            commute_allowance,
        )
        plan = ZonePlan(
            labels=labels,
            n_zones=len(ids),
            durations_h=durations,
            weighting=name,
            balance=balance,
            attempts=len(candidates),
            feasible=bool(durations.max() <= window_hours)
            and not disconnected_zones(zones, labels),
        )
        if best is None or _rank(plan, window_hours) < _rank(best, window_hours):
            best = plan
    return best


def _rank(plan: ZonePlan, window_hours: float) -> tuple:
    """Infeasible plans lose; among feasible ones the flattest day profile wins.

    Ranking on the longest day alone was the earlier form, and it picked plans
    that squeaked under the window with one four-hour day and one nine-hour one.
    The gate measures the spread, so the search optimises the spread.
    """
    overrun = max(0.0, float(plan.durations_h.max()) - window_hours)
    return (overrun > 1e-9, round(overrun, 6), float(plan.durations_h.std()))


def choose_zone_count(
    zones: ZoneGraph,
    leg_out_s: np.ndarray,
    leg_back_s: np.ndarray,
    overhead: float,
    break_hours: float,
    window_hours: float,
    max_iterations: int = C.ZONE_COUNT_MAX_ITERATIONS,
    commute_allowance: float = C.COMMUTE_ALLOWANCE,
    allowances: tuple[float, ...] | None = None,
) -> ZonePlan:
    """The fewest zones that all fit their window.

    Starts from the arithmetic floor — total work over the window — and walks up.
    Each day is a day, so one zone too many is a day of driving wasted; the search
    stops at the first count that fits rather than at the best-balanced one.
    """
    floor = int(np.ceil(zones.total_weight_s / 3600.0 * overhead / max(window_hours - break_hours, 0.1)))
    # Whether to let the search buy a day back by reserving no commute room.
    # Stage 4b measured the trade and it goes the other way — reserving the room
    # drives fewer hours, which is SPEC §4's KPI — so by default the search
    # commits to the allowance.  `ZONE_PREFER_FEWEST_DAYS` restores the old
    # behaviour for anyone who needs the shortest calendar instead.
    if allowances is None:
        allowances = (
            sorted({float(commute_allowance), 0.0}, reverse=True)
            if C.ZONE_PREFER_FEWEST_DAYS
            else [float(commute_allowance)]
        )
    else:
        allowances = sorted({float(a) for a in allowances}, reverse=True)
    for step in range(max_iterations):
        candidates = [
            solve_zones(
                zones, floor + step, leg_out_s, leg_back_s, overhead, break_hours,
                window_hours, commute_allowance=allowance,
            )
            for allowance in allowances
        ]
        feasible = [plan for plan in candidates if plan.feasible]
        if feasible:
            best = min(feasible, key=lambda plan: _rank(plan, window_hours))
            return dataclasses.replace(best, attempts=step + 1)
    raise RuntimeError(
        f"no zone count between {floor} and {floor + max_iterations} fits a "
        f"{window_hours:.2f} h window"
    )


def split_zone(
    zones: ZoneGraph, labels: np.ndarray, zone: int, new_label: int
) -> tuple[np.ndarray, bool]:
    """Cut one zone in two, both halves connected.

    Stage 5's repair for a day that will not fit its window.  Shrinking every zone
    to accommodate one awkward one costs a day per zone; splitting the offender
    costs exactly one day.  Returns the labels unchanged, and False, when the zone
    is a single segment and cannot be cut.
    """
    members = np.flatnonzero(labels == zone)
    if len(members) < 2:
        return labels, False

    position = {segment: i for i, segment in enumerate(members.tolist())}
    degree = np.zeros(len(members) + 1, dtype="int64")
    pairs: list[tuple[int, int]] = []
    for segment in members.tolist():
        for neighbour in zones.neighbours(segment).tolist():
            if neighbour in position and neighbour > segment:
                pairs.append((position[segment], position[neighbour]))
    for a, b in pairs:
        degree[a + 1] += 1
        degree[b + 1] += 1
    xadj = np.cumsum(degree)
    adjncy = np.zeros(max(xadj[-1], 1), dtype="int64")
    cursor = xadj[:-1].copy()
    for a, b in sorted(pairs):
        adjncy[cursor[a]] = b
        cursor[a] += 1
        adjncy[cursor[b]] = a
        cursor[b] += 1

    sub = ZoneGraph(
        segment_id=zones.segment_id[members],
        weight_s=zones.weight_s[members],
        xadj=xadj,
        adjncy=adjncy,
        eweights=np.ones(len(adjncy), dtype="int64"),
        segment_of_node=np.array([], dtype="int64"),
        nodes_of_segment=[],
        length_m=zones.length_m[members],
    )
    halves = partition(sub, 2)
    halves, _ = repair_connectivity(sub, halves)
    if len(np.unique(halves)) < 2:
        return labels, False

    out = labels.copy()
    out[members[halves == 1]] = new_label
    return out, True
