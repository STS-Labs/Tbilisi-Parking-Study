"""Stage 3 item 2.2 — min-cost flow with lower bounds, and connectivity repair."""
import numpy as np
import pytest
import toygraph

from efficientroute import dcpp, euler
from efficientroute import tourcheck as TC


class TestBalance:
    def test_a_cycle_needs_no_augmentation(self):
        """The square is already Eulerian, so the cheapest circulation is one lap."""
        g, star = toygraph.square()
        flow = dcpp.solve(star)
        n = star.n_arc_nodes
        assert flow.x[:n].tolist() == [1, 1, 1, 1]
        assert flow.x[n : 2 * n].tolist() == [0, 0, 0, 0]
        assert flow.x[2 * n :].tolist() == [1, 1, 1, 1]

    def test_the_result_is_a_circulation(self):
        g, star = toygraph.square()
        euler.assert_balanced(star, dcpp.solve(star).x)

    def test_every_lower_bound_is_met(self):
        g, star = toygraph.spur_and_loop()
        flow = dcpp.solve(star)
        assert (flow.x >= star.lower).all()

    def test_the_reported_cost_is_the_cost_of_the_flow(self):
        g, star = toygraph.square()
        flow = dcpp.solve(star)
        assert flow.cost_ms == int((flow.x * star.cost_ms).sum())


class TestConnectivity:
    def test_a_self_contained_spur_cycle_is_joined_to_the_loop(self):
        """Left alone the flow drives into the spur and straight back in again."""
        g, star = toygraph.spur_and_loop()
        flow = dcpp.solve(star)
        assert flow.components_initial == 2
        assert flow.rounds >= 1
        assert flow.forced_edges > 0

    def test_the_joined_result_has_a_single_euler_circuit(self):
        g, star = toygraph.spur_and_loop()
        flow = dcpp.solve(star)
        tour = euler.tour(star, flow.x)
        audit = TC.audit(tour, star, g)
        assert audit.ok, [(c.name, c.detail) for c in audit.failures]

    def test_joining_reaches_the_spur_from_the_loop(self):
        g, star = toygraph.spur_and_loop()
        tour = euler.tour(star, dcpp.solve(star).x).tolist()
        assert set(tour) == {0, 1, 2, 3, 4}, "the joined tour must cover everything"

    def test_connectivity_is_charged_separately_from_balance(self):
        """It decomposes, and it can never be a discount: forcing edges only adds
        constraints. On this toy it happens to be free, which is allowed."""
        g, star = toygraph.spur_and_loop()
        flow = dcpp.solve(star)
        assert flow.cost_ms == flow.balance_cost_ms + flow.connectivity_cost_ms
        assert flow.connectivity_cost_ms >= 0

    def test_an_already_connected_flow_pays_nothing_for_connectivity(self):
        g, star = toygraph.square()
        flow = dcpp.solve(star)
        assert flow.components_initial == 1
        assert flow.connectivity_cost_ms == 0
        assert flow.rounds == 0

    def test_components_that_cannot_be_joined_are_an_error_not_a_bad_tour(self):
        g, star = toygraph.two_cycles()
        with pytest.raises(RuntimeError, match="no connecting path"):
            dcpp.solve(star)


class TestDeterminism:
    def test_the_same_l_star_gives_the_same_flow(self):
        g, star = toygraph.spur_and_loop()
        assert dcpp.solve(star).x.tolist() == dcpp.solve(star).x.tolist()

    def test_solving_does_not_mutate_the_input(self):
        g, star = toygraph.spur_and_loop()
        before = star.lower.copy()
        dcpp.solve(star)
        assert star.lower.tolist() == before.tolist()
