"""PBF -> ways, node coordinates, barrier nodes, restriction count."""
from pathlib import Path

import pytest
from shapely.geometry import box

from efficientroute import extract as E

FIXTURE = Path(__file__).parent / "fixtures" / "mini.osm"
CLIP = box(44.79, 41.71, 44.81, 41.73)


@pytest.fixture(scope="module")
def mini():
    return E.extract_ways(FIXTURE, CLIP)


class TestWaySelection:
    def test_keeps_highway_ways_inside_the_clip(self, mini):
        assert set(mini.ways) == {100, 101, 102, 103, 105, 106, 107}

    def test_drops_ways_outside_the_clip_with_a_reason(self, mini):
        assert 104 not in mini.ways
        reasons = {d["way_id"]: d["reason"] for d in mini.dropped_ways}
        assert reasons.get(104) == "outside_clip"

    def test_keeps_non_drivable_classes_for_the_exclusion_report(self, mini):
        # SPEC §3.1 exclusions are reported, not silently skipped
        assert mini.ways[103].tags["highway"] == "footway"

    def test_records_tags_and_node_refs(self, mini):
        way = mini.ways[100]
        assert way.node_ids == [1, 2, 3]
        assert way.tags["highway"] == "residential"


class TestNodes:
    def test_records_coordinates_for_every_referenced_node(self, mini):
        needed = {n for w in mini.ways.values() for n in w.node_ids}
        assert needed <= set(mini.node_lonlat)

    def test_coordinates_are_lon_lat(self, mini):
        lon, lat = mini.node_lonlat[1]
        assert (round(lon, 3), round(lat, 3)) == (44.800, 41.720)


class TestBarriers:
    def test_blocking_barrier_node_is_recorded(self, mini):
        assert 9 in mini.blocking_barrier_nodes

    def test_unlocked_gate_is_not_a_blocker(self, mini):
        assert 10 not in mini.blocking_barrier_nodes


class TestRestrictionRelations:
    def test_counts_type_restriction_only(self, mini):
        assert mini.restriction_relations_total == 1

    def test_counts_restrictions_touching_the_kept_ways(self, mini):
        assert mini.restriction_relations_in_clip == 1
