"""Stage 3 item 3 — the lower bound.

The one property that matters is that it is *below*.  Every test here either
checks that, or checks that the thing it is below is the thing we mean.
"""
import numpy as np
import pytest
import toygraph

from efficientroute import dcpp, euler, lowerbound as LB
from efficientroute import tourcheck as TC


def constructive_total_s(g, star) -> float:
    tour = euler.tour(star, dcpp.solve(star).x)
    return TC.audit(tour, star, g).total_s


class TestCombinatorialBound:
    def test_it_counts_every_required_arc_and_its_cheapest_exit(self):
        """Square: 4 arcs at 100 s, each with one legal exit at 5 s."""
        g, star = toygraph.square()
        bound = LB.combinatorial_bound(star, g)
        assert bound.value_s == pytest.approx(4 * 105.0)

    def test_a_narrow_pair_counts_once_and_takes_the_cheaper_direction(self):
        g, star = toygraph.pair_square()
        bound = LB.combinatorial_bound(star, g)
        # arcs 2 and 3 at 105 s each, plus one traversal of the pair at 105 s
        assert bound.value_s == pytest.approx(3 * 105.0)

    def test_a_dead_end_spur_counts_its_pair_once(self):
        """Three loop arcs at 105 s, plus one traversal of the spur at 105 s."""
        g, star = toygraph.spur_and_loop()
        assert LB.combinatorial_bound(star, g).value_s == pytest.approx(4 * 105.0)

    def test_it_ignores_arcs_outside_the_tour_s_component(self):
        g, _ = toygraph.square()
        from efficientroute import lstar as LS

        star = LS.build(g, np.full(4, 100.0), np.full(4, 80.0),
                        np.ones(4, dtype="int64"),
                        keep=np.array([True, True, True, False]))
        assert LB.combinatorial_bound(star, g).value_s == pytest.approx(3 * 105.0)

    def test_it_is_below_the_constructive_tour(self):
        for builder in (toygraph.square, toygraph.pair_square, toygraph.spur_and_loop):
            g, star = builder()
            assert LB.combinatorial_bound(star, g).value_s <= constructive_total_s(g, star) + 1e-9

    def test_an_arc_with_no_legal_exit_contributes_no_exit_time(self):
        arcs = [{"arc_id": "1:0:F"}, {"arc_id": "2:0:F"}]
        g = toygraph.graph(arcs, {(0, 1): 7.0})
        assert LB.min_exit_s(g).tolist() == [7.0, 0.0]


class TestLpBound:
    def test_it_is_below_the_constructive_tour(self):
        for builder in (toygraph.square, toygraph.pair_square, toygraph.spur_and_loop):
            g, star = builder()
            bound = LB.lp_bound(star)
            assert bound.status == "optimal"
            assert bound.value_s <= constructive_total_s(g, star) + 1e-6

    def test_it_is_at_or_above_the_combinatorial_bound_on_a_simple_cycle(self):
        g, star = toygraph.square()
        assert LB.lp_bound(star).value_s >= LB.combinatorial_bound(star, g).value_s - 1e-6

    def test_it_is_tight_where_the_problem_is_easy(self):
        """The square has no orientation choice and no connectivity slack."""
        g, star = toygraph.square()
        assert LB.lp_bound(star).value_s == pytest.approx(constructive_total_s(g, star), rel=1e-6)

    def test_it_is_free_to_choose_either_direction_of_a_pair(self):
        """Which is what makes it a relaxation, and the tour an upper bound."""
        g, star = toygraph.pair_square()
        assert LB.lp_bound(star).value_s <= constructive_total_s(g, star) + 1e-6

    def test_it_reports_the_model_it_solved(self):
        g, star = toygraph.pair_square()
        detail = LB.lp_bound(star).to_dict()
        assert detail["columns"] == star.n_edges
        assert detail["pair_rows"] == 1
        assert detail["method"] == "lp_relaxation"


class TestCompute:
    def test_it_returns_both_bounds(self):
        g, star = toygraph.spur_and_loop()
        lp, fallback = LB.compute(star, g)
        assert lp.status == "optimal"
        assert fallback.status == "exact"

    def test_a_failing_lp_leaves_the_fallback_usable(self, monkeypatch):
        g, star = toygraph.square()
        monkeypatch.setattr(
            LB, "lp_bound", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        lp, fallback = LB.compute(star, g)
        assert "failed" in lp.status
        assert fallback.value_s > 0


class TestGap:
    def test_the_gap_is_relative_to_the_lower_bound(self):
        assert LB.optimality_gap(150.0, 100.0) == pytest.approx(0.5)

    def test_a_matching_pair_has_no_gap(self):
        assert LB.optimality_gap(100.0, 100.0) == pytest.approx(0.0)

    def test_a_zero_bound_is_not_a_division_by_zero(self):
        assert np.isnan(LB.optimality_gap(10.0, 0.0))
