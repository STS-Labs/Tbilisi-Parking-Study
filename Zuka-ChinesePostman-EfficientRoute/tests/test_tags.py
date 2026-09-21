"""OSM tag parsing — the fallback chain in SPEC §1.1 is only as good as this."""
import math

import pytest

from efficientroute import tags as T


class TestParseOneway:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ({"oneway": "yes"}, "yes"),
            ({"oneway": "true"}, "yes"),
            ({"oneway": "1"}, "yes"),
            ({"oneway": "-1"}, "-1"),
            ({"oneway": "reverse"}, "-1"),
            ({"oneway": "no"}, "no"),
            ({"oneway": "false"}, "no"),
            ({"oneway": "0"}, "no"),
            ({}, "no"),
        ],
    )
    def test_explicit_and_absent(self, raw, expected):
        assert T.parse_oneway(raw) == expected

    def test_roundabout_implies_oneway(self):
        assert T.parse_oneway({"junction": "roundabout"}) == "yes"

    def test_motorway_implies_oneway(self):
        assert T.parse_oneway({"highway": "motorway"}) == "yes"

    def test_explicit_oneway_no_beats_motorway_implication(self):
        assert T.parse_oneway({"highway": "motorway", "oneway": "no"}) == "no"


class TestParseLanes:
    def test_plain_total(self):
        assert T.parse_lanes({"lanes": "4"}) == 4

    def test_absent(self):
        assert T.parse_lanes({}) is None

    def test_unparseable_is_none(self):
        assert T.parse_lanes({"lanes": "two"}) is None

    def test_zero_is_rejected(self):
        assert T.parse_lanes({"lanes": "0"}) is None

    def test_decimal_lanes_round_up(self):
        # lanes=1.5 exists in OSM; accuracy-first rounds toward the wider street
        assert T.parse_lanes({"lanes": "1.5"}) == 2


class TestDirectionalLanes:
    def test_oneway_uses_total(self):
        assert T.directional_lanes({"lanes": "4", "oneway": "yes"}, "forward") == 4

    def test_twoway_halves_total_rounding_up(self):
        assert T.directional_lanes({"lanes": "4"}, "forward") == 2
        assert T.directional_lanes({"lanes": "3"}, "forward") == 2

    def test_explicit_forward_backward_wins(self):
        raw = {"lanes": "4", "lanes:forward": "3", "lanes:backward": "1"}
        assert T.directional_lanes(raw, "forward") == 3
        assert T.directional_lanes(raw, "backward") == 1

    def test_absent(self):
        assert T.directional_lanes({}, "forward") is None


class TestParseWidth:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("8", 8.0),
            ("8.5", 8.5),
            ("8.5 m", 8.5),
            ("8.5m", 8.5),
            ("3;4", 4.0),  # ambiguous -> widest, per SPEC §1.1
        ],
    )
    def test_metric(self, raw, expected):
        assert T.parse_width({"width": raw}) == pytest.approx(expected)

    def test_feet_and_inches(self):
        assert T.parse_width({"width": "26'"}) == pytest.approx(7.9248, abs=1e-3)

    @pytest.mark.parametrize("raw", ["narrow", "", "-3", "0"])
    def test_rejected(self, raw):
        assert T.parse_width({"width": raw}) is None

    def test_absent(self):
        assert T.parse_width({}) is None


class TestDirectionalWidth:
    def test_oneway_width_is_the_whole_carriageway(self):
        assert T.directional_width({"width": "12", "oneway": "yes"}) == pytest.approx(12.0)

    def test_twoway_width_is_halved(self):
        assert T.directional_width({"width": "12"}) == pytest.approx(6.0)


class TestParseMaxspeed:
    @pytest.mark.parametrize(
        "raw,expected",
        [("50", 50.0), ("50 km/h", 50.0), ("50km/h", 50.0), ("30 mph", 48.2803)],
    )
    def test_parsed(self, raw, expected):
        assert T.parse_maxspeed({"maxspeed": raw}) == pytest.approx(expected, abs=1e-3)

    @pytest.mark.parametrize("raw", ["none", "walk", "signals", "GE:urban", ""])
    def test_non_numeric_is_none(self, raw):
        assert T.parse_maxspeed({"maxspeed": raw}) is None


class TestParseIncline:
    @pytest.mark.parametrize(
        "raw,expected", [("10%", 10.0), ("-7.5%", -7.5), ("10", 10.0), ("+6%", 6.0)]
    )
    def test_percent(self, raw, expected):
        assert T.parse_incline({"incline": raw}) == pytest.approx(expected)

    def test_degrees_convert_to_percent(self):
        assert T.parse_incline({"incline": "5°"}) == pytest.approx(
            math.tan(math.radians(5)) * 100, abs=1e-6
        )

    @pytest.mark.parametrize("raw", ["up", "down", "steep", ""])
    def test_qualitative_is_none(self, raw):
        assert T.parse_incline({"incline": raw}) is None

    def test_absent(self):
        assert T.parse_incline({}) is None


class TestParseServiceType:
    """SPEC §2.1 leaves `highway=service` open, but `service` is a bag of unrelated
    things: an alley is a street, a driveway is not. The decision needs the subtag."""

    def test_tagged_subtype_is_returned_raw(self):
        assert T.parse_service_type({"highway": "service", "service": "alley"}) == "alley"
        assert T.parse_service_type({"highway": "service", "service": "driveway"}) == "driveway"
        assert T.parse_service_type({"highway": "service", "service": "parking_aisle"}) == "parking_aisle"

    def test_service_way_without_the_subtag_is_untagged_not_null(self):
        assert T.parse_service_type({"highway": "service"}) == "untagged"

    def test_blank_subtag_counts_as_untagged(self):
        assert T.parse_service_type({"highway": "service", "service": "  "}) == "untagged"

    def test_value_is_normalised_but_not_reclassified(self):
        assert T.parse_service_type({"highway": "service", "service": "Driveway"}) == "driveway"

    @pytest.mark.parametrize("cls", ["residential", "primary", "footway", "track"])
    def test_non_service_ways_are_null(self, cls):
        assert T.parse_service_type({"highway": cls}) is None

    def test_service_subtag_on_a_non_service_way_is_ignored(self):
        # `service=driveway` appears on non-service ways in OSM; it is not our column
        assert T.parse_service_type({"highway": "residential", "service": "driveway"}) is None
