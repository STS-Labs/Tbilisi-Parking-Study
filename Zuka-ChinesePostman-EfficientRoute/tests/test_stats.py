"""Report statistics, computed on the fixture where every number is checkable."""
from pathlib import Path

import pytest
from shapely.geometry import box

from efficientroute import extract as E
from efficientroute import network as N
from efficientroute import stats as S

FIXTURE = Path(__file__).parent / "fixtures" / "mini.osm"
CLIP = box(44.79, 41.71, 44.81, 41.73)


@pytest.fixture(scope="module")
def bundle():
    ex = E.extract_ways(FIXTURE, CLIP)
    table = N.build_arc_table(ex, sampler=None)
    return table, S.compute(table, ex, meta={})


class TestTotals:
    def test_arc_km_is_the_sum_of_every_directed_arc(self, bundle):
        table, st = bundle
        assert st["totals"]["arc_km"] == pytest.approx(table["length_m"].sum() / 1000.0)

    def test_centerline_counts_each_physical_segment_once(self, bundle):
        table, st = bundle
        unique = table.drop_duplicates(subset=["way_id", "seg_index"])["length_m"].sum()
        assert st["totals"]["centerline_km"] == pytest.approx(unique / 1000.0)

    def test_arc_count_matches_the_table(self, bundle):
        table, st = bundle
        assert st["totals"]["arc_count"] == len(table)


class TestPerClassBreakdown:
    def test_per_class_km_sums_to_arc_km(self, bundle):
        _, st = bundle
        total = sum(row["arc_km"] for row in st["by_class"])
        assert total == pytest.approx(st["totals"]["arc_km"])

    def test_service_is_isolated_as_its_own_line_item(self, bundle):
        _, st = bundle
        assert st["service"]["arc_count"] == 2
        assert st["service"]["highway_class"] == "service"


class TestRequiredTraversal:
    def test_headline_is_computed_over_included_arcs(self, bundle):
        table, st = bundle
        included = table[~table["excluded"]]
        assert st["headline"]["required_traversal_km"] == pytest.approx(
            N.required_traversal_km(included)
        )

    def test_routable_headline_is_never_larger_than_the_included_headline(self, bundle):
        _, st = bundle
        assert (
            st["headline"]["required_traversal_km_routable"]
            <= st["headline"]["required_traversal_km"] + 1e-9
        )

    def test_by_min_passes_km_sums_to_the_headline(self, bundle):
        _, st = bundle
        total = sum(row["required_km"] for row in st["by_min_passes"])
        assert total == pytest.approx(st["headline"]["required_traversal_km"])


class TestOneway:
    def test_oneway_share_by_count_uses_physical_segments(self, bundle):
        _, st = bundle
        # the share is measured over the *included* network: 6 segments survive
        # the drivability filter, and the 2 belonging to way 101 are one-way
        assert st["oneway"]["oneway_segment_count"] == 2
        assert st["oneway"]["segment_count"] == 6
        assert st["oneway"]["share_by_count"] == pytest.approx(1 / 3)

    def test_shares_are_fractions_not_percentages(self, bundle):
        _, st = bundle
        assert 0.0 <= st["oneway"]["share_by_length"] <= 1.0


class TestTaggingCompleteness:
    """Measured over the *included* network.

    Tbilisi's extract carries ~109k footway/track/path arcs that are excluded by
    SPEC §3.1.  Counting them would halve every completeness percentage and would
    put ~108k arcs into the `min_passes = 2` fallback line — a number the stage
    brief uses to decide whether the threshold needs calibrating, so it has to
    describe arcs the campaign will actually drive.
    """

    def test_completeness_is_measured_over_the_included_network(self, bundle):
        table, st = bundle
        included = table[~table["excluded"]]
        assert st["tagging"]["arc_count_basis"] == len(included)
        assert st["tagging"]["lanes_pct"] == pytest.approx(2 / len(included) * 100.0)

    def test_default_fallback_is_reported_with_count_and_km(self, bundle):
        table, st = bundle
        fallback = table[(~table["excluded"]) & (table["min_passes_basis"] == "default")]
        assert st["tagging"]["default_fallback_arc_count"] == len(fallback)
        assert st["tagging"]["default_fallback_km"] == pytest.approx(
            fallback["length_m"].sum() / 1000.0
        )

    def test_excluded_arcs_do_not_leak_into_the_fallback_count(self, bundle):
        table, st = bundle
        excluded_on_default = table[table["excluded"] & (table["min_passes_basis"] == "default")]
        assert len(excluded_on_default) > 0, "fixture must contain the case being guarded against"
        assert st["tagging"]["default_fallback_arc_count"] < len(
            table[table["min_passes_basis"] == "default"]
        )


class TestExclusions:
    def test_every_reason_present_in_the_table_is_reported(self, bundle):
        table, st = bundle
        reported = {row["reason"] for row in st["exclusions"]}
        actual = set(table[table["excluded"]]["exclusion_reason"])
        assert reported == actual

    def test_counts_match(self, bundle):
        _, st = bundle
        by_reason = {row["reason"]: row["arc_count"] for row in st["exclusions"]}
        assert by_reason == {"class_excluded": 2, "access_private": 2, "barrier_blocking": 2}


class TestScc:
    def test_largest_component_arc_count(self, bundle):
        _, st = bundle
        # nodes {1,2,3,5} form the largest component: 7 included arcs sit inside it
        assert st["scc"]["largest_arc_count"] == 7

    def test_orphan_fragments_are_listed_with_size_and_location(self, bundle):
        _, st = bundle
        assert len(st["scc"]["fragments"]) == 1
        fragment = st["scc"]["fragments"][0]
        assert fragment["arc_count"] == 2
        assert "lon" in fragment and "lat" in fragment

    def test_bridge_arcs_are_counted_separately(self, bundle):
        _, st = bundle
        assert st["scc"]["bridge_arc_count"] == 1

    def test_share_of_included_km_is_a_fraction(self, bundle):
        _, st = bundle
        assert 0.0 < st["scc"]["largest_share_of_included_km"] <= 1.0


class TestRestrictions:
    def test_restriction_relation_counts_are_carried_through(self, bundle):
        _, st = bundle
        assert st["restrictions"]["total_in_source"] == 1
        assert st["restrictions"]["touching_clip"] == 1


class TestGradient:
    """SPEC §6 needs gradient; §1.1 forbids using a noisy DEM to remove coverage.

    So a DEM gradient above the drivability limit is *reported*, never excluded —
    which only works if the report actually carries the number.
    """

    def test_gradient_sources_are_counted(self, bundle):
        table, st = bundle
        included = table[~table["excluded"]]
        assert st["gradient"]["tag_count"] == int(
            (included["gradient_source"] == "tag").sum()
        )
        assert st["gradient"]["dem_count"] == int(
            (included["gradient_source"] == "dem").sum()
        )

    def test_arcs_steeper_than_the_drivability_limit_are_reported_not_excluded(self, bundle):
        table, st = bundle
        assert "steep_arc_count" in st["gradient"]
        assert "steep_km" in st["gradient"]
        # nothing was excluded for a DEM gradient
        assert "gradient_too_steep" not in set(table["exclusion_reason"])

    def test_steep_split_by_structure_is_reported(self, bundle):
        _, st = bundle
        assert "steep_on_structure_arc_count" in st["gradient"]


class TestOnewayAudit:
    def test_two_way_link_segments_are_counted(self, bundle):
        _, st = bundle
        assert "two_way_link_segment_count" in st["oneway"]
        assert "two_way_link_km" in st["oneway"]


class TestOrphanComposition:
    def test_orphan_km_is_broken_down_by_class(self, bundle):
        table, st = bundle
        rows = {r["highway_class"]: r["arc_km"] for r in st["scc"]["orphan_by_class"]}
        orphans = table[(~table["excluded"]) & (table["scc_id"] > 0)]
        assert rows == pytest.approx(
            (orphans.groupby("highway_class")["length_m"].sum() / 1000.0).to_dict()
        )


class TestServiceSubtagBreakdown:
    """SPEC §2.1's open question cannot be answered on the parent tag alone."""

    def test_every_service_arc_appears_in_the_breakdown(self, bundle):
        table, st = bundle
        counted = sum(r["arc_count"] for r in st["service"]["by_type"])
        assert counted == int((table["highway_class"] == "service").sum())

    def test_breakdown_required_km_sums_to_the_service_total(self, bundle):
        _, st = bundle
        total = sum(r["required_km"] for r in st["service"]["by_type"])
        assert total == pytest.approx(st["service"]["required_km"])

    def test_untagged_service_ways_are_their_own_line(self, bundle):
        _, st = bundle
        assert "untagged" in {r["service_type"] for r in st["service"]["by_type"]}

    def test_rows_are_sorted_by_required_km_descending(self, bundle):
        _, st = bundle
        values = [r["required_km"] for r in st["service"]["by_type"]]
        assert values == sorted(values, reverse=True)

    def test_share_is_of_the_service_total_not_the_headline(self, bundle):
        _, st = bundle
        shares = [r["share_of_service_required"] for r in st["service"]["by_type"]]
        assert all(0.0 <= s <= 1.0 for s in shares)
