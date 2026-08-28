"""Stage 4 item 1 — partitioning into shift-sized zones."""
import numpy as np
import pytest
import toygraph

from efficientroute import zoning


@pytest.fixture
def ring():
    return toygraph.zone_ring(12)


@pytest.fixture
def line():
    return toygraph.zone_line(8)


class TestZoneGraph:
    def test_one_segment_per_physical_street_piece(self, ring):
        g, zg = ring
        assert zg.n_segments == 12

    def test_both_directions_of_a_street_land_on_one_segment(self):
        """Splitting a two-way street across zones would manufacture deadhead."""
        g, star = toygraph.pair_square()
        keep = np.ones(4, dtype=bool)
        zg = zoning.build(g, keep, np.full(4, 100.0), np.full(4, 500.0))
        assert zg.n_segments == 3, "the pair's two arcs are one segment"
        assert zg.segment_of_node[0] == zg.segment_of_node[1]

    def test_a_narrow_pair_is_weighted_for_one_traversal_not_two(self):
        g, _ = toygraph.pair_square()
        zg = zoning.build(g, np.ones(4, dtype=bool), np.full(4, 100.0), np.full(4, 500.0))
        pair = zg.segment_of_node[0]
        assert zg.weight_s[pair] == pytest.approx(100.0)

    def test_out_of_scope_nodes_are_excluded(self, ring):
        g, _ = ring
        keep = np.ones(12, dtype=bool)
        keep[3] = False
        zg = zoning.build(g, keep, np.full(12, 600.0), np.full(12, 1000.0))
        assert zg.n_segments == 11
        assert zg.segment_of_node[3] == -1

    def test_adjacency_follows_legal_manoeuvres(self, ring):
        g, zg = ring
        for segment in range(zg.n_segments):
            assert len(zg.neighbours(segment)) == 2, "a ring segment has two neighbours"

    def test_length_is_counted_once_per_piece(self, ring):
        g, zg = ring
        assert zg.length_m.sum() == pytest.approx(12 * 1000.0)

    def test_the_total_weight_is_the_capture_time(self, ring):
        g, zg = ring
        assert zg.total_weight_s == pytest.approx(12 * 600.0)


class TestPartition:
    def test_it_returns_one_label_per_segment(self, ring):
        g, zg = ring
        labels = zoning.partition(zg, 3)
        assert len(labels) == zg.n_segments
        assert len(np.unique(labels)) == 3

    def test_a_single_part_is_the_whole_network(self, ring):
        g, zg = ring
        assert zoning.partition(zg, 1).tolist() == [0] * 12

    def test_zero_parts_is_an_error(self, ring):
        g, zg = ring
        with pytest.raises(ValueError, match="at least one part"):
            zoning.partition(zg, 0)

    def test_parts_are_connected(self, ring):
        g, zg = ring
        labels = zoning.partition(zg, 4)
        assert zoning.disconnected_zones(zg, labels) == {}

    def test_the_partition_is_reproducible(self, ring):
        """CLAUDE.md rule 5 — METIS is seeded."""
        g, zg = ring
        assert zoning.partition(zg, 4).tolist() == zoning.partition(zg, 4).tolist()


class TestConnectivity:
    def test_a_connected_set_is_recognised(self, line):
        g, zg = line
        assert zoning.is_connected(zg, np.array([2, 3, 4]))

    def test_a_split_set_is_recognised(self, line):
        g, zg = line
        assert not zoning.is_connected(zg, np.array([0, 1, 5, 6]))

    def test_a_single_segment_is_connected(self, line):
        g, zg = line
        assert zoning.is_connected(zg, np.array([3]))

    def test_components_are_returned_largest_first(self, line):
        g, zg = line
        pieces = zoning.components_of(zg, np.array([0, 1, 2, 5]))
        assert [len(p) for p in pieces] == [3, 1]

    def test_a_stranded_fragment_is_reattached_to_the_zone_it_touches(self, line):
        g, zg = line
        labels = np.array([0, 0, 0, 1, 1, 0, 0, 0])   # zone 0 is in two pieces
        assert zoning.disconnected_zones(zg, labels) == {0: 2}
        repaired, moved = zoning.repair_connectivity(zg, labels)
        assert zoning.disconnected_zones(zg, repaired) == {}
        assert moved == 3

    def test_repair_leaves_a_healthy_partition_alone(self, line):
        g, zg = line
        labels = np.array([0, 0, 0, 0, 1, 1, 1, 1])
        repaired, moved = zoning.repair_connectivity(zg, labels)
        assert moved == 0
        assert repaired.tolist() == labels.tolist()


class TestArticulationPoints:
    def test_every_interior_segment_of_a_line_is_one(self, line):
        g, zg = line
        points = zoning.articulation_points(zg, np.arange(8))
        assert points == {1, 2, 3, 4, 5, 6}

    def test_a_ring_has_none(self, ring):
        g, zg = ring
        assert zoning.articulation_points(zg, np.arange(12)) == set()

    def test_removing_a_non_articulation_point_keeps_the_zone_whole(self, line):
        g, zg = line
        members = np.arange(8)
        for segment in sorted(set(members.tolist()) - zoning.articulation_points(zg, members)):
            rest = members[members != segment]
            assert zoning.is_connected(zg, rest)


class TestDurations:
    def test_a_day_is_capture_times_overhead_plus_legs_plus_break(self, ring):
        g, zg = ring
        labels = np.zeros(12, dtype="int64")
        legs = np.full(12, 600.0)
        hours = zoning.zone_durations(
            zg, labels, np.array([0]), legs, legs, 2.0, 0.75
        )
        # 12 x 600 s capture x 2.0 + (600 + 600) s of legs + 0.75 h
        assert hours[0] == pytest.approx(12 * 600 / 3600 * 2.0 + 1200 / 3600 + 0.75)

    def test_the_leg_is_the_cheapest_way_in_not_the_average(self, ring):
        g, zg = ring
        labels = np.zeros(12, dtype="int64")
        legs = np.full(12, 3600.0)
        legs[5] = 60.0
        hours = zoning.zone_durations(zg, labels, np.array([0]), legs, legs, 1.0, 0.0)
        assert hours[0] == pytest.approx(12 * 600 / 3600 + 2 * 60 / 3600)

    def test_the_commute_allowance_reserves_room_in_proportion_to_the_leg(self, ring):
        g, zg = ring
        labels = np.zeros(12, dtype="int64")
        legs = np.full(12, 1800.0)
        plain = zoning.zone_durations(zg, labels, np.array([0]), legs, legs, 1.0, 0.0)
        reserved = zoning.zone_durations(
            zg, labels, np.array([0]), legs, legs, 1.0, 0.0, commute_allowance=0.5
        )
        assert reserved[0] - plain[0] == pytest.approx(0.5 * 2 * 1800 / 3600)

    def test_an_unreachable_zone_contributes_no_leg_rather_than_infinity(self, ring):
        g, zg = ring
        labels = np.zeros(12, dtype="int64")
        legs = np.full(12, np.inf)
        assert np.isfinite(zoning.zone_durations(zg, labels, np.array([0]), legs, legs, 1.0, 0.0)).all()

    def test_the_overhead_excludes_the_depot_legs(self, ring):
        """The multiplier is intra-zone; the legs sit beside it, not inside it.

        Stage 5 reports a solved day as `route_h`, which *includes* both depot
        legs.  Dividing that by capture and feeding the result back here charges
        the legs twice — once inside the multiplier, once again in the `legs`
        term — and the day is over-predicted by exactly one leg pair.  That was
        the Stage 4c defect: `ZONE_OVERHEAD_MEASURED = 2.55` was taken from
        `route_h / capture_h`, so every zone was sized against a day about
        1.2 h longer than the one Stage 5 actually drives, and every zone came
        out correspondingly too small.
        """
        g, zg = ring
        labels = np.zeros(12, dtype="int64")
        legs = np.full(12, 1800.0)
        capture_h = 12 * 600 / 3600
        legs_h = 2 * 1800 / 3600
        intra_zone = 2.1  # what the solver spends inside the zone, per capture hour
        driven_h = capture_h * intra_zone + legs_h

        right = zoning.zone_durations(
            zg, labels, np.array([0]), legs, legs, intra_zone, 0.0
        )
        assert right[0] == pytest.approx(driven_h), (
            "a leg-excluded overhead reproduces the day the solver drives"
        )

        including_legs = driven_h / capture_h
        wrong = zoning.zone_durations(
            zg, labels, np.array([0]), legs, legs, including_legs, 0.0
        )
        assert wrong[0] - right[0] == pytest.approx(legs_h), (
            "a leg-included overhead charges the depot legs a second time"
        )


class TestRebalance:
    def test_it_never_returns_something_worse_than_it_was_given(self, ring):
        g, zg = ring
        labels = np.array([0] * 10 + [1] * 2)
        legs = np.zeros(12)
        before = zoning.zone_durations(zg, labels, np.array([0, 1]), legs, legs, 1.0, 0.0)
        result = zoning.rebalance(zg, labels, legs, legs, 1.0, 0.0, 24.0)
        after = zoning.zone_durations(
            zg, result.labels, np.unique(result.labels), legs, legs, 1.0, 0.0
        )
        assert after.std() <= before.std() + 1e-9

    def test_it_evens_out_a_lopsided_split(self, ring):
        g, zg = ring
        labels = np.array([0] * 10 + [1] * 2)
        result = zoning.rebalance(zg, labels, np.zeros(12), np.zeros(12), 1.0, 0.0, 24.0)
        counts = np.bincount(result.labels)
        assert abs(counts[0] - counts[1]) <= 2

    def test_it_keeps_every_zone_connected(self, ring):
        g, zg = ring
        labels = np.array([0] * 10 + [1] * 2)
        result = zoning.rebalance(zg, labels, np.zeros(12), np.zeros(12), 1.0, 0.0, 24.0)
        assert zoning.disconnected_zones(zg, result.labels) == {}

    def test_it_never_pushes_a_receiving_zone_over_the_window(self):
        """Reducing the spread by creating a new overrun is not an improvement.

        Zone 0 starts over the window and cannot be rescued: every segment it
        could shed would put zone 1 over instead. The pass must leave it alone
        rather than move the problem.
        """
        g, zg = toygraph.zone_ring(12)
        labels = np.array([0] * 8 + [1] * 4)
        legs = np.zeros(12)
        window = 0.75          # zone 1 holds 4 x 600 s = 0.667 h and has 0.083 h of room
        result = zoning.rebalance(zg, labels, legs, legs, 1.0, 0.0, window)
        after = zoning.zone_durations(
            zg, result.labels, np.unique(result.labels), legs, legs, 1.0, 0.0
        )
        assert after[1] <= window + 1e-9, "the receiving zone was pushed over"
        assert result.moves == 0, "no move was available that respected the window"

    def test_it_is_reproducible(self, ring):
        g, zg = ring
        labels = np.array([0] * 10 + [1] * 2)
        a = zoning.rebalance(zg, labels, np.zeros(12), np.zeros(12), 1.0, 0.0, 24.0)
        b = zoning.rebalance(zg, labels, np.zeros(12), np.zeros(12), 1.0, 0.0, 24.0)
        assert a.labels.tolist() == b.labels.tolist()


class TestSolveAndChoose:
    def test_it_finds_a_count_that_fits(self, ring):
        g, zg = ring
        legs = np.zeros(12)
        plan = zoning.choose_zone_count(zg, legs, legs, 1.0, 0.0, 1.0)
        assert plan.feasible
        assert plan.durations_h.max() <= 1.0 + 1e-9

    def test_it_uses_the_fewest_days_that_work(self, ring):
        g, zg = ring
        legs = np.zeros(12)
        # 12 x 600 s = 2 h of capture; a 1 h window needs at least two days
        plan = zoning.choose_zone_count(zg, legs, legs, 1.0, 0.0, 1.0)
        assert plan.n_zones == 2

    def test_an_impossible_window_raises_rather_than_looping(self, ring):
        g, zg = ring
        legs = np.full(12, 36000.0)
        with pytest.raises(RuntimeError, match="fits a"):
            zoning.choose_zone_count(zg, legs, legs, 1.0, 0.0, 0.5, max_iterations=3)

    def test_the_plan_reports_which_weighting_won(self, ring):
        g, zg = ring
        legs = np.zeros(12)
        plan = zoning.choose_zone_count(zg, legs, legs, 1.0, 0.0, 1.0)
        assert plan.weighting in {"capture", "leg_amortised", "leg_fixed_point"}
