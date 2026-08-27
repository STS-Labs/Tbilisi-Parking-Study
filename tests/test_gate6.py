"""Stage 6 gate. Every assertion is copied from `prompts/06-coverage-tracker.md`.

The brief names the failure that matters: a matcher that is too lenient marks
streets covered that were never filmed, and nobody finds out until the footage is
reviewed weeks later with the car long gone. So these tests are written to catch
leniency, not strictness — a matcher that refuses a marginal match fails nothing
here, while one that accepts a wrong-direction or too-fast pass fails loudly.

The network is a toy street rather than the 286k-arc base network: these must run
in milliseconds on every commit, and the matcher's correctness does not depend on
scale. The real network is exercised by the round-trip against a solved day.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import toygraph  # noqa: E402

from efficientroute import config as C  # noqa: E402
from efficientroute import coverage, trace  # noqa: E402

pytestmark = pytest.mark.gate6

#: Four arcs: a plain one-way, a reduced-quality one-way, a narrow pair where
#: either direction counts, and an arc wanting two passes.
SPECS = [
    {"capture_quality": "full"},
    {"capture_quality": "reduced"},
    {"pair": True},
    {"min_passes": 2},
]


@pytest.fixture
def network():
    return toygraph.street(SPECS)


@pytest.fixture
def frame(network):
    return network[0]


@pytest.fixture
def centreline(network):
    return network[1]


def _ingest(frame, coords, speed_kmh, state=None):
    return coverage.ingest(
        trace.synthesise(coords, speed_kmh=speed_kmh), frame, state=state
    )


class TestRoundTrip:
    def test_a_trace_of_the_planned_route_covers_all_of_it(self, frame, centreline):
        """The brief: 100%, or the matcher is wrong."""
        out = _ingest(frame, centreline, speed_kmh=25.0)
        missed = [k for k, v in out.state.remaining.items() if v]
        # The two-pass arc still owes its second pass after one traversal.
        assert missed == ["103:0:F"], missed
        assert out.state.remaining["103:0:F"] == 1
        for key in ("100:0:F", "101:0:F", "P2"):
            assert out.state.remaining[key] == 0, f"{key} not covered"

    def test_a_second_traversal_finishes_the_two_pass_arc(self, frame, centreline):
        out = _ingest(frame, centreline, speed_kmh=25.0)
        out = _ingest(frame, centreline, speed_kmh=25.0, state=out.state)
        assert not any(out.state.remaining.values()), out.state.remaining


class TestDirection:
    def test_the_reversed_trace_covers_nothing_on_directed_arcs(self, frame, centreline):
        """SPEC §10.3: a wrong-direction pass does not count."""
        out = _ingest(frame, list(reversed(centreline)), speed_kmh=25.0)
        for key in ("100:0:F", "101:0:F", "103:0:F"):
            assert out.state.covered.get(key, 0) == 0, f"{key} covered backwards"

    def test_the_reversed_trace_still_covers_a_narrow_pair(self, frame, centreline):
        """A narrow pair is one requirement satisfiable from either direction."""
        out = _ingest(frame, list(reversed(centreline)), speed_kmh=25.0)
        assert out.state.covered.get("P2", 0) == 1, "the pair should accept either way"

    def test_every_rejection_says_why(self, frame, centreline):
        out = _ingest(frame, list(reversed(centreline)), speed_kmh=25.0)
        rejected = [v for v in out.verdicts if not v.counted]
        assert rejected, "the reversed trace must reject something"
        assert all(v.reason for v in rejected)
        assert {"heading"} <= {v.reason for v in rejected}


class TestSpeed:
    def test_sixty_kmh_covers_nothing_on_full_quality_arcs(self, frame, centreline):
        out = _ingest(frame, centreline, speed_kmh=60.0)
        for key in ("100:0:F", "P2", "103:0:F"):
            assert out.state.covered.get(key, 0) == 0, f"{key} covered at 60 km/h"
        assert "speed" in {v.reason for v in out.verdicts if not v.counted}

    def test_sustained_over_speed_on_part_of_an_arc_does_not_count(self, frame):
        """The case a constant-speed trace cannot express.

        Crawling half a street and racing the other half averages to something
        acceptable while half the footage is unusable. Whichever speed statistic the
        rule uses, it has to reject this — and only a variable-speed trace proves it
        does. Written after a deliberately weakened quantile passed every other test
        in this class.
        """
        one_arc, coords = toygraph.street([{"capture_quality": "full"}])
        midpoint = (
            (coords[0][0] + coords[1][0]) / 2.0,
            (coords[0][1] + coords[1][1]) / 2.0,
        )
        crawl_then_race = trace.synthesise(
            [coords[0], midpoint, coords[1]], speed_kmh=[15.0, 75.0]
        )
        out = coverage.ingest(crawl_then_race, one_arc)
        assert out.state.covered.get("100:0:F", 0) == 0, (
            "half the arc was driven at 75 km/h; that footage is not usable"
        )
        assert "speed" in {v.reason for v in out.verdicts if not v.counted}

    def test_sixty_kmh_covers_reduced_quality_arcs(self, frame, centreline):
        """SPEC §3.2 already accepted a reduced pass on these, so speed is not a bar."""
        out = _ingest(frame, centreline, speed_kmh=60.0)
        assert out.state.covered.get("101:0:F", 0) == 1


class TestAccounting:
    def test_remaining_plus_covered_plus_retired_is_the_original_requirement(
        self, frame, centreline
    ):
        """The brief's exact-accounting rule, counted in required passes."""
        state = coverage.CoverageState.initial(frame)
        original = dict(state.required)
        out = _ingest(frame, centreline, speed_kmh=25.0, state=state)
        out.state.retire("103:0:F", reason="gated", date="2026-08-26", reporter="driver")
        for key, total in original.items():
            got = (
                out.state.covered.get(key, 0)
                + out.state.remaining.get(key, 0)
                + out.state.retired_passes.get(key, 0)
            )
            assert got == total, f"{key}: {got} != {total}"

    def test_coverage_is_monotonic_across_ingests(self, frame, centreline):
        """A re-plan never un-covers something, absent an explicit exception."""
        out = _ingest(frame, centreline, speed_kmh=25.0)
        before = dict(out.state.covered)
        # A day that covers nothing at all must not reduce what is already covered.
        out = _ingest(frame, list(reversed(centreline)), speed_kmh=60.0, state=out.state)
        for key, was in before.items():
            assert out.state.covered.get(key, 0) >= was, f"{key} went backwards"


class TestRecordingEvidence:
    def test_a_trace_alone_is_not_proof_the_camera_was_on(self, frame, centreline):
        """The brief: a GPS trace is evidence the car was there, not that it filmed.

        With no footage timestamps available the state must say so, so the report
        can print it rather than the number quietly implying more than it knows.
        """
        out = _ingest(frame, centreline, speed_kmh=25.0)
        assert C.RECORDING_EVIDENCE_AVAILABLE is False
        assert out.recording_evidence == "unknown"


class TestDeterminism:
    def test_the_same_trace_twice_gives_the_same_answer(self, frame, centreline):
        a = _ingest(frame, centreline, speed_kmh=25.0)
        b = _ingest(frame, centreline, speed_kmh=25.0)
        assert a.state.covered == b.state.covered
        assert [(v.arc_id, v.counted, v.reason) for v in a.verdicts] == [
            (v.arc_id, v.counted, v.reason) for v in b.verdicts
        ]


class TestExceptionsRegister:
    """Item 3 — the register that stops the re-planner returning to a locked gate."""

    def test_a_retired_street_leaves_the_required_set(self, frame, tmp_path):
        from efficientroute import exceptions

        state = coverage.CoverageState.initial(frame)
        assert "100:0:F" in state.outstanding()
        register = [
            coverage.Exception_("100:0:F", "gated", "2026-08-26", "driver", True)
        ]
        exceptions.apply(state, register)
        assert "100:0:F" not in state.outstanding()
        assert state.retired_passes["100:0:F"] == 1

    def test_applying_the_register_twice_changes_nothing(self, frame):
        from efficientroute import exceptions

        state = coverage.CoverageState.initial(frame)
        register = [
            coverage.Exception_("100:0:F", "gated", "2026-08-26", "driver", True)
        ]
        exceptions.apply(state, register)
        first = dict(state.retired_passes)
        exceptions.apply(state, register)
        assert state.retired_passes == first
        assert len(state.exceptions) == 1

    def test_a_temporary_exclusion_returns_after_the_interval(self, frame):
        from efficientroute import exceptions

        state = coverage.CoverageState.initial(frame)
        register = [
            coverage.Exception_("100:0:F", "blocked", "2026-08-26", "driver", False)
        ]
        exceptions.apply(state, register, today="2026-08-27")
        assert "100:0:F" not in state.outstanding(), "still blocked the next day"
        exceptions.apply(state, register, today="2026-10-01")
        assert "100:0:F" in state.outstanding(), "should have returned to be re-tried"

    def test_the_register_round_trips_through_csv(self, frame, tmp_path):
        from efficientroute import exceptions

        path = tmp_path / "06-exceptions.csv"
        entries = [
            coverage.Exception_("100:0:F", "gated", "2026-08-26", "driver", True),
            coverage.Exception_("101:0:F", "blocked", "2026-08-27", "driver", False),
        ]
        exceptions.write(entries, path)
        assert [vars(e) for e in exceptions.read(path)] == [vars(e) for e in entries]

    def test_retired_kilometres_are_reported(self, frame):
        from efficientroute import exceptions

        state = coverage.CoverageState.initial(frame)
        report = exceptions.apply(
            state, [coverage.Exception_("100:0:F", "gated", "2026-08-26", "d", True)]
        )
        assert report["retired_km"] == pytest.approx(0.120), (
            "retired km caps what complete coverage can mean and must be visible"
        )


class TestSampleRate:
    """The matcher must not care how fast the rig logs.

    Written after a 10 Hz replay scored 33% against a 1 Hz replay's 99.9%. Heading
    was being taken from consecutive fixes, so a dense trace had no baseline at all
    and every fix read as due north — matching only northbound arcs. Nothing in the
    single-rate tests could see it, and a rig logging at 10 Hz is entirely ordinary.
    """

    @pytest.mark.parametrize("hz", [1.0, 2.0, 5.0, 10.0, 20.0])
    def test_heading_survives_any_log_rate(self, centreline, hz):
        east = trace.synthesise(centreline, speed_kmh=25.0, hz=hz)
        assert east.heading_deg.mean() == pytest.approx(90.0, abs=1.0), (
            f"at {hz} Hz the derived heading is {east.heading_deg.mean():.0f}°, not east"
        )
        west = trace.synthesise(list(reversed(centreline)), speed_kmh=25.0, hz=hz)
        assert west.heading_deg.mean() == pytest.approx(270.0, abs=1.0)

    @pytest.mark.parametrize("hz", [1.0, 2.0, 5.0, 10.0])
    def test_coverage_survives_any_log_rate(self, frame, centreline, hz):
        out = coverage.ingest(
            trace.synthesise(centreline, speed_kmh=25.0, hz=hz), frame
        )
        for key in ("100:0:F", "101:0:F", "P2"):
            assert out.state.covered.get(key, 0) == 1, f"{key} missed at {hz} Hz"


class TestAgainstTheRealNetwork:
    """The brief's round trip, on the 286k-arc network and a solved day.

    The toy street proves the rules; this proves they survive real geometry —
    switchbacks, 4 m junction stubs, paired narrow streets and 80k routable arcs.
    """

    @pytest.fixture(scope="class")
    def solved_day(self):
        import geopandas as gpd

        from efficientroute import scenarios

        if not (C.NETWORK_GPKG.exists() and C.ROUTES_GPKG.exists()):
            pytest.skip("network or routes not built — run `make stage5`")
        arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
        arcs = scenarios.apply_variant(arcs, C.SCOPE_VARIANT)
        routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])].reset_index(drop=True)
        manoeuvres = gpd.read_file(C.ROUTES_GPKG, layer=C.ROUTES_LAYER)
        day = manoeuvres[(manoeuvres["day"] == 1) & (manoeuvres["mode"] == "capture")]
        planned = trace.read(C.ROUTES_DIR / "day-01.gpx")
        return routable, set(day["arc_id"].astype(str)), list(zip(planned.lon, planned.lat))

    def test_replaying_a_solved_day_covers_all_of_it(self, solved_day):
        routable, required, coords = solved_day
        replay = trace.synthesise(coords, speed_kmh=25.0, hz=C.MIN_TRACE_RATE_HZ)
        state = coverage.CoverageState.initial(routable)
        coverage.ingest(replay, routable, state=state)
        keys = {state.key_of(a) for a in required} - {None}
        covered = {k for k in keys if state.covered.get(k, 0) > 0}
        assert len(covered) == len(keys), (
            f"{len(keys) - len(covered)} of {len(keys)} required elements missed"
        )

    def test_no_coverage_is_ever_credited_against_the_heading(self, solved_day):
        """The invariant that actually holds at scale, forwards or backwards."""
        routable, required, coords = solved_day
        for direction in (coords, list(reversed(coords))):
            replay = trace.synthesise(direction, speed_kmh=25.0, hz=C.MIN_TRACE_RATE_HZ)
            out = coverage.ingest(replay, routable)
            over = [v for v in out.verdicts
                    if v.counted and v.heading_delta_deg > C.MATCH_HEADING_TOLERANCE_DEG]
            assert not over, f"{len(over)} arcs credited beyond the heading tolerance"

    def test_backwards_coverage_of_a_one_way_is_only_ever_the_parallel_carriageway(
        self, solved_day
    ):
        """Driving a day backwards does still credit some one-way arcs. This pins
        down *why*, because the answer decides whether it is a defect.

        It is not the matcher accepting a wrong-way drive down an arc: it is the car
        being within the candidate radius of the *opposite* carriageway of a one-way
        pair, which genuinely does run in its direction of travel. Position cannot
        distinguish those two situations and neither can this matcher — but the two
        look completely different in match distance. Legitimate coverage sits on the
        arc; carriageway confusion sits 11-21 m off it. If that separation ever
        closes, the matcher has started crediting arcs the car was really driving the
        wrong way down, which is the failure this whole stage exists to prevent.
        """
        import numpy as np

        routable, required, coords = solved_day
        oneway = dict(zip(routable["arc_id"].astype(str), routable["oneway"].astype(str)))

        def credited_distances(cs):
            out = coverage.ingest(
                trace.synthesise(cs, speed_kmh=25.0, hz=C.MIN_TRACE_RATE_HZ), routable
            )
            found = {}
            for v in out.verdicts:
                if not v.counted:
                    continue
                d = out.match.distance_m[v.first_fix : v.last_fix + 1]
                d = d[~np.isnan(d)]
                if len(d):
                    found.setdefault(v.key, []).append(float(np.mean(d)))
            return out, found

        _, forward = credited_distances(coords)
        out, backward = credited_distances(list(reversed(coords)))

        leaked = [
            min(v) for k, v in backward.items()
            if (out.state.members.get(k) or [])
            and all(oneway.get(a) == "yes" for a in out.state.members[k])
        ]
        assert leaked, "expected some carriageway confusion to measure"
        assert float(np.median([min(v) for v in forward.values()])) < 1.0, (
            "legitimate coverage should sit on the arc"
        )
        assert float(np.median(leaked)) > 5.0, (
            "one-way arcs credited on a reversed replay are matching too close to be "
            "the parallel carriageway — the matcher is accepting wrong-way drives"
        )


class TestCalibration:
    """Item 4 — the measurements the campaign gets for free.

    No real trace exists yet, so these check the extractors against synthetic traces
    with a known answer. That is what they can prove: that a dwell of N seconds comes
    back as N. What they cannot prove is anything about Tbilisi's actual junctions —
    SPEC §3.3's coefficients stay [CONFIRM] until a real day is driven.
    """

    @pytest.mark.parametrize("dwell", [3.0, 6.0, 12.0, 20.0])
    def test_a_known_junction_delay_is_recovered(self, centreline, dwell):
        from efficientroute import calibrate, matcher

        frame, coords = toygraph.street([{}, {}, {}, {}])
        t = trace.synthesise(coords, speed_kmh=25.0, hz=4.0, dwell_s={2: dwell})
        observed = calibrate.turn_observations(t, matcher.match(t, frame), frame)
        assert max(o.excess_s for o in observed) == pytest.approx(dwell, abs=0.25)

    def test_driving_straight_through_costs_nothing(self):
        """`straight` is the control: if it does not come back at zero, the method
        is measuring something other than the turn."""
        from efficientroute import calibrate, matcher

        frame, coords = toygraph.street([{}, {}, {}, {}])
        t = trace.synthesise(coords, speed_kmh=25.0, hz=4.0)
        observed = calibrate.turn_observations(t, matcher.match(t, frame), frame)
        assert observed
        assert all(o.excess_s == pytest.approx(0.0, abs=0.05) for o in observed)

    def test_the_coefficients_are_reported_beside_what_is_assumed(self, centreline):
        """A measurement that does not say what it is replacing cannot be reviewed,
        and CLAUDE.md forbids adopting it automatically."""
        from efficientroute import calibrate, matcher

        frame, coords = toygraph.street([{}, {}, {}, {}])
        t = trace.synthesise(coords, speed_kmh=25.0, hz=4.0, dwell_s={2: 8.0})
        result = calibrate.calibrate(t, matcher.match(t, frame), frame)
        assert result.turns
        for name, stats in result.turns.items():
            assert stats["assumed_s"] == C.TURN_PENALTY_S[name]
            assert stats["n"] >= 1

    def test_calibration_never_writes_a_constant(self, centreline):
        """Per CLAUDE.md: pinned, not fed back. Adopting a measurement is a human act."""
        from efficientroute import calibrate, matcher

        frame, coords = toygraph.street([{}, {}, {}, {}])
        before = dict(C.TURN_PENALTY_S)
        t = trace.synthesise(coords, speed_kmh=25.0, hz=4.0, dwell_s={2: 9.0})
        calibrate.calibrate(t, matcher.match(t, frame), frame)
        assert C.TURN_PENALTY_S == before


class TestUntimedTraces:
    """A trace with no clock cannot satisfy a condition about speed.

    Found by running the stage end to end on a planned route exported as GPX, which
    carries no `<time>`. Numbering the fixes one-per-second invents speeds — some
    above the capture limit, some below — so coverage becomes an artefact of vertex
    spacing. Refusing is the only honest answer, and it must be loud.
    """

    def test_a_gpx_without_timestamps_is_flagged(self, tmp_path, centreline):
        path = tmp_path / "planned.gpx"
        points = "".join(
            f'<trkpt lat="{y}" lon="{x}"></trkpt>' for x, y in centreline
        )
        path.write_text(
            '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><trkseg>{points}</trkseg></trk></gpx>"
        )
        assert trace.read(path).has_time is False

    def test_an_untimed_trace_covers_nothing_it_cannot_verify(self, frame, centreline):
        from dataclasses import replace

        timed = trace.synthesise(centreline, speed_kmh=25.0, hz=2.0)
        untimed = replace(timed, has_time=False)
        assert coverage.ingest(timed, frame).gained > 0
        out = coverage.ingest(untimed, frame)
        assert out.state.covered.get("100:0:F", 0) == 0
        assert "no-time" in {v.reason for v in out.verdicts if not v.counted}

    def test_a_reduced_quality_arc_is_still_covered_without_time(self, frame, centreline):
        """Speed is not a condition on these, so the missing clock does not matter."""
        from dataclasses import replace

        untimed = replace(trace.synthesise(centreline, speed_kmh=25.0, hz=2.0),
                          has_time=False)
        out = coverage.ingest(untimed, frame)
        assert out.state.covered.get("101:0:F", 0) == 1
