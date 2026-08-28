"""Way -> junction-split segments -> directed arcs. No invented geometry (CLAUDE.md rule 1)."""
import pytest
from shapely.geometry import LineString

from efficientroute import arcs as A


class TestJunctionNodes:
    def test_shared_interior_node_is_a_junction(self):
        ways = {10: [1, 2, 3], 11: [4, 2, 5]}
        assert 2 in A.find_junction_nodes(ways)

    def test_way_endpoints_are_always_junctions(self):
        ways = {10: [1, 2, 3]}
        j = A.find_junction_nodes(ways)
        assert {1, 3} <= j

    def test_unshared_interior_node_is_not_a_junction(self):
        ways = {10: [1, 2, 3]}
        assert 2 not in A.find_junction_nodes(ways)

    def test_repeated_node_within_one_way_is_a_junction(self):
        # a self-touching way must be split there or the graph loses a connection
        ways = {10: [1, 2, 3, 2, 4]}
        assert 2 in A.find_junction_nodes(ways)


class TestSplitWay:
    def test_splits_at_interior_junction(self):
        assert A.split_way_into_segments([1, 2, 3, 4, 5], {1, 3, 5}) == [[1, 2, 3], [3, 4, 5]]

    def test_no_interior_junction_yields_one_segment(self):
        assert A.split_way_into_segments([1, 2, 3], {1, 3}) == [[1, 2, 3]]

    def test_closed_way_stays_whole_when_only_its_tip_is_a_junction(self):
        assert A.split_way_into_segments([1, 2, 3, 1], {1}) == [[1, 2, 3, 1]]

    def test_consecutive_duplicate_nodes_are_collapsed(self):
        assert A.split_way_into_segments([1, 2, 2, 3], {1, 3}) == [[1, 2, 3]]

    def test_degenerate_way_yields_no_segments(self):
        assert A.split_way_into_segments([1, 1], {1}) == []
        assert A.split_way_into_segments([1], {1}) == []


class TestDirectedArcs:
    def test_oneway_yields_a_single_forward_arc(self):
        got = A.directed_arcs(way_id=7, seg_index=0, node_ids=[1, 2, 3], oneway="yes")
        assert len(got) == 1
        arc = got[0]
        assert (arc.arc_id, arc.from_node, arc.to_node, arc.pair_id) == ("7:0:F", 1, 3, "")
        assert arc.node_ids == [1, 2, 3]

    def test_reverse_oneway_yields_a_single_backward_arc(self):
        got = A.directed_arcs(way_id=7, seg_index=0, node_ids=[1, 2, 3], oneway="-1")
        assert len(got) == 1
        arc = got[0]
        assert (arc.arc_id, arc.from_node, arc.to_node) == ("7:0:B", 3, 1)
        assert arc.node_ids == [3, 2, 1]

    def test_twoway_yields_a_paired_forward_and_backward_arc(self):
        got = A.directed_arcs(way_id=7, seg_index=1, node_ids=[1, 2, 3], oneway="no")
        assert [a.arc_id for a in got] == ["7:1:F", "7:1:B"]
        assert [a.pair_id for a in got] == ["7:1", "7:1"]
        assert (got[0].from_node, got[0].to_node) == (1, 3)
        assert (got[1].from_node, got[1].to_node) == (3, 1)

    def test_arc_ids_are_unique_across_segments_of_one_way(self):
        a0 = A.directed_arcs(7, 0, [1, 2], "no")
        a1 = A.directed_arcs(7, 1, [2, 3], "no")
        assert len({a.arc_id for a in a0 + a1}) == 4


class TestGeodesicLength:
    def test_one_hundredth_degree_of_latitude(self):
        line = LineString([(44.80, 41.70), (44.80, 41.71)])
        assert A.geodesic_length_m(line) == pytest.approx(1109.0, rel=2e-3)

    def test_length_is_direction_independent(self):
        fwd = LineString([(44.80, 41.70), (44.81, 41.71)])
        rev = LineString(list(fwd.coords)[::-1])
        assert A.geodesic_length_m(fwd) == pytest.approx(A.geodesic_length_m(rev))

    def test_multi_vertex_length_is_the_sum_of_its_parts(self):
        whole = LineString([(44.80, 41.70), (44.80, 41.705), (44.80, 41.71)])
        assert A.geodesic_length_m(whole) == pytest.approx(1109.0, rel=2e-3)
