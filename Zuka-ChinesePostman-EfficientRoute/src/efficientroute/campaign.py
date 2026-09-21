"""Stage 2 item 3 — hours into days, and days into a campaign.

    productive_hours = 9.0 − 0.75 break − outbound leg − return leg   (SPEC §5)

The depot legs are the interesting term.  SPEC §7.1: the base sits ~8 km WSW of
centre while the city runs east, so an eastern day loses up to two hours of a
nine-hour shift before any street is captured.  Until Stage 4 routes them, legs
are estimated from **straight-line distance bands** around the depot, with the
detour factor and the door-to-door speed both read off SPEC §7.1's own worked
example rather than assumed.

What this stage does **not** estimate is deadhead.  Repositioning between required
arcs is what Stage 3's lower bound is for, and inventing a deadhead ratio here
would put a number in front of the reader that no measurement stands behind.  The
campaign estimate below is therefore a **floor**: the days the capture work alone
consumes.  The report says so in those words, and carries a table of what each
additional 10% of deadhead costs, so the sensitivity is visible without being
asserted.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
from pyproj import Geod

from . import config as C
from . import scenarios
from . import timemodel as TM
from .congestion import CongestionModel
from .speedmodel import SpeedModel

_GEOD = Geod(ellps="WGS84")

#: The class whose peak congestion the depot-leg speed is expressed against —
#: a leg is an arterial run, not a crawl through residential streets.
LEG_CLASS = "primary"

#: Illustrative deadhead ratios for the report's closing table.  **Not** an
#: estimate of Tbilisi's deadhead: Stage 3 produces that.
DEADHEAD_ILLUSTRATION: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3)


# ------------------------------------------------------------------ turn time


def turn_seconds_per_arc(graph) -> tuple[pd.Series, pd.Series]:
    """Mean and minimum cost of *leaving* each arc, in seconds.

    SPEC §3.3 puts the turn penalty on the manoeuvre, not the arc, so without a
    route there is no exact answer — only a range.  The minimum over legal
    successors is a true floor (a tour that always found a straight-on exit);
    the mean is what an unlucky-but-not-pathological route pays.  Both are
    reported and the mean is used, because under-running a shift is a scheduling
    failure and over-running an estimate is not.
    """
    means: dict[str, list[float]] = {}
    mins: dict[str, list[float]] = {}
    for index, (arc_id, _variant) in enumerate(graph.node_ids):
        row = graph.adjacency[index]
        if not row:
            continue
        penalties = [penalty for _code, penalty in row.values()]
        means.setdefault(arc_id, []).append(float(np.mean(penalties)))
        mins.setdefault(arc_id, []).append(float(min(penalties)))

    mean_s = pd.Series({k: float(np.mean(v)) for k, v in means.items()}, dtype="float64")
    min_s = pd.Series({k: float(np.mean(v)) for k, v in mins.items()}, dtype="float64")
    return mean_s, min_s


def attach_turn_time(frame: pd.DataFrame, mean_s: pd.Series, min_s: pd.Series) -> pd.DataFrame:
    """Per-arc turn seconds, with a class-mean stand-in for arcs absent from L.

    An arc missing from L is one Stage 1 could not reach; it still has to be
    driven, so dropping it from the turn account would understate the campaign.
    The count of stand-ins is carried into the report.
    """
    out = frame.copy()
    out["turn_mean_s"] = out["arc_id"].map(mean_s)
    out["turn_min_s"] = out["arc_id"].map(min_s)

    for column in ("turn_mean_s", "turn_min_s"):
        by_class = out.groupby("highway_class")[column].transform("mean")
        out[column] = out[column].fillna(by_class).fillna(out[column].mean()).fillna(0.0)
    return out


# ------------------------------------------------------------- depot geometry


def depot_distance_km(frame: pd.DataFrame) -> np.ndarray:
    """Straight-line distance from the depot to each arc's centroid, km.

    The centroid is taken in the metric CRS and converted back, not taken in
    degrees: a centroid of lon/lat coordinates is not a point on the ground, and
    while the error is centimetres on a 39 m arc it is not on a 2 km one.  The
    distance itself is geodesic, matching `arcs.geodesic_length_m`.
    """
    centroids = frame.geometry.to_crs(C.METRIC_CRS).centroid.to_crs("EPSG:4326")
    lon = centroids.x.to_numpy(dtype="float64")
    lat = centroids.y.to_numpy(dtype="float64")
    _, _, metres = _GEOD.inv(
        np.full(lon.shape, C.DEPOT_LON), np.full(lat.shape, C.DEPOT_LAT), lon, lat
    )
    return metres / 1000.0


def band_labels(edges=C.DEPOT_DISTANCE_BANDS_KM) -> list[str]:
    labels = [f"0–{edges[0]:.0f}"]
    labels += [f"{a:.0f}–{b:.0f}" for a, b in zip(edges, edges[1:])]
    labels.append(f"{edges[-1]:.0f}+")
    return labels


def band_index(distance_km: np.ndarray, edges=C.DEPOT_DISTANCE_BANDS_KM) -> np.ndarray:
    return np.searchsorted(np.asarray(edges, dtype="float64"), distance_km, side="right")


def leg_speed_kmh(congestion: CongestionModel) -> float:
    """Door-to-door depot-leg speed under a given congestion assumption.

    SPEC §7.1's "50–60 min each way in traffic" over ~30 km of driving is a
    *congested* observation, so it is the value this returns at the baseline
    assumption (λ = 1).  Expressing it as free-flow ÷ peak index rather than as a
    constant is what lets the sensitivity sweep move the depot legs too — on
    eastern days the legs are a fifth of the shift, so holding them fixed while
    congestion varies would understate the risk the table exists to show.
    """
    baseline = CongestionModel.from_config().value(LEG_CLASS, "am_peak")
    free_flow = C.DEPOT_LEG_SPEED_KMH * baseline
    return free_flow / congestion.value(LEG_CLASS, "am_peak")


# --------------------------------------------------------------- the estimate


@dataclasses.dataclass(frozen=True)
class DayModel:
    shift_hours: float = C.SHIFT_HOURS
    break_hours: float = C.BREAK_HOURS

    def productive_hours(self, leg_hours: float) -> float:
        return self.shift_hours - self.break_hours - 2.0 * leg_hours


def estimate(
    frame: pd.DataFrame,
    model: SpeedModel,
    congestion: CongestionModel,
    day: DayModel | None = None,
    use_mean_turn_time: bool = True,
) -> dict:
    """Campaign estimate for one include set under one congestion assumption.

    `frame` must already carry `turn_mean_s`, `turn_min_s` and `depot_km`, and
    must already be reduced to the arcs the variant includes.
    """
    day = DayModel() if day is None else day
    traversals = TM.required_traversals(frame)
    length_km = frame["length_m"].to_numpy(dtype="float64") / 1000.0
    turn_s = frame["turn_mean_s" if use_mean_turn_time else "turn_min_s"].to_numpy(
        dtype="float64"
    )
    turn_floor = frame["turn_min_s"].to_numpy(dtype="float64")
    bands = band_index(frame["depot_km"].to_numpy(dtype="float64"))
    speed = leg_speed_kmh(congestion)

    rows = []
    for index, label in enumerate(band_labels()):
        in_band = bands == index
        required = in_band & (traversals > 0)
        band_km = float((length_km[required] * traversals[required]).sum())

        if band_km <= 0:
            rows.append(_empty_band(label))
            continue

        # Distance is weighted by the work in the band, so a band's leg cost
        # reflects where its streets actually are, not where its edges are.
        mean_km = float(
            np.average(frame["depot_km"].to_numpy(dtype="float64")[required],
                       weights=length_km[required] * traversals[required])
        )
        leg_hours = mean_km * C.DEPOT_DETOUR_FACTOR / speed
        productive = day.productive_hours(leg_hours)

        weights = congestion.work_band_weights(leg_hours, day.break_hours)
        band_frame = frame[in_band]
        index_array = congestion.blended_index(band_frame, weights)
        seconds = model.capture_time_s(band_frame, index_array)
        capture_hours = float((seconds * traversals[in_band]).sum() / 3600.0)
        turn_hours = float((turn_s[in_band] * traversals[in_band]).sum() / 3600.0)
        turn_hours_floor = float((turn_floor[in_band] * traversals[in_band]).sum() / 3600.0)
        work_hours = capture_hours + turn_hours

        rows.append(
            {
                "band_km": label,
                "required_km": band_km,
                "mean_depot_km": mean_km,
                "leg_hours": leg_hours,
                "productive_hours": productive,
                "capture_hours": capture_hours,
                "turn_hours": turn_hours,
                "turn_hours_floor": turn_hours_floor,
                "work_hours": work_hours,
                "days": (work_hours / productive) if productive > 0 else math.inf,
                "feasible": productive > 0,
            }
        )

    total_work = sum(r["work_hours"] for r in rows)
    total_days = sum(r["days"] for r in rows)
    return {
        "bands": rows,
        "required_km": sum(r["required_km"] for r in rows),
        "capture_hours": sum(r["capture_hours"] for r in rows),
        "turn_hours": sum(r["turn_hours"] for r in rows),
        "turn_hours_floor": sum(r["turn_hours_floor"] for r in rows),
        "work_hours": total_work,
        "depot_leg_hours": sum(r["days"] * 2.0 * r["leg_hours"] for r in rows if r["feasible"]),
        "days": total_days,
        "days_rounded": int(math.ceil(total_days)) if math.isfinite(total_days) else None,
        "leg_speed_kmh": speed,
        "congestion_scale": congestion.scale,
        "infeasible_bands": [r["band_km"] for r in rows if r["required_km"] > 0 and not r["feasible"]],
    }


def _empty_band(label: str) -> dict:
    return {
        "band_km": label, "required_km": 0.0, "mean_depot_km": 0.0, "leg_hours": 0.0,
        "productive_hours": 0.0, "capture_hours": 0.0, "turn_hours": 0.0,
        "turn_hours_floor": 0.0, "work_hours": 0.0, "days": 0.0, "feasible": True,
    }


def prepare(arcs: pd.DataFrame, graph=None) -> pd.DataFrame:
    """Attach the per-arc inputs the estimate needs: turn seconds and depot km."""
    frame = arcs.copy()
    frame["depot_km"] = depot_distance_km(frame)
    if graph is None:
        frame["turn_mean_s"] = 0.0
        frame["turn_min_s"] = 0.0
        return frame
    mean_s, min_s = turn_seconds_per_arc(graph)
    return attach_turn_time(frame, mean_s, min_s)


def scope_variants(
    prepared: pd.DataFrame,
    model: SpeedModel,
    congestion: CongestionModel,
    variants: tuple[str, ...] = C.STAGE2_SCOPE_VARIANTS,
) -> list[dict]:
    """The A / D / C table, in hours rather than kilometres.

    Each variant is re-evaluated rather than subtracted: dropping spurs changes
    which streets stay strongly connected, so the include set is rebuilt and the
    components relabelled for every one of them.
    """
    rows = []
    for variant in variants:
        frame = scenarios.apply_variant(prepared, variant)
        included = frame[~frame["excluded"]]
        result = estimate(included, model, congestion)
        result["variant"] = variant
        result["label"] = scenarios.VARIANT_LABELS[variant]
        result["included_arc_count"] = int(len(included))
        result["service_km_dropped"] = float(
            prepared.loc[
                (frame["exclusion_reason"] == "service_scope_variant").to_numpy()
                & prepared["is_pair_representative"].to_numpy(dtype=bool),
                "length_m",
            ].sum()
            / 1000.0
        )
        rows.append(result)

    baseline = rows[0]
    for row in rows:
        row["delta_days"] = row["days"] - baseline["days"]
        row["delta_work_hours"] = row["work_hours"] - baseline["work_hours"]
    return rows


def sensitivity(
    model: SpeedModel,
    variant_frame: pd.DataFrame,
    levels=None,
) -> list[dict]:
    """Campaign length across the congestion range.  Item 2's whole point."""
    from .congestion import sensitivity_levels

    levels = sensitivity_levels() if levels is None else sorted(set(levels))
    base = CongestionModel.from_config()
    rows = []
    for level in levels:
        result = estimate(variant_frame, model, base.scaled(level))
        rows.append(
            {
                "scale": level,
                "label": _scale_label(level),
                "capture_hours": result["capture_hours"],
                "turn_hours": result["turn_hours"],
                "turn_hours_floor": result["turn_hours_floor"],
                "work_hours": result["work_hours"],
                "days": result["days"],
                "days_rounded": result["days_rounded"],
                "leg_speed_kmh": result["leg_speed_kmh"],
            }
        )
    baseline = next(r for r in rows if r["scale"] == 1.0)
    for row in rows:
        row["delta_days"] = row["days"] - baseline["days"]
        row["delta_days_pct"] = (
            (row["days"] / baseline["days"] - 1.0) * 100.0 if baseline["days"] else 0.0
        )
    return rows


def _scale_label(level: float) -> str:
    if level == 0.0:
        return "free flow (no congestion)"
    if level == 1.0:
        return "baseline assumption"
    return f"{(level - 1.0) * 100:+.0f}% congestion"


def turn_sensitivity(
    frame: pd.DataFrame, model: SpeedModel, congestion: CongestionModel
) -> dict:
    """Campaign length at the turn-time floor and at the turn-time estimate.

    Without routes the turn account is a range, not a number, and the width of
    that range turns out to matter more than the congestion assumption does —
    which is worth measuring rather than asserting.
    """
    high = estimate(frame, model, congestion, use_mean_turn_time=True)
    low = estimate(frame, model, congestion, use_mean_turn_time=False)
    return {
        "mean_exit": {"turn_hours": high["turn_hours"], "work_hours": high["work_hours"],
                      "days": high["days"], "days_rounded": high["days_rounded"]},
        "min_exit": {"turn_hours": low["turn_hours"], "work_hours": low["work_hours"],
                     "days": low["days"], "days_rounded": low["days_rounded"]},
        "swing_days": high["days"] - low["days"],
        "swing_hours": high["work_hours"] - low["work_hours"],
    }


def deadhead_illustration(days: float, ratios=DEADHEAD_ILLUSTRATION) -> list[dict]:
    """What each slice of deadhead would cost, if it were known.  It is not.

    Stage 3's lower bound is the first number in this project entitled to say
    what the deadhead ratio is.  This table exists so that the reader can see the
    slope without the stage pretending to know where on it Tbilisi sits.
    """
    return [
        {"deadhead_ratio": ratio, "days": days * (1.0 + ratio),
         "days_rounded": int(math.ceil(days * (1.0 + ratio)))}
        for ratio in ratios
    ]
