"""Turn classification from geometry (SPEC §3.3).

Bearings are geographic: 0 = north, increasing clockwise, so a positive delta is
a right turn.  Getting that sign backwards silently swaps the 3 s and 8 s
penalties on every junction in the city, which no downstream test would catch.
"""
import pytest
from shapely.geometry import LineString

from efficientroute import bearings as B


class TestBearing:
    def test_due_north(self):
        assert B.bearing_deg(44.8, 41.7, 44.8, 41.8) == pytest.approx(0.0, abs=1e-6)

    def test_due_east(self):
        assert B.bearing_deg(44.8, 41.7, 44.9, 41.7) == pytest.approx(90.0, abs=0.05)

    def test_due_south(self):
        assert B.bearing_deg(44.8, 41.8, 44.8, 41.7) == pytest.approx(180.0, abs=1e-6)

    def test_due_west(self):
        assert B.bearing_deg(44.9, 41.7, 44.8, 41.7) == pytest.approx(270.0, abs=0.05)

    def test_always_in_zero_to_360(self):
        for lon, lat in [(44.7, 41.6), (44.9, 41.8), (44.75, 41.75)]:
            assert 0.0 <= B.bearing_deg(44.8, 41.7, lon, lat) < 360.0


class TestTurnDelta:
    @pytest.mark.parametrize(
        "incoming,outgoing,expected",
        [(0, 90, 90), (0, 270, -90), (0, 180, 180), (350, 10, 20), (10, 350, -20), (90, 90, 0)],
    )
    def test_signed_delta(self, incoming, outgoing, expected):
        assert B.turn_delta_deg(incoming, outgoing) == pytest.approx(expected)

    def test_delta_is_in_the_half_open_range(self):
        assert -180.0 < B.turn_delta_deg(0, 180) <= 180.0


class TestClassify:
    @pytest.mark.parametrize("delta", [0, 15, -15, 29.9, -29.9])
    def test_straight(self, delta):
        assert B.classify_turn(delta) == "straight"

    @pytest.mark.parametrize("delta", [31, 90, 149])
    def test_right(self, delta):
        assert B.classify_turn(delta) == "right"

    @pytest.mark.parametrize("delta", [-31, -90, -149])
    def test_left(self, delta):
        assert B.classify_turn(delta) == "left"

    @pytest.mark.parametrize("delta", [151, -151, 180])
    def test_u_turn(self, delta):
        assert B.classify_turn(delta) == "u_turn"


class TestTerminalBearing:
    def test_end_bearing_uses_the_final_leg_not_the_chord(self):
        # runs east for a long way, then turns hard north for the last stretch
        line = LineString([(44.80, 41.70), (44.90, 41.70), (44.90, 41.71)])
        assert B.terminal_bearing(line, "end", sample_m=50.0) == pytest.approx(0.0, abs=1.0)

    def test_start_bearing_uses_the_first_leg(self):
        line = LineString([(44.80, 41.70), (44.80, 41.71), (44.90, 41.71)])
        assert B.terminal_bearing(line, "start", sample_m=50.0) == pytest.approx(0.0, abs=1.0)

    def test_short_line_falls_back_to_the_whole_geometry(self):
        line = LineString([(44.80, 41.70), (44.8001, 41.70)])
        assert B.terminal_bearing(line, "end", sample_m=500.0) == pytest.approx(90.0, abs=0.5)

    def test_sampling_smooths_a_noisy_final_vertex(self):
        # a 2 m jitter on the last vertex must not read as a turn
        straight = LineString([(44.80, 41.70), (44.81, 41.70), (44.82, 41.70)])
        jittered = LineString([(44.80, 41.70), (44.81, 41.70), (44.82, 41.700018)])
        assert B.terminal_bearing(jittered, "end", sample_m=200.0) == pytest.approx(
            B.terminal_bearing(straight, "end", sample_m=200.0), abs=2.0
        )


class TestBulkBearings:
    def test_bulk_matches_the_scalar_implementation(self):
        lines = [
            LineString([(44.80, 41.70), (44.81, 41.70), (44.81, 41.71)]),
            LineString([(44.80, 41.70), (44.80, 41.69)]),
            LineString([(44.82, 41.72), (44.81, 41.72), (44.80, 41.73), (44.79, 41.73)]),
        ]
        for at in ("start", "end"):
            bulk = B.terminal_bearings(lines, at)
            scalar = [B.terminal_bearing(line, at) for line in lines]
            assert list(bulk) == pytest.approx(scalar, abs=1e-6)
