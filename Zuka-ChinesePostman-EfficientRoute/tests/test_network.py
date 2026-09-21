"""Arc-table assembly on a hand-built fixture, where every expected row is known.

Junction nodes in the fixture are {1,2,3,4,5,6,10}; node 9 carries a bollard but
belongs to only one way, so it stays interior and blocks that way instead of
splitting it.
"""
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box

from efficientroute import extract as E
from efficientroute import network as N

FIXTURE = Path(__file__).parent / "fixtures" / "mini.osm"
CLIP = box(44.79, 41.71, 44.81, 41.73)


@pytest.fixture(scope="module")
def table():
    return N.build_arc_table(E.extract_ways(FIXTURE, CLIP), sampler=None)


class TestSplitting:
    def test_way_shared_at_an_interior_node_is_split_there(self, table):
        residential = table[table["way_id"] == 100]
        assert sorted(residential["arc_id"]) == ["100:0:B", "100:0:F", "100:1:B", "100:1:F"]

    def test_barrier_node_does_not_split_a_way(self, table):
        service = table[table["way_id"] == 102]
        assert sorted(service["arc_id"]) == ["102:0:B", "102:0:F"]

    def test_arc_count(self, table):
        assert len(table) == 16


class TestGeometryProvenance:
    def test_forward_geometry_is_the_node_sequence(self, table):
        arc = table[table["arc_id"] == "100:0:F"].iloc[0]
        assert [tuple(round(v, 3) for v in c) for c in arc.geometry.coords] == [
            (44.800, 41.720),
            (44.802, 41.720),
        ]

    def test_backward_geometry_is_the_same_coordinates_reversed(self, table):
        fwd = table[table["arc_id"] == "100:0:F"].iloc[0].geometry
        bwd = table[table["arc_id"] == "100:0:B"].iloc[0].geometry
        assert list(bwd.coords) == list(fwd.coords)[::-1]

    def test_paired_arcs_have_identical_length(self, table):
        fwd = table[table["arc_id"] == "100:0:F"].iloc[0]["length_m"]
        bwd = table[table["arc_id"] == "100:0:B"].iloc[0]["length_m"]
        assert fwd == pytest.approx(bwd)


class TestPasses:
    def test_four_lane_oneway_needs_two_passes(self, table):
        primary = table[table["way_id"] == 101]
        assert set(primary["min_passes"]) == {2}
        assert set(primary["min_passes_basis"]) == {"lanes"}

    def test_untagged_residential_resolves_by_class_not_by_the_default(self, table):
        residential = table[table["way_id"] == 100]
        assert set(residential["min_passes"]) == {1}
        assert set(residential["min_passes_basis"]) == {"class"}

    def test_narrow_two_way_pair_shares_one_requirement(self, table):
        residential = table[table["way_id"] == 100]
        assert set(residential["pair_requirement"]) == {1}

    def test_oneway_arcs_carry_no_shared_pair_requirement(self, table):
        primary = table[table["way_id"] == 101]
        assert set(primary["pair_requirement"]) == {0}
        assert set(primary["pair_id"]) == {""}


class TestDirectionalAttributes:
    def test_tagged_incline_flips_sign_on_the_backward_arc(self, table):
        fwd = table[table["arc_id"] == "107:0:F"].iloc[0]
        bwd = table[table["arc_id"] == "107:0:B"].iloc[0]
        assert fwd["incline"] == pytest.approx(8.0)
        assert bwd["incline"] == pytest.approx(-8.0)

    def test_tagged_incline_is_preferred_over_the_dem(self, table):
        fwd = table[table["arc_id"] == "107:0:F"].iloc[0]
        assert fwd["gradient_pct"] == pytest.approx(8.0)
        assert fwd["gradient_source"] == "tag"

    def test_width_is_recorded_as_the_whole_carriageway(self, table):
        fwd = table[table["arc_id"] == "107:0:F"].iloc[0]
        assert fwd["width"] == pytest.approx(5.5)


class TestExclusions:
    def test_blocking_barrier_excludes_the_way(self, table):
        service = table[table["way_id"] == 102]
        assert set(service["excluded"]) == {True}
        assert set(service["exclusion_reason"]) == {"barrier_blocking"}

    def test_non_drivable_class_excluded(self, table):
        assert set(table[table["way_id"] == 103]["exclusion_reason"]) == {"class_excluded"}

    def test_private_access_excluded(self, table):
        assert set(table[table["way_id"] == 105]["exclusion_reason"]) == {"access_private"}

    def test_excluded_rows_are_kept_in_the_table(self, table):
        assert len(table[table["excluded"]]) == 6

    def test_excluded_arcs_still_carry_min_passes(self, table):
        excluded = table[table["excluded"]]
        assert (excluded["min_passes"] >= 1).all()


class TestDeterminism:
    def test_rows_are_sorted_by_arc_id(self, table):
        assert list(table["arc_id"]) == sorted(table["arc_id"])

    def test_two_builds_produce_identical_frames(self):
        ex = E.extract_ways(FIXTURE, CLIP)
        first = N.build_arc_table(ex, sampler=None)
        second = N.build_arc_table(ex, sampler=None)
        assert first.drop(columns="geometry").equals(second.drop(columns="geometry"))
        assert all(a.equals(b) for a, b in zip(first.geometry, second.geometry))


class TestRequiredTraversalKm:
    def test_narrow_pair_is_counted_once(self, table):
        included = table[~table["excluded"]]
        residential = included[included["way_id"] == 100]
        pair_km = residential["length_m"].sum() / 2000.0  # one direction of two segments
        assert N.required_traversal_km(residential) == pytest.approx(pair_km)

    def test_two_pass_oneway_is_counted_twice(self, table):
        primary = table[table["way_id"] == 101]
        assert N.required_traversal_km(primary) == pytest.approx(
            primary["length_m"].sum() * 2 / 1000.0
        )


class TestGradientWithoutADem:
    def test_missing_sampler_leaves_gradient_unset(self, table):
        untagged = table[table["way_id"] == 100]
        assert np.isnan(untagged["gradient_pct"]).all()
        assert set(untagged["gradient_source"]) == {"none"}


class TestStreetName:
    def test_name_tag_is_carried_onto_the_arc(self, table):
        arc = table[table["arc_id"] == "100:0:F"].iloc[0]
        assert arc["name"] == "Test Residential"

    def test_unnamed_way_gets_an_empty_name_not_a_null(self, table):
        arc = table[table["arc_id"] == "101:0:F"].iloc[0]
        assert arc["name"] == ""


class TestStructure:
    def test_bridge_is_recorded(self, table):
        assert table[table["arc_id"] == "106:0:F"].iloc[0]["structure"] == "bridge"

    def test_plain_street_has_no_structure(self, table):
        assert table[table["arc_id"] == "100:0:F"].iloc[0]["structure"] == ""


class TestServiceType:
    def test_service_way_without_a_subtag_reads_untagged(self, table):
        arc = table[table["arc_id"] == "102:0:F"].iloc[0]
        assert arc["highway_class"] == "service"
        assert arc["service_type"] == "untagged"

    def test_non_service_arcs_carry_null(self, table):
        arc = table[table["arc_id"] == "100:0:F"].iloc[0]
        assert arc["service_type"] is None

    def test_service_type_is_set_for_every_service_arc(self, table):
        service = table[table["highway_class"] == "service"]
        assert service["service_type"].notna().all()

    def test_service_type_is_null_for_every_other_arc(self, table):
        rest = table[table["highway_class"] != "service"]
        assert rest["service_type"].isna().all()
