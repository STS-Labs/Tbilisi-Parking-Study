"""Stage 6 item 1 — direction-aware map matching onto *our* arcs.

Why not Valhalla Meili or `fmm`, which SPEC §10.2 names: both match onto a graph
they build themselves from the PBF, with their own splitting and simplification.
Coverage in this project is defined on `arc_id`, so using either means joining
their edge ids back to our arc table — and that join is precisely where a street
gets marked covered because something *near* it was driven. The brief's stated
failure mode is a lenient matcher, so the join is removed rather than tuned:
matching happens against the arcs the coverage requirement is written in.

Matching against our own network also buys information a general matcher cannot
have. Transitions are restricted to arcs that actually meet at a node, and where a
turn graph is supplied, to manoeuvres `L(G)` permits — so a match cannot hop across
a central reservation or through a banned turn to find a better fit.

The model is the standard HMM: emission from perpendicular distance, transition
from the disagreement between how far the network says the car went and how far the
fixes say it went, decoded with Viterbi. Every tie is broken on arc index, so the
same trace always decodes the same way (CLAUDE.md rule 5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import config as C

#: Log-probability floor for a transition between arcs that do not meet. Not -inf:
#: a trace with a gap (a tunnel, a dropped fix) must still decode, just never in
#: preference to a connected path.
DISCONNECTED_PENALTY = -50.0

#: How far along the arc to sample either side of a matched position when taking its
#: local bearing. Long enough to be stable against vertex noise, short enough to
#: still follow a curve.
BEARING_SAMPLE_M = 10.0


@dataclass(frozen=True)
class Run:
    """A maximal stretch of consecutive fixes decoded onto one arc."""

    arc_id: str
    arc_index: int
    first_fix: int
    last_fix: int
    #: Share of the arc's length the run actually spans, by linear reference.
    fraction: float
    #: True when the fix before this run sat on an arc feeding into this one, and
    #: the fix after sat on an arc this one feeds. That is a traversal end to end,
    #: whatever the geometric fraction says.
    through: bool
    max_speed_kmh: float
    mean_speed_kmh: float
    #: Speed at `config.COVERAGE_SPEED_QUANTILE` — the figure the limit is tested on.
    speed_quantile_kmh: float
    max_heading_delta_deg: float
    mean_distance_m: float
    #: Seconds between the first and last fix of the run.
    duration_s: float


@dataclass(frozen=True)
class Pass:
    """One end-to-end traversal of an arc, assembled from the runs that made it.

    A traversal is not the same thing as a run. Two things break a single drive down
    a street into several runs: the decoder briefly preferring a neighbouring arc,
    and — on the paired arcs of a narrow street — the heading crossing the tolerance
    on a switchback. Judging each fragment on its own then rejects a street that was
    driven end to end, which is the *opposite* of the error this stage guards
    against but just as wrong: it sends the car back to a street already filmed.

    Fragments are merged into one pass while they extend the covered stretch, and a
    fragment that re-covers ground the pass already holds starts a new pass instead,
    because that is a second drive down the same street.
    """

    arc_id: str
    arc_index: int
    first_fix: int
    last_fix: int
    fraction: float
    through: bool
    #: True when no fix landed on this arc and it was inferred from its neighbours.
    inferred: bool
    max_speed_kmh: float
    speed_quantile_kmh: float
    max_heading_delta_deg: float


@dataclass(frozen=True)
class MatchResult:
    runs: list[Run]
    #: Runs assembled into end-to-end traversals. This is what coverage judges.
    passes: list[Pass]
    #: Arcs the car demonstrably drove the *wrong way* down: close enough to match
    #: on distance, rejected on heading. Not coverage — but the driver needs telling,
    #: and a silent non-match looks identical to never having been there.
    wrong_way: list[Run]
    #: Per fix: index into the arc frame, or -1 where nothing was close enough.
    matched: np.ndarray
    distance_m: np.ndarray
    heading_delta_deg: np.ndarray

    @property
    def unmatched_fixes(self) -> int:
        return int((self.matched < 0).sum())


def _heading_delta(a: np.ndarray | float, b: np.ndarray | float):
    """Smallest angle between two compass bearings, in [0, 180]."""
    return np.abs((np.asarray(a) - np.asarray(b) + 180.0) % 360.0 - 180.0)


def _local_bearing(line, position_m: float) -> float:
    """Compass bearing of the arc at a point along it, from projected coordinates.

    Grid north in UTM 38N differs from true north by about 0.13° over Tbilisi,
    which is three orders of magnitude below the heading tolerance.
    """
    half = BEARING_SAMPLE_M / 2.0
    back = line.interpolate(max(0.0, position_m - half))
    ahead = line.interpolate(min(line.length, position_m + half))
    dx, dy = ahead.x - back.x, ahead.y - back.y
    if dx == 0.0 and dy == 0.0:
        return 0.0
    return math.degrees(math.atan2(dx, dy)) % 360.0


def match(
    trace,
    arcs,
    *,
    tolerance_deg: float | None = None,
    max_distance_m: float | None = None,
    sigma_m: float | None = None,
    beta_m: float | None = None,
    legal_transition=None,
) -> MatchResult:
    """Decode `trace` onto `arcs`.

    `legal_transition(from_arc_index, to_arc_index) -> bool` optionally narrows
    node-connected transitions to the ones `L(G)` permits. Without it, matching
    respects geometry and direction but not turn restrictions.
    """
    import geopandas as gpd
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    tolerance_deg = C.MATCH_HEADING_TOLERANCE_DEG if tolerance_deg is None else tolerance_deg
    max_distance_m = C.MATCH_MAX_CANDIDATE_DIST_M if max_distance_m is None else max_distance_m
    sigma_m = C.MATCH_GPS_SIGMA_M if sigma_m is None else sigma_m
    beta_m = C.MATCH_TRANSITION_BETA_M if beta_m is None else beta_m

    metric = arcs.to_crs(C.METRIC_CRS)
    lines = list(metric.geometry)
    tree = STRtree(lines)
    from_node = arcs["from_node"].to_numpy()
    to_node = arcs["to_node"].to_numpy()
    arc_ids = arcs["arc_id"].astype(str).to_numpy()

    fixes = gpd.GeoSeries(
        [Point(x, y) for x, y in zip(trace.lon, trace.lat)], crs="EPSG:4326"
    ).to_crs(C.METRIC_CRS)

    n = len(trace)
    # Per fix: the candidate arcs that survive distance *and* heading.
    candidates: list[list[tuple[int, float, float, float]]] = []
    near_miss: list[list[tuple[int, float, float, float]]] = []
    for i, point in enumerate(fixes):
        found, missed = [], []
        for index in sorted(tree.query(point.buffer(max_distance_m))):
            line = lines[index]
            distance = line.distance(point)
            if distance > max_distance_m:
                continue
            position = line.project(point)
            delta = float(_heading_delta(_local_bearing(line, position),
                                         trace.heading_deg[i]))
            entry = (int(index), float(distance), float(position), delta)
            if delta > tolerance_deg:
                missed.append(entry)  # wrong way down this arc — SPEC §10.3
            else:
                found.append(entry)
        candidates.append(found)
        near_miss.append(missed)

    matched = np.full(n, -1, dtype="int64")
    distance_out = np.full(n, np.nan)
    delta_out = np.full(n, np.nan)
    position_out = np.full(n, np.nan)

    # --- Viterbi over the candidate lattice -------------------------------------
    # Decoded in contiguous blocks of fixes that *have* candidates. A fix with none
    # — a tunnel, a dropped fix, a stretch of road not in scope — ends the block and
    # the next one starts fresh. Decoding the whole trace as a single chain would
    # mean one gap truncating everything before it, which is not a conservative
    # failure: it silently reports a street as never driven.
    blocks: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if not candidates[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and candidates[j + 1]:
            j += 1
        blocks.append((i, j))
        i = j + 1

    def gps_step(i: int) -> float:
        if i <= 0:
            return 0.0
        return float(np.hypot(fixes.iloc[i].x - fixes.iloc[i - 1].x,
                              fixes.iloc[i].y - fixes.iloc[i - 1].y))

    for first, last in blocks:
        scores: dict[int, float] = {}
        back: list[dict[int, int]] = []
        for i in range(first, last + 1):
            step_scores: dict[int, float] = {}
            step_back: dict[int, int] = {}
            step = gps_step(i)
            for index, distance, position, delta in candidates[i]:
                emission = -0.5 * (distance / sigma_m) ** 2
                if not scores:
                    step_scores[index] = emission
                    step_back[index] = -1
                    continue
                best_score, best_from = None, -1
                for prev_index, prev_score in sorted(scores.items()):
                    if prev_index == index:
                        transition = 0.0
                    elif to_node[prev_index] == from_node[index] and (
                        legal_transition is None or legal_transition(prev_index, index)
                    ):
                        transition = -abs(step - min(step, lines[index].length)) / beta_m
                    else:
                        transition = DISCONNECTED_PENALTY
                    total = prev_score + transition
                    if best_score is None or total > best_score:
                        best_score, best_from = total, prev_index
                step_scores[index] = emission + best_score
                step_back[index] = best_from
            scores = step_scores
            back.append(step_back)

        # Backtrace this block. Ties break on the lower arc index so the same trace
        # always decodes the same way (CLAUDE.md rule 5).
        state = max(sorted(scores), key=lambda k: (scores[k], -k))
        for offset in range(len(back) - 1, -1, -1):
            i = first + offset
            matched[i] = state
            for index, distance, position, delta in candidates[i]:
                if index == state:
                    distance_out[i] = distance
                    position_out[i] = position
                    delta_out[i] = delta
                    break
            state = back[offset].get(state, -1)
            if state < 0 and offset > 0:
                # Should not happen inside a block, but never guess a state.
                break

    runs = _runs(trace, matched, distance_out, delta_out, position_out, lines, arc_ids,
                 from_node, to_node)
    passes = _passes(runs, position_out, lines, arc_ids, from_node, to_node, trace)

    # Wrong-way stretches: for each fix with nothing legal, the nearest arc that
    # failed only on heading. Collapsed the same way, so a single stray fix beside
    # an oncoming carriageway does not become a "you drove the wrong way" report.
    wrong = np.full(n, -1, dtype="int64")
    w_dist = np.full(n, np.nan)
    w_delta = np.full(n, np.nan)
    w_pos = np.full(n, np.nan)
    for i, missed in enumerate(near_miss):
        if matched[i] >= 0 or not missed:
            continue
        index, distance, position, delta = min(missed, key=lambda e: (e[1], e[0]))
        wrong[i], w_dist[i], w_pos[i], w_delta[i] = index, distance, position, delta
    wrong_way = _runs(trace, wrong, w_dist, w_delta, w_pos, lines, arc_ids)

    return MatchResult(runs=runs, passes=passes, wrong_way=wrong_way, matched=matched,
                       distance_m=distance_out, heading_delta_deg=delta_out)


def _runs(trace, matched, distance, delta, position, lines, arc_ids,
          from_node=None, to_node=None) -> list[Run]:
    """Collapse the decoded per-fix arcs into maximal same-arc stretches.

    Two things decide whether a stretch is a *traversal*. The geometric fraction is
    the obvious one and it is unreliable on short arcs: at 25 km/h and 1 Hz the
    fixes are 7 m apart, so on a 20 m arc the first fix is already inside it and the
    last stops short, and a genuine end-to-end drive scores 0.7 by arithmetic alone.
    The topological test is exact — if the car came from an arc that feeds this one
    and left onto an arc this one feeds, it went the whole way down it, and no
    amount of fix spacing changes that.
    """
    runs: list[Run] = []
    start = 0
    n = len(matched)
    while start < n:
        arc = matched[start]
        if arc < 0:
            start += 1
            continue
        stop = start
        while stop + 1 < n and matched[stop + 1] == arc:
            stop += 1
        span = slice(start, stop + 1)
        through = False
        if from_node is not None and start > 0 and stop + 1 < n:
            before, after = matched[start - 1], matched[stop + 1]
            through = (
                before >= 0 and after >= 0
                and to_node[before] == from_node[arc]
                and from_node[after] == to_node[arc]
            )
        seen = position[span]
        seen = seen[~np.isnan(seen)]
        length = lines[arc].length
        # The share of the arc the run spans. A single fix spans nothing, which is
        # correct: one fix near an arc is not a traversal of it.
        fraction = float((seen.max() - seen.min()) / length) if len(seen) > 1 and length else 0.0
        runs.append(
            Run(
                arc_id=str(arc_ids[arc]),
                arc_index=int(arc),
                first_fix=start,
                last_fix=stop,
                fraction=min(fraction, 1.0),
                through=bool(through),
                max_speed_kmh=float(np.nanmax(trace.speed_kmh[span])),
                mean_speed_kmh=float(np.nanmean(trace.speed_kmh[span])),
                speed_quantile_kmh=float(
                    np.nanquantile(trace.speed_kmh[span], C.COVERAGE_SPEED_QUANTILE)
                ),
                max_heading_delta_deg=float(np.nanmax(delta[span])) if not np.isnan(delta[span]).all() else float("nan"),
                mean_distance_m=float(np.nanmean(distance[span])) if not np.isnan(distance[span]).all() else float("nan"),
                duration_s=float(trace.t[stop] - trace.t[start]),
            )
        )
        start = stop + 1
    return runs


#: Longest arc that may be credited without a single fix of its own. An arc shorter
#: than the gap between fixes can be driven straight through without ever being the
#: nearest thing to one — at 25 km/h and 1 Hz the fixes are 7 m apart, and Tbilisi's
#: junction stubs are routinely 4 m. Bounded hard, and only ever taken when the
#: connecting path is unique, because inventing coverage is the failure that matters.
MAX_INFERRED_ARC_M = 25.0


def _interval(run, position) -> tuple[float, float]:
    seen = position[run.first_fix : run.last_fix + 1]
    seen = seen[~np.isnan(seen)]
    if not len(seen):
        return (0.0, 0.0)
    return (float(seen.min()), float(seen.max()))


def _passes(runs, position, lines, arc_ids, from_node, to_node, trace) -> list["Pass"]:
    """Assemble runs into traversals, and infer arcs that were driven through.

    Ordering is by first fix throughout, so the result is a function of the decoded
    path alone and does not depend on dict iteration order (CLAUDE.md rule 5).
    """
    open_pass: dict[int, dict] = {}
    built: list[dict] = []

    for run in runs:
        lo, hi = _interval(run, position)
        current = open_pass.get(run.arc_index)
        span = hi - lo
        if current is not None:
            c_lo, c_hi = current["lo"], current["hi"]
            overlap = max(0.0, min(hi, c_hi) - max(lo, c_lo))
            # Re-covering ground this pass already holds is a second drive down the
            # street, not a continuation of the first.
            if span > 0 and overlap > 0.5 * span:
                built.append(current)
                current = None
        if current is None:
            current = {"arc_index": run.arc_index, "arc_id": run.arc_id,
                       "first_fix": run.first_fix, "last_fix": run.last_fix,
                       "lo": lo, "hi": hi, "through": run.through, "runs": [run]}
            open_pass[run.arc_index] = current
        else:
            current["lo"] = min(current["lo"], lo)
            current["hi"] = max(current["hi"], hi)
            current["last_fix"] = run.last_fix
            current["through"] = current["through"] or run.through
            current["runs"].append(run)
    built.extend(open_pass.values())

    # Arcs driven straight through without collecting a fix of their own.
    inferred = _infer_skipped(runs, lines, arc_ids, from_node, to_node)

    out: list[Pass] = []
    for entry in built:
        length = lines[entry["arc_index"]].length
        fraction = (entry["hi"] - entry["lo"]) / length if length else 0.0
        speeds = np.concatenate([
            trace.speed_kmh[r.first_fix : r.last_fix + 1] for r in entry["runs"]
        ])
        deltas = [r.max_heading_delta_deg for r in entry["runs"]
                  if not math.isnan(r.max_heading_delta_deg)]
        out.append(Pass(
            arc_id=entry["arc_id"], arc_index=entry["arc_index"],
            first_fix=entry["first_fix"], last_fix=entry["last_fix"],
            fraction=min(fraction, 1.0), through=entry["through"], inferred=False,
            max_speed_kmh=float(np.nanmax(speeds)),
            speed_quantile_kmh=float(np.nanquantile(speeds, C.COVERAGE_SPEED_QUANTILE)),
            max_heading_delta_deg=max(deltas) if deltas else float("nan"),
        ))
    out.extend(inferred)
    out.sort(key=lambda p: (p.first_fix, p.arc_id))
    return out


#: Longest chain of unmatched arcs that may be inferred between two matched ones.
#:
#: One is not enough. Streets are split at every junction, so a short link is
#: routinely two or three arcs of the same way — Zone B has a 12.0 m arc followed by
#: a 2.6 m one, together shorter than the gap between two GPS fixes, and bridging
#: only single arcs left both uncovered for ever. The safety property is not the
#: length of the chain but its **uniqueness**.
MAX_INFERRED_CHAIN = 3


def _infer_skipped(runs, lines, arc_ids, from_node, to_node) -> list["Pass"]:
    """Credit short arcs the car must have crossed between two matched ones.

    Only when the connecting path is the *unique* legal way from one to the other,
    every arc on it is shorter than `MAX_INFERRED_ARC_M`, and it is no longer than
    `MAX_INFERRED_CHAIN`. Uniqueness is what keeps this honest: if two routes could
    have joined those arcs, which one was driven is unknown, and an unknown leaves
    the street required. Inventing coverage is the one failure this stage exists to
    prevent, so the search stops the moment a second path appears.
    """
    outgoing: dict[int, list[int]] = {}
    for index in range(len(arc_ids)):
        outgoing.setdefault(int(from_node[index]), []).append(index)

    def unique_path(start_node: int, end_node: int) -> list[int] | None:
        """The one short path from node to node, or None if there is not exactly one."""
        found: list[list[int]] = []
        stack = [(start_node, [])]
        while stack:
            node, path = stack.pop()
            if len(path) >= MAX_INFERRED_CHAIN:
                continue
            for index in outgoing.get(node, []):
                if index in path or lines[index].length > MAX_INFERRED_ARC_M:
                    continue
                step = path + [index]
                if to_node[index] == end_node:
                    found.append(step)
                    if len(found) > 1:
                        return None   # ambiguous; stop looking
                else:
                    stack.append((int(to_node[index]), step))
        return found[0] if len(found) == 1 else None

    inferred: list[Pass] = []
    for before, after in zip(runs, runs[1:]):
        a, b = before.arc_index, after.arc_index
        if to_node[a] == from_node[b]:
            continue  # they already meet; nothing was skipped
        path = unique_path(int(to_node[a]), int(from_node[b]))
        if not path:
            continue
        for index in path:
            inferred.append(Pass(
                arc_id=str(arc_ids[index]), arc_index=index,
                first_fix=before.last_fix, last_fix=after.first_fix,
                fraction=1.0, through=True, inferred=True,
                max_speed_kmh=before.max_speed_kmh,
                speed_quantile_kmh=before.speed_quantile_kmh,
                max_heading_delta_deg=0.0,
            ))
    return inferred
