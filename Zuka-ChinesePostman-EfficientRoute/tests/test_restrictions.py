"""Parsing OSM `type=restriction` relations (SPEC §3.3).

Nothing is dropped silently: every relation that is not applied leaves a row in
the skip log with its relation id and a machine-readable reason.
"""
from pathlib import Path

import pytest

from efficientroute import restrictions as R

FIXTURE = Path(__file__).parent / "fixtures" / "turns.osm"
NETWORK_WAYS = {1000, 1001, 1002, 1003, 1004}


@pytest.fixture(scope="module")
def parsed():
    return R.parse_restrictions(FIXTURE, NETWORK_WAYS)


def _by_id(parsed):
    return {r.relation_id: r for r in parsed.applicable}


def _skips(parsed):
    return {row["relation_id"]: row["reason"] for row in parsed.skipped}


class TestSimpleNodeVia:
    def test_no_left_turn_is_parsed(self, parsed):
        r = _by_id(parsed)[2000]
        assert (r.kind, r.manoeuvre) == ("no", "left_turn")
        assert r.from_way == 1000
        assert r.to_ways == (1001,)
        assert r.via_nodes == (100,)
        assert r.via_ways == ()

    def test_only_restriction_keeps_its_kind(self, parsed):
        r = _by_id(parsed)[2001]
        assert (r.kind, r.manoeuvre) == ("only", "straight_on")

    def test_no_u_turn_with_from_equal_to_is_parsed(self, parsed):
        r = _by_id(parsed)[2002]
        assert (r.kind, r.manoeuvre) == ("no", "u_turn")
        assert r.from_way == r.to_ways[0] == 1000


class TestViaWay:
    def test_via_way_restriction_is_parsed_not_skipped(self, parsed):
        r = _by_id(parsed)[2003]
        assert r.via_ways == (1002,)
        assert r.via_nodes == ()
        assert r.from_way == 1000 and r.to_ways == (1004,)

    def test_via_way_restrictions_are_counted_separately(self, parsed):
        assert parsed.via_way_count == 1
        # 2000, 2001, 2002, the shift-covering conditional 2009, and 2010/2011,
        # which parse cleanly but cannot be resolved onto arcs (see test_turngraph)
        assert parsed.via_node_count == 6


class TestSkipReasons:
    def test_to_way_outside_the_network_is_logged(self, parsed):
        assert _skips(parsed)[2004] == "member_way_not_in_network"

    def test_hgv_only_restriction_does_not_bind_a_car(self, parsed):
        assert _skips(parsed)[2005] == "not_applicable_to_car"

    def test_except_motorcar_exempts_the_camera_car(self, parsed):
        assert _skips(parsed)[2007] == "not_applicable_to_car"

    def test_relation_without_a_restriction_tag_is_logged(self, parsed):
        assert _skips(parsed)[2008] == "no_restriction_tag"

    def test_every_skip_carries_a_relation_id_and_a_reason(self, parsed):
        for row in parsed.skipped:
            assert isinstance(row["relation_id"], int)
            assert row["reason"]

    def test_nothing_is_both_applied_and_skipped(self, parsed):
        assert not (set(_by_id(parsed)) & set(_skips(parsed)))


class TestConditional:
    def test_condition_narrower_than_the_shift_is_logged_not_applied(self, parsed):
        assert _skips(parsed)[2006] == "conditional_outside_shift"

    def test_condition_covering_the_whole_shift_is_applied(self, parsed):
        r = _by_id(parsed)[2009]
        assert (r.kind, r.manoeuvre) == ("no", "right_turn")
        assert r.conditional


class TestConditionCoverage:
    @pytest.mark.parametrize("cond", ["Mo-Su 00:00-24:00", "24/7", "Mo-Su 08:00-19:00"])
    def test_covers_the_shift(self, cond):
        assert R.condition_covers_shift(cond) is True

    @pytest.mark.parametrize(
        "cond", ["Mo-Fr 07:00-09:00", "Sa-Su 00:00-24:00", "Mo-Su 10:00-16:00", "sunset-sunrise", ""]
    )
    def test_does_not_cover_the_shift(self, cond):
        assert R.condition_covers_shift(cond) is False


class TestCounts:
    def test_totals_add_up(self, parsed):
        assert parsed.found == len(parsed.applicable) + len(parsed.skipped)

    def test_by_type_breakdown_covers_every_applied_restriction(self, parsed):
        assert sum(parsed.by_type.values()) == len(parsed.applicable)
