"""Stage 4c gate. Every assertion here is copied from
`prompts/04c-rezone-on-measured-overhead.md`.

Stage 4 sizes a day as `capture x overhead + legs + break` (`zoning.zone_durations`),
so `overhead` is the *intra-zone* multiplier and the depot legs are added beside
it. Stage 5 reports a solved day as `route_h`, which already contains both legs.
Taking the overhead from `route_h / capture_h` therefore charges the legs twice
and inflates every zone's predicted day, which is what produced 38 zones sized for
a day 1.2 h longer than the one actually driven.

These assertions are read from the committed artifacts rather than recomputed in
memory, so they check the plan the project is working to, not a solver's scratch
state.
"""
import json
import math

import pytest

from efficientroute import config as C

pytestmark = pytest.mark.gate4c

#: Zones Stage 5 had to split are excluded from the calibration comparison: their
#: Stage 5 day covers half the zone Stage 4 predicted, so the pair is not like for
#: like. The split *count* is asserted separately, and is the sharper signal.
WINDOW = "9h"


def _quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


@pytest.fixture(scope="module", autouse=True)
def _requires_stage_4c():
    """Stage 4c is a re-zoning *comparison*; a campaign that never ran it has
    nothing to compare. Its baselines are the marker that it did."""
    if not (C.BASELINE_ZONES_JSON.exists() and C.BASELINE_ROUTES_JSON.exists()):
        pytest.skip(
            "no Stage 4c baseline for this campaign — the sizing was never re-derived "
            "here, so there is no calibrated-overhead claim to check"
        )


@pytest.fixture(scope="module")
def zoning_payload() -> dict:
    if not C.ZONES_JSON.exists():
        pytest.skip(f"{C.ZONES_JSON} not built — run `make stage4`")
    return json.loads(C.ZONES_JSON.read_text())


@pytest.fixture(scope="module")
def routes_payload() -> dict:
    if not C.ROUTES_JSON.exists():
        pytest.skip(f"{C.ROUTES_JSON} not built — run `make stage5`")
    return json.loads(C.ROUTES_JSON.read_text())


@pytest.fixture(scope="module")
def measured(zoning_payload, routes_payload) -> dict:
    """Stage 5's solved days, re-expressed as the ratio Stage 4 actually needs."""
    zones = {z["zone"]: z for z in zoning_payload["windows"][WINDOW]["zones"]}
    split = {s["zone"] for s in routes_payload["splits"]}
    split |= {into for s in routes_payload["splits"] for into in s["into"]}

    intra, inclusive, identity = [], [], []
    for day in routes_payload["days"]:
        zone = zones.get(day["zone"])
        if zone is None:
            continue
        legs_h = zone["leg_total_h"]
        intra.append((day["route_h"] - legs_h) / day["capture_h"])
        inclusive.append(day["route_h"] / day["capture_h"])
        if day["zone"] not in split:
            achieved = (day["route_h"] - legs_h) / day["capture_h"]
            resid = (zone["total_h"] - day["day_h"]) / day["capture_h"]
            identity.append(abs(resid + achieved - zoning_payload["overhead"]["factor"]))
    return {"intra": intra, "inclusive": inclusive, "identity": identity}


class TestSizingIsCalibrated:
    def test_the_overhead_is_drawn_from_the_intra_zone_distribution(
        self, zoning_payload, measured
    ):
        """The value used must be a quantile of the leg-excluded ratios.

        The two distributions overlap, so a bare range check would pass on the
        wrong one. The discriminator is the *upper tail*: the leg-inclusive
        distribution sits a whole leg-pair-per-capture-hour above the leg-excluded
        one, so a value taken from it lands above the leg-excluded p95.
        """
        used = zoning_payload["overhead"]["factor"]
        ceiling = _quantile(measured["intra"], 0.95)
        assert used <= ceiling + 1e-9, (
            f"overhead {used:.3f} exceeds the leg-excluded p95 {ceiling:.3f} — it "
            f"looks drawn from route_h/capture_h (p95 "
            f"{_quantile(measured['inclusive'], 0.95):.3f}), which double-counts "
            "the depot legs"
        )

    def test_the_overhead_is_at_least_the_intra_zone_median(
        self, zoning_payload, measured
    ):
        """Sizing below the median guarantees overruns; the plan asks for p75-p90."""
        used = zoning_payload["overhead"]["factor"]
        floor = _quantile(measured["intra"], 0.5)
        assert used >= floor - 1e-9, (
            f"overhead {used:.3f} is below the measured median {floor:.3f}"
        )

    def test_the_residual_cannot_be_used_to_detect_the_double_count(self, measured):
        """Guards the *reason* the bracket above is the only detector.

        It is tempting to look for the defect in `predicted - actual`, on the
        theory that a double-counted leg shows up as an over-prediction the size
        of a leg pair. It does not. The model predicts
        `capture x overhead + legs + break` and the solver drives
        `capture x achieved + legs + break`, so the legs cancel in the difference
        no matter which quantity `overhead` holds:

            predicted - actual == capture x (overhead - achieved)

        Measured on the committed plan the deviation from that identity was 0.008
        and on the corrected one 0.005 — indistinguishable. The over-prediction of
        1.26 h under `2.55` resembled a leg pair by arithmetic coincidence, not by
        mechanism. This test pins the identity so nobody re-derives the wrong
        detector later.
        """
        deviations = measured["identity"]
        assert deviations, "no unsplit zones to compare"
        assert _quantile(deviations, 0.5) < 0.05, (
            "predicted - actual no longer equals capture x (overhead - achieved); "
            "the cost model has grown a term the measurement does not know about"
        )


class TestTheReZonedPlanIsBetter:
    def test_few_zones_needed_splitting(self, routes_payload, zoning_payload):
        """The plan's own headline: days over window *before* splitting.

        A split is Stage 5 repairing a zone Stage 4 sized wrong, and it costs a
        whole day — an oversized zone becomes two undersized ones. The prompt asks
        for "few or no overruns", not none: sizing on an upper quantile means a
        minority of zones are expected to exceed, and driving that to zero would
        need the tail (max 3.35 against a median 2.06), which starves every
        well-behaved zone. The threshold separates a sizing that works from one
        that does not — the swept candidates split 4.3% (p90), 9.3% (p75, adopted)
        and 41% (p50, which is the "overhead model is still wrong" case).
        """
        zones = len(zoning_payload["windows"][WINDOW]["zones"])
        splits = len(routes_payload["splits"])
        assert splits <= 0.15 * zones, (
            f"{splits} of {zones} zones needed splitting ({splits / zones:.1%}) — "
            "splitting has become the main repair, so the sizing is wrong"
        )

    def test_no_day_exceeds_its_window(self, routes_payload):
        assert routes_payload["totals"]["days_over_window"] == 0

    def test_the_campaign_is_shorter_than_the_committed_plan(self, routes_payload):
        """No regression (prompt gate): a re-run that is not shorter is not adopted."""
        assert routes_payload["totals"]["days"] < 50, (
            f"{routes_payload['totals']['days']} days against the committed 50 — "
            "keep the committed plan"
        )
