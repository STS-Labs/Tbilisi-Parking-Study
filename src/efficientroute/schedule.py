"""Stage 4 items 3, 4 and 5 — sequence the zones, capture on the commute, taper.

Three rules from SPEC §7.1 and §7.3, in the order they are applied:

**Far zones first (§7.1 mitigation 2, a hard rule).**  Early in the campaign the
connecting corridors are still uncovered, so a long leg absorbs productive work.
Late in the campaign the same corridors are done and the same leg is pure
deadhead.  So the distant zones go first.  SPEC calls this counter-intuitive and
easy to implement backwards; the gate asserts the ordering rather than trusting
it.

**Capture on the commute (§7.1 mitigation 1).**  Legs are routed through
uncovered required arcs where it pays.  This only works *because* of the ordering
above — on day 1 almost nothing is covered and the legs are nearly free; by the
last day everything on the way home is already done.

**Daylight taper (§7.3).**  The usable day ends at `min(shift_end, sunset)`, and
sunset in Tbilisi drops below 18:00 at the end of October.  A campaign that runs
that late loses the tail of every remaining day.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np

from . import config as C
from . import daylight as D
from . import depotlegs


@dataclasses.dataclass
class Day:
    """One day of the campaign: which zone, when, and whether it fits."""

    position: int
    zone: int
    date: dt.date
    window_start_h: float
    window_end_h: float
    usable_end_h: float
    available_h: float
    taper_h: float
    capture_h: float
    work_h: float
    leg_out_h: float
    leg_back_h: float
    #: The plain deadhead round trip — the zone's intrinsic distance from the
    #: depot, and the key the sequence is ordered by.  The legs actually driven
    #: can be longer, because a coverage-routed leg trades clock time for work it
    #: takes off a later day.
    leg_baseline_h: float
    break_h: float
    commute_capture_h: float
    commute_arcs: int
    coverage_routed: bool

    @property
    def total_h(self) -> float:
        return self.work_h + self.leg_out_h + self.leg_back_h + self.break_h

    @property
    def slack_h(self) -> float:
        return self.available_h - self.total_h

    @property
    def fits(self) -> bool:
        return self.slack_h >= -1e-9

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "zone": int(self.zone),
            "date": self.date.isoformat(),
            "window": f"{D.hhmm(self.window_start_h)}–{D.hhmm(self.window_end_h)}",
            "sunset": D.hhmm(D.sunset_hour(self.date)),
            "usable_end": D.hhmm(self.usable_end_h),
            "available_h": self.available_h,
            "taper_h": self.taper_h,
            "capture_h": self.capture_h,
            "work_h": self.work_h,
            "leg_out_h": self.leg_out_h,
            "leg_back_h": self.leg_back_h,
            "leg_total_h": self.leg_out_h + self.leg_back_h,
            "leg_baseline_h": self.leg_baseline_h,
            "break_h": self.break_h,
            "total_h": self.total_h,
            "slack_h": self.slack_h,
            "fits": self.fits,
            "commute_capture_h": self.commute_capture_h,
            "commute_arcs": self.commute_arcs,
            "coverage_routed": self.coverage_routed,
        }


@dataclasses.dataclass
class Campaign:
    days: list[Day]
    window_name: str
    start_date: dt.date
    commute_capture_h: float
    commute_arcs: int
    coverage_routed_legs: int
    plain_legs: int

    @property
    def finish_date(self) -> dt.date:
        return self.days[-1].date

    @property
    def durations(self) -> np.ndarray:
        return np.array([d.total_h for d in self.days], dtype="float64")

    @property
    def taper_hours(self) -> float:
        return float(sum(d.taper_h for d in self.days))

    @property
    def first_tapered_day(self) -> Day | None:
        return next((d for d in self.days if d.taper_h > 1e-9), None)

    def to_dict(self) -> dict:
        durations = self.durations
        return {
            "window": self.window_name,
            "start_date": self.start_date.isoformat(),
            "finish_date": self.finish_date.isoformat(),
            "days": len(self.days),
            "total_hours": float(durations.sum()),
            "day_hours_min": float(durations.min()),
            "day_hours_max": float(durations.max()),
            "day_hours_mean": float(durations.mean()),
            "day_hours_stdev": float(durations.std()),
            "all_days_fit": bool(all(d.fits for d in self.days)),
            "commute_capture_h": self.commute_capture_h,
            "commute_arcs": self.commute_arcs,
            "coverage_routed_legs": self.coverage_routed_legs,
            "plain_legs": self.plain_legs,
            "taper_hours": self.taper_hours,
            "first_tapered_day": (
                self.first_tapered_day.to_dict() if self.first_tapered_day else None
            ),
            "day_table": [d.to_dict() for d in self.days],
        }


def sequence_far_first(zone_ids: np.ndarray, leg_total_s: np.ndarray) -> np.ndarray:
    """Zones ordered by descending depot-leg cost — SPEC §7.1 mitigation 2.

    Ties break on zone id so the order is total and reproducible; without that a
    tie would make the sequence depend on numpy's sort stability, which is not a
    contract this project should lean on.
    """
    order = np.lexsort((zone_ids, -leg_total_s))
    return zone_ids[order]


def build(
    graph,
    zones,
    labels: np.ndarray,
    field: depotlegs.LegField,
    capture_s: np.ndarray,
    deadhead_s: np.ndarray,
    required: np.ndarray,
    traversals: np.ndarray,
    overhead: float,
    window_name: str,
    start_date: dt.date,
    break_hours: float = C.BREAK_HOURS,
    capture_on_commute: bool = True,
    arrays=None,
) -> Campaign:
    """Walk the sequence, routing each leg against what is still uncovered."""
    shift_start, shift_end = C.SHIFT_WINDOWS[window_name]
    arrays = depotlegs.manoeuvre_arrays(graph) if arrays is None else arrays
    zone_ids = np.unique(labels)

    nodes_by_zone = {
        int(zone): np.concatenate(
            [zones.nodes_of_segment[s] for s in np.flatnonzero(labels == zone)]
        )
        for zone in zone_ids
    }
    leg_total_s = np.array(
        [
            depotlegs.nearest_in_zone(field, nodes_by_zone[int(z)], True)[0]
            + depotlegs.nearest_in_zone(field, nodes_by_zone[int(z)], False)[0]
            for z in zone_ids
        ]
    )
    order = sequence_far_first(zone_ids, leg_total_s)

    covered = np.zeros(graph.n_nodes, dtype=bool)
    days: list[Day] = []
    commute_capture_s = 0.0
    commute_arcs = 0
    routed = 0
    plain = 0

    for position, zone in enumerate(order):
        nodes = nodes_by_zone[int(zone)]
        date = start_date + dt.timedelta(days=position)
        usable_end = D.usable_end_hour(date, shift_end)
        available = max(0.0, usable_end - shift_start)
        taper = max(0.0, (shift_end - shift_start) - available)

        out_s, out_node = depotlegs.nearest_in_zone(field, nodes, True)
        back_s, back_node = depotlegs.nearest_in_zone(field, nodes, False)
        out_leg = depotlegs.plain_leg(field, out_node, outbound=True)
        back_leg = depotlegs.plain_leg(field, back_node, outbound=False)

        if capture_on_commute:
            out_leg = depotlegs.coverage_leg(
                graph, capture_s, deadhead_s, required, covered,
                field.depot_node, nodes, True, out_leg, arrays=arrays,
            )
            covered[out_leg.captured] = True
            back_leg = depotlegs.coverage_leg(
                graph, capture_s, deadhead_s, required, covered,
                field.depot_node, nodes, False, back_leg, arrays=arrays,
            )
            covered[back_leg.captured] = True

        remaining = nodes[required[nodes] & ~covered[nodes]]
        capture_h = float((capture_s[remaining] * traversals[remaining]).sum() / 3600.0)

        day = Day(
            position=position,
            zone=int(zone),
            date=date,
            window_start_h=shift_start,
            window_end_h=shift_end,
            usable_end_h=usable_end,
            available_h=available,
            taper_h=taper,
            capture_h=capture_h,
            work_h=capture_h * overhead,
            leg_out_h=out_leg.seconds / 3600.0,
            leg_back_h=back_leg.seconds / 3600.0,
            leg_baseline_h=(out_s + back_s) / 3600.0,
            break_h=break_hours,
            commute_capture_h=(out_leg.capture_s + back_leg.capture_s) / 3600.0,
            commute_arcs=len(out_leg.captured) + len(back_leg.captured),
            coverage_routed=out_leg.routed_for_coverage or back_leg.routed_for_coverage,
        )

        # A coverage-routed leg is longer on the clock than the plain one it
        # replaced.  If that tips the day over its window, the saving is not worth
        # having and the plain leg goes back — the day still has to close.
        if not day.fits and (out_leg.routed_for_coverage or back_leg.routed_for_coverage):
            # Give the leg's coverage credit back before re-measuring the zone,
            # or the day is "fixed" by pretending its work was already done.
            covered[out_leg.captured] = False
            covered[back_leg.captured] = False
            plain_out = depotlegs.plain_leg(field, out_node, outbound=True)
            plain_back = depotlegs.plain_leg(field, back_node, outbound=False)
            recovered = nodes[required[nodes] & ~covered[nodes]]
            plain_capture = float(
                (capture_s[recovered] * traversals[recovered]).sum() / 3600.0
            )
            day = dataclasses.replace(
                day,
                capture_h=plain_capture,
                work_h=plain_capture * overhead,
                leg_out_h=plain_out.seconds / 3600.0,
                leg_back_h=plain_back.seconds / 3600.0,
                commute_capture_h=0.0,
                commute_arcs=0,
                coverage_routed=False,
            )

        covered[nodes] = True

        if day.coverage_routed:
            routed += 1
        else:
            plain += 1
        commute_capture_s += day.commute_capture_h * 3600.0
        commute_arcs += day.commute_arcs
        days.append(day)

    return Campaign(
        days=days,
        window_name=window_name,
        start_date=start_date,
        commute_capture_h=commute_capture_s / 3600.0,
        commute_arcs=commute_arcs,
        coverage_routed_legs=routed,
        plain_legs=plain,
    )


def latest_feasible_start(
    build_campaign, earliest: dt.date, latest: dt.date
) -> tuple[dt.date | None, dict]:
    """The last start date at which every day still fits its window.

    The taper only bites at the end of October, so this is the number the
    schedule decision actually turns on: not "does it fit today" but "how long can
    the decision wait".  Binary search over start dates, each evaluated by a full
    campaign build.
    """
    probes: dict[str, bool] = {}

    def fits(date: dt.date) -> bool:
        campaign = build_campaign(date)
        ok = all(day.fits for day in campaign.days)
        probes[date.isoformat()] = ok
        return ok

    if not fits(earliest):
        return None, probes
    low, high = earliest, latest
    if fits(high):
        return high, probes
    while (high - low).days > 1:
        middle = low + dt.timedelta(days=(high - low).days // 2)
        if fits(middle):
            low = middle
        else:
            high = middle
    return low, probes
