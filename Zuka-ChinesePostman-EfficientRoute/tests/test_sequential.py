"""Stage 8's credit arithmetic, on arrays small enough to check by hand.

The gate asserts the campaign artifact is sound. These assert the pieces are sound
for reasons, on inputs where the right answer is obvious by inspection — so a
failure points at a line rather than at a 47-day plan.
"""
import numpy as np
import pytest

from efficientroute import config as C
from efficientroute import coverage, sequential


class TestTheSharedCreditRule:
    """§1 — one implementation, two callers. These pin the rule itself."""

    def test_a_slow_pass_counts(self):
        fast = C.COVERAGE_SPEED_MAX_KMH - 1.0
        assert sequential and coverage.qualifies(
            coverage.Pass("a", speed_kmh=fast), "full") == "counted"

    def test_a_fast_pass_does_not(self):
        over = C.COVERAGE_SPEED_MAX_KMH + 1.0
        assert coverage.qualifies(coverage.Pass("a", speed_kmh=over), "full") == "speed"

    def test_a_reduced_quality_arc_is_exempt_from_the_speed_rule(self):
        """SPEC §3.2 films motorway and trunk at prevailing speed, so the 40 km/h
        rule cannot apply to them — which is why crediting a motorway pass is free."""
        over = C.COVERAGE_SPEED_MAX_KMH + 60.0
        assert coverage.qualifies(
            coverage.Pass("a", speed_kmh=over), "reduced") == "counted"

    def test_the_wrong_way_never_counts(self):
        assert coverage.qualifies(
            coverage.Pass("a", speed_kmh=5.0, heading_ok=False), "full") == "heading"

    def test_a_part_of_an_arc_is_not_a_traversal(self):
        assert coverage.qualifies(
            coverage.Pass("a", speed_kmh=5.0, through=False, fraction=0.1),
            "full") == "partial"

    def test_no_timestamps_means_no_speed_means_no_credit(self):
        assert coverage.qualifies(
            coverage.Pass("a", speed_kmh=0.0, has_time=False), "full") == "no-time"


class TestRequirementCarrier:
    def test_a_solo_arc_carries_its_own_requirement(self):
        lower = np.array([1, 0, 2], dtype="int64")
        partner = np.array([-1, -1, -1], dtype="int64")
        carrier = sequential.requirement_carrier(lower, partner)
        assert carrier.tolist() == [0, -1, 2]

    def test_either_direction_of_a_narrow_pair_discharges_it(self):
        """SPEC §2.2 — the pair is one street. `orientation` puts the requirement on
        one direction; driving the other films the same tarmac."""
        lower = np.array([1, 0], dtype="int64")
        partner = np.array([1, 0], dtype="int64")
        carrier = sequential.requirement_carrier(lower, partner)
        assert carrier.tolist() == [0, 0]

    def test_a_traversal_of_nothing_required_discharges_nothing(self):
        lower = np.array([0, 0], dtype="int64")
        partner = np.array([1, 0], dtype="int64")
        assert sequential.requirement_carrier(lower, partner).tolist() == [-1, -1]


class TestTakeCredit:
    def test_the_days_own_work_is_credited_first_and_is_not_bonus(self):
        counts = np.array([1, 0], dtype="int64")
        remaining = np.array([1, 1], dtype="int64")
        day_lower = np.array([1, 0], dtype="int64")
        carrier = np.array([0, 1], dtype="int64")
        own, bonus, left = sequential.take_credit(counts, remaining, day_lower, carrier)
        assert own.tolist() == [1, 0]
        assert bonus.tolist() == [0, 0]
        assert left.tolist() == [0, 1]

    def test_a_pass_over_another_days_street_is_bonus(self):
        counts = np.array([1, 1], dtype="int64")
        remaining = np.array([1, 1], dtype="int64")
        day_lower = np.array([1, 0], dtype="int64")   # only arc 0 belongs to this day
        carrier = np.array([0, 1], dtype="int64")
        own, bonus, left = sequential.take_credit(counts, remaining, day_lower, carrier)
        assert own.tolist() == [1, 0]
        assert bonus.tolist() == [0, 1]
        assert left.tolist() == [0, 0], "both requirements are now discharged"

    def test_credit_never_exceeds_what_is_owed(self):
        counts = np.array([5], dtype="int64")
        remaining = np.array([2], dtype="int64")
        own, bonus, left = sequential.take_credit(
            counts, remaining, np.array([0], dtype="int64"), np.array([0], dtype="int64"))
        assert bonus.tolist() == [2]
        assert left.tolist() == [0]

    def test_two_directions_of_one_street_cannot_both_claim_it(self):
        counts = np.array([1, 1], dtype="int64")
        remaining = np.array([1, 0], dtype="int64")
        carrier = np.array([0, 0], dtype="int64")     # a narrow pair
        own, bonus, left = sequential.take_credit(
            counts, remaining, np.zeros(2, dtype="int64"), carrier)
        assert bonus.sum() == 1, "one street, one requirement, one credit"
        assert left.tolist() == [0, 0]


class TestPayingForIt:
    def test_the_marginal_cost_is_the_slowdown(self):
        cost = sequential.marginal_cost_s(np.array([10.0, 5.0]), np.array([4.0, 5.0]))
        assert cost.tolist() == [6.0, 0.0]

    def test_a_reduced_arc_credit_is_free(self):
        assert sequential.marginal_cost_s(
            np.array([7.0]), np.array([7.0])).tolist() == [0.0]

    def test_within_budget_everything_is_kept(self):
        kept, total = sequential.fit_bonus(
            np.array([1, 1]), np.array([10.0, 20.0]), budget_s=100.0)
        assert kept.tolist() == [1, 1] and total == 30.0

    def test_over_budget_the_dearest_credits_go_first(self):
        kept, total = sequential.fit_bonus(
            np.array([1, 1]), np.array([10.0, 20.0]), budget_s=10.0)
        assert kept.tolist() == [1, 0], "keep the cheap one"
        assert total == 10.0

    def test_free_credits_are_never_given_up(self):
        kept, _ = sequential.fit_bonus(
            np.array([1, 1]), np.array([0.0, 50.0]), budget_s=0.0)
        assert kept.tolist() == [1, 0]

    def test_i10_holds_when_the_slowdown_is_charged(self):
        check = sequential.check_i10(np.array([2]), np.array([3.0]), charged_s=6.0)
        assert check["ok"]

    def test_i10_fails_when_it_is_not(self):
        assert not sequential.check_i10(
            np.array([2]), np.array([3.0]), charged_s=0.0)["ok"]


class TestRanking:
    def test_fewer_days_wins(self):
        assert sequential.better({"days": 6, "route_h": 40.0},
                                 {"days": 7, "route_h": 35.0})

    def test_on_equal_days_fewer_hours_wins(self):
        assert sequential.better({"days": 7, "route_h": 34.0},
                                 {"days": 7, "route_h": 35.0})

    def test_a_tie_keeps_the_incumbent(self):
        assert not sequential.better({"days": 7, "route_h": 35.0},
                                     {"days": 7, "route_h": 35.0})

    def test_more_days_loses_even_on_fewer_hours(self):
        assert not sequential.better({"days": 8, "route_h": 30.0},
                                     {"days": 7, "route_h": 35.0})


class TestDeterminism:
    def test_fit_bonus_is_stable_under_ties(self):
        """CLAUDE.md rule 5 — equal marginal costs must break the same way twice."""
        bonus = np.array([1, 1, 1, 1], dtype="int64")
        marginal = np.array([5.0, 5.0, 5.0, 5.0])
        first = sequential.fit_bonus(bonus, marginal, 10.0)[0].tolist()
        second = sequential.fit_bonus(bonus, marginal, 10.0)[0].tolist()
        assert first == second

    def test_take_credit_does_not_depend_on_iteration_order(self):
        counts = np.array([1, 1, 1], dtype="int64")
        remaining = np.array([1, 1, 1], dtype="int64")
        day_lower = np.zeros(3, dtype="int64")
        carrier = np.array([0, 1, 2], dtype="int64")
        a = sequential.take_credit(counts, remaining, day_lower, carrier)
        b = sequential.take_credit(counts, remaining, day_lower, carrier)
        assert a[1].tolist() == b[1].tolist()
