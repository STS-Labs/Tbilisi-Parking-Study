"""Stage 6 item 4 — measurements the model has been guessing at.

Three quantities in the time model were never measured: SPEC §3.3's turn penalties
(still marked **[CONFIRM values]**, and worth 17.4% of all driving), the speed
model's coefficients, and the congestion multipliers. A day's trace contains all
three, so a campaign that is driving anyway pays for the survey it would otherwise
have to run separately.

**Nothing here writes a constant.** Per CLAUDE.md, a calibration constant is pinned
deliberately with a measured justification, never refreshed automatically — a model
that silently retunes itself from yesterday's traffic produces a plan nobody
reviewed and a finish date nobody can reproduce. These functions return
measurements and the deltas against what is assumed; adopting one is a separate,
human act.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import config as C
from .bearings import classify_turn, turn_delta_deg


@dataclass(frozen=True)
class TurnObservation:
    turn_class: str
    excess_s: float
    from_arc: str
    to_arc: str


@dataclass(frozen=True)
class Calibration:
    """What the trace says, beside what the model assumes."""

    turns: dict[str, dict]
    speed: dict | None
    congestion: dict | None
    observations: int

    def turn_deltas(self) -> dict[str, float]:
        return {
            name: stats["measured_s"] - C.TURN_PENALTY_S[name]
            for name, stats in self.turns.items()
            if name in C.TURN_PENALTY_S
        }


def _bearing_of(line, at: str) -> float:
    import math

    coords = list(line.coords)
    if at == "end":
        (x0, y0), (x1, y1) = coords[-2], coords[-1]
    else:
        (x0, y0), (x1, y1) = coords[0], coords[1]
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360.0


#: Radius around a junction over which its cost is measured, in metres.
#:
#: The penalty is not spent *between* two arcs — it is spent slowing down before the
#: corner and getting back up to speed after it, which happens inside both runs. A
#: first attempt measured only the gap between the last fix on one arc and the first
#: on the next, recovered 0.5 s from a synthetic 6 s dwell, and would have reported
#: SPEC §3.3's penalties as near zero.
JUNCTION_WINDOW_M = 20.0


def turn_observations(trace, match, arcs) -> list[TurnObservation]:
    """Time lost at each junction, over and above holding the approach speed.

    Everything within `JUNCTION_WINDOW_M` of the corner is counted: the distance
    actually covered there, against the time it actually took, against the time it
    would have taken at the speed the car held on the way in. A car that does not
    slow yields zero, which is the right answer for driving straight through and the
    reason `straight` acts as a control rather than an assumption.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    metric = arcs.to_crs(C.METRIC_CRS)
    lines = list(metric.geometry)
    fixes = gpd.GeoSeries(
        [Point(x, y) for x, y in zip(trace.lon, trace.lat)], crs="EPSG:4326"
    ).to_crs(C.METRIC_CRS)
    xs = np.array([p.x for p in fixes])
    ys = np.array([p.y for p in fixes])

    found: list[TurnObservation] = []
    for before, after in zip(match.runs, match.runs[1:]):
        incoming = _bearing_of(lines[before.arc_index], "end")
        outgoing = _bearing_of(lines[after.arc_index], "start")
        turn = classify_turn(turn_delta_deg(incoming, outgoing))

        corner = np.array(lines[before.arc_index].coords[-1])
        lo, hi = before.first_fix, after.last_fix
        near = np.flatnonzero(
            np.hypot(xs[lo : hi + 1] - corner[0], ys[lo : hi + 1] - corner[1])
            <= JUNCTION_WINDOW_M
        )
        if near.size < 2:
            continue
        i, j = lo + int(near[0]), lo + int(near[-1])
        elapsed = float(trace.t[j] - trace.t[i])
        travelled = float(
            np.hypot(np.diff(xs[i : j + 1]), np.diff(ys[i : j + 1])).sum()
        )
        # Approach speed, taken from the part of the incoming run outside the window.
        approach = trace.speed_kmh[before.first_fix : i]
        cruise = float(np.nanmedian(approach)) if approach.size else float("nan")
        if not np.isfinite(cruise) or cruise <= 1.0:
            continue
        free_s = travelled / (cruise / 3.6)
        found.append(TurnObservation(turn, max(0.0, elapsed - free_s),
                                     before.arc_id, after.arc_id))
    return found


def turn_coefficients(observations: list[TurnObservation]) -> dict[str, dict]:
    """Aggregate to one number per turn class, with its spread and count.

    Median rather than mean: a single junction held up by a delivery van should not
    move a coefficient that multiplies 115,000 manoeuvres.
    """
    grouped: dict[str, list[float]] = {}
    for entry in observations:
        grouped.setdefault(entry.turn_class, []).append(entry.excess_s)
    out: dict[str, dict] = {}
    for name, values in sorted(grouped.items()):
        array = np.array(values, dtype="float64")
        out[name] = {
            "measured_s": float(np.median(array)),
            "p25_s": float(np.quantile(array, 0.25)),
            "p75_s": float(np.quantile(array, 0.75)),
            "n": int(array.size),
            "assumed_s": C.TURN_PENALTY_S.get(name),
        }
    return out


def speed_observations(trace, match, arcs):
    """Per-arc observed speed, ready for `SpeedModel.fit`.

    Only whole traversals count. A partial run is a fragment of a street whose speed
    says as much about where the matcher lost the car as about the road.
    """
    rows, observed = [], []
    indexed = arcs.set_index(arcs["arc_id"].astype(str))
    for run in match.passes:
        if run.inferred or run.fraction < C.MATCH_MIN_ARC_FRACTION:
            continue
        speed = float(np.nanmedian(trace.speed_kmh[run.first_fix : run.last_fix + 1]))
        if not np.isfinite(speed) or speed <= 0:
            continue
        rows.append(indexed.loc[run.arc_id])
        observed.append(speed)
    if not rows:
        return None, np.array([])
    import pandas as pd

    return pd.DataFrame(rows), np.array(observed, dtype="float64")


def congestion_observations(trace, match, arcs) -> dict:
    """Observed speed against free flow, by highway class and time-of-day band."""
    from .congestion import CongestionModel

    model = CongestionModel.from_config()
    indexed = arcs.set_index(arcs["arc_id"].astype(str))
    buckets: dict[tuple, list[float]] = {}
    for run in match.passes:
        if run.inferred or run.fraction < C.MATCH_MIN_ARC_FRACTION:
            continue
        row = indexed.loc[run.arc_id]
        speed = float(np.nanmedian(trace.speed_kmh[run.first_fix : run.last_fix + 1]))
        if not np.isfinite(speed) or speed <= 0:
            continue
        import datetime as dt

        hour = dt.datetime.fromtimestamp(
            float(trace.t[run.first_fix]), dt.timezone.utc
        ).hour
        band = _band(model, hour)
        buckets.setdefault((str(row["highway_class"]), band), []).append(speed)
    return {
        f"{cls}|{band}": {"median_kmh": float(np.median(v)), "n": len(v)}
        for (cls, band), v in sorted(buckets.items())
    }


def _band(model, hour: float) -> str:
    """Which time-of-day band an hour falls in. `config.CONGESTION_BANDS` is a tuple
    of `(name, start, end)`, and hours outside every band are outside the shift."""
    for name, start, end in getattr(model, "bands", C.CONGESTION_BANDS):
        if start <= hour < end:
            return name
    return "off-shift"


def calibrate(trace, match, arcs, model=None) -> Calibration:
    """Everything the day's trace can say about the model's guesses."""
    observations = turn_observations(trace, match, arcs)
    turns = turn_coefficients(observations)

    speed = None
    frame, observed = speed_observations(trace, match, arcs)
    if model is not None and frame is not None and len(observed) >= 10:
        _, diagnostics = model.fit(frame, observed)
        speed = diagnostics

    return Calibration(turns=turns, speed=speed,
                       congestion=congestion_observations(trace, match, arcs),
                       observations=len(observations))
