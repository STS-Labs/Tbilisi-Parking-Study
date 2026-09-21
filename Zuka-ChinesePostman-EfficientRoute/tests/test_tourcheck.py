"""Stage 3 — the invariant suite, tested against tours known to be wrong.

Written before the solver (per the Stage 3 process note).  A checker that has
only ever seen valid input proves nothing, so every test here feeds it a tour
that is broken in exactly one way and asserts which invariant notices.
"""
import dataclasses

import numpy as np
import pytest
import toygraph

from efficientroute import tourcheck as TC


@pytest.fixture
def square():
    return toygraph.square()


@pytest.fixture
def pair_square():
    return toygraph.pair_square()


class TestValidTour:
    def test_the_obvious_lap_passes_every_invariant(self, square):
        g, star = square
        result = TC.audit([0, 1, 2, 3], star, g)
        assert result.ok, [(c.name, c.detail) for c in result.failures]

    def test_the_named_invariants_are_all_actually_run(self, square):
        g, star = square
        names = {c.name for c in TC.audit([0, 1, 2, 3], star, g).checks}
        assert {"I1", "I2", "I6", "closed", "lower_bounds"} <= names

    def test_a_second_lap_still_passes_but_costs_more(self, square):
        g, star = square
        once = TC.audit([0, 1, 2, 3], star, g)
        twice = TC.audit([0, 1, 2, 3, 0, 1, 2, 3], star, g)
        assert twice.ok
        assert twice.total_s > once.total_s

    def test_starting_the_lap_elsewhere_is_the_same_tour(self, square):
        g, star = square
        a = TC.audit([0, 1, 2, 3], star, g)
        b = TC.audit([2, 3, 0, 1], star, g)
        assert b.ok and b.total_s == pytest.approx(a.total_s)


class TestI2:
    def test_an_illegal_manoeuvre_is_caught(self, square):
        """0 -> 2 skips an arc; L has no such edge."""
        g, star = square
        result = TC.audit([0, 2, 3], star, g)
        assert not result.ok
        assert [c.name for c in result.failures if c.name == "I2"]

    def test_the_failure_says_where(self, square):
        g, star = square
        check = TC.check_i2_manoeuvres_are_legal(np.array([0, 2, 3]), g)
        assert not check.passed and "0 -> 2" in check.detail

    def test_a_legal_looking_reversal_is_still_caught(self, square):
        """Nothing in L lets the car turn round; the check must not assume it can."""
        g, star = square
        assert not TC.check_i2_manoeuvres_are_legal(np.array([0, 1, 0, 1]), g).passed

    def test_a_single_arc_tour_has_no_manoeuvres_to_be_legal(self, square):
        g, star = square
        assert not TC.check_i2_manoeuvres_are_legal(np.array([0]), g).passed


class TestClosure:
    def test_an_open_walk_is_caught(self, square):
        """0 -> 1 -> 2 is a legal walk but 2 -> 0 does not exist, so it never closes."""
        g, star = square
        check = TC.check_closed(np.array([0, 1, 2]), g)
        assert not check.passed and "close" in check.detail

    def test_closure_is_checked_by_the_wraparound_not_by_the_endpoints(self, square):
        g, star = square
        assert TC.check_closed(np.array([0, 1, 2, 3]), g).passed
        assert not TC.check_closed(np.array([1, 2, 3]), g).passed

    def test_the_audit_reports_closure_separately_from_i2(self, square):
        g, star = square
        result = TC.audit([0, 1, 2], star, g)
        failed = {c.name for c in result.failures}
        assert "closed" in failed


class TestI1:
    def test_a_missing_arc_is_caught(self, square):
        g, star = square
        counts = TC.visit_counts([0, 1, 2], star)
        check = TC.check_i1_coverage(counts, star)
        assert not check.passed and "min_passes" in check.detail

    def test_a_second_required_pass_is_enforced(self, square):
        g, star = square
        star = dataclasses.replace(star, min_passes=np.array([2, 1, 1, 1]))
        assert not TC.check_i1_coverage(TC.visit_counts([0, 1, 2, 3], star), star).passed
        assert TC.check_i1_coverage(TC.visit_counts([0, 1, 2, 3, 0], star), star).passed

    def test_covering_either_direction_satisfies_a_narrow_pair(self, pair_square):
        """SPEC §2.1 row 3 — the requirement is on the pair, not on the arc."""
        g, star = pair_square
        forward = TC.check_i1_coverage(TC.visit_counts([0, 2, 3], star), star)
        backward = TC.check_i1_coverage(TC.visit_counts([1, 2, 3], star), star)
        assert forward.passed and backward.passed

    def test_covering_neither_direction_fails(self, pair_square):
        g, star = pair_square
        check = TC.check_i1_coverage(TC.visit_counts([2, 3], star), star)
        assert not check.passed and "narrow pair" in check.detail

    def test_i1_is_spec_level_while_lower_bounds_is_solver_level(self, pair_square):
        """Driving the unoriented direction covers the street but not the flow's plan."""
        g, star = pair_square
        counts = TC.visit_counts([1, 2, 3], star)
        assert TC.check_i1_coverage(counts, star).passed
        assert not TC.check_lower_bounds_met(counts, star).passed


class TestI6:
    def test_a_node_outside_the_graph_is_caught(self, square):
        g, star = square
        check = TC.check_i6_nodes_exist(np.array([0, 1, 99]), star)
        assert not check.passed and "not L-nodes" in check.detail

    def test_a_negative_index_is_caught(self, square):
        g, star = square
        assert not TC.check_i6_nodes_exist(np.array([0, -1]), star).passed

    def test_an_empty_tour_is_caught_before_anything_else_runs(self, square):
        g, star = square
        result = TC.audit([], star, g)
        assert not result.ok
        assert result.checks[0].name == "I6"


class TestCostRecomputation:
    def test_the_cost_matches_a_hand_calculation(self, square):
        """4 required captures at 100 s + 4 manoeuvres at 5 s = 420 s."""
        g, star = square
        result = TC.audit([0, 1, 2, 3], star, g)
        assert result.capture_s == pytest.approx(400.0)
        assert result.turn_s == pytest.approx(20.0)
        assert result.deadhead_s == pytest.approx(0.0)
        assert result.total_s == pytest.approx(420.0)

    def test_a_repeat_pass_is_priced_as_deadhead_not_capture(self, square):
        """SPEC §6 — only *required* traversals are capped, so extras are cheaper."""
        g, star = square
        result = TC.audit([0, 1, 2, 3, 0, 1, 2, 3], star, g)
        assert result.capture_s == pytest.approx(400.0)
        assert result.deadhead_s == pytest.approx(320.0)   # 4 x 80, not 4 x 100
        assert result.turn_s == pytest.approx(40.0)

    def test_an_unrequired_arc_is_entirely_deadhead(self, pair_square):
        """Arc 1 is the unoriented half of the pair, so its lower bound is 0 and
        its single visit is deadhead — as is the second visit of 2 and of 3."""
        g, star = pair_square
        result = TC.audit([0, 2, 3, 1, 2, 3], star, g)
        assert result.capture_s == pytest.approx(3 * 100.0)   # arcs 0, 2, 3 once each
        assert result.deadhead_s == pytest.approx(3 * 80.0)   # arc 1, plus 2 and 3 again

    def test_cost_is_not_reported_for_an_illegal_tour(self, square):
        g, star = square
        result = TC.audit([0, 2, 3], star, g)
        assert np.isnan(result.total_s)


class TestMatchesFlow:
    def test_a_tour_that_drops_an_edge_is_caught(self, square):
        g, star = square
        flow = np.zeros(star.n_edges, dtype="int64")
        flow[:4] = 1          # the flow paid for one capture pass of each arc
        counts = TC.visit_counts([0, 1, 2], star)
        check = TC.check_matches_flow(counts, flow, star)
        assert not check.passed and "differ from the flow" in check.detail

    def test_a_faithful_tour_passes(self, square):
        g, star = square
        flow = np.zeros(star.n_edges, dtype="int64")
        flow[:4] = 1
        assert TC.check_matches_flow(TC.visit_counts([0, 1, 2, 3], star), flow, star).passed

    def test_deadhead_flow_counts_towards_the_expected_visits(self, square):
        g, star = square
        flow = np.zeros(star.n_edges, dtype="int64")
        flow[:4] = 1
        flow[4:8] = 1         # one extra deadhead pass of each arc
        counts = TC.visit_counts([0, 1, 2, 3, 0, 1, 2, 3], star)
        assert TC.check_matches_flow(counts, flow, star).passed


class TestRaise:
    def test_a_failed_audit_raises_with_every_reason(self, square):
        g, star = square
        with pytest.raises(AssertionError) as excinfo:
            TC.audit([0, 2, 3], star, g).raise_if_failed()
        assert "I2" in str(excinfo.value)

    def test_a_passing_audit_does_not_raise(self, square):
        g, star = square
        TC.audit([0, 1, 2, 3], star, g).raise_if_failed()
