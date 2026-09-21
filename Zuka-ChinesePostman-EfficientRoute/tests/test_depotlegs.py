"""Stage 4 items 2 and 3 — depot legs routed over L(G), and commute capture."""
import numpy as np
import pytest
import toygraph

from efficientroute import depotlegs


def line_graph(n=6, deadhead=100.0, capture=200.0, turn=5.0):
    """0 → 1 → … → n-1, one way, so every leg has exactly one route."""
    arcs = [{"arc_id": f"{i}:0:F", "from_node": i, "to_node": i + 1} for i in range(n)]
    turns = {(i, i + 1): turn for i in range(n - 1)}
    graph = toygraph.graph(arcs, turns)
    return graph, np.full(n, deadhead), np.full(n, capture)


def ring_graph(n=6, deadhead=100.0, capture=200.0, turn=5.0):
    arcs = [{"arc_id": f"{i}:0:F", "from_node": i, "to_node": (i + 1) % n} for i in range(n)]
    turns = {(i, (i + 1) % n): turn for i in range(n)}
    return toygraph.graph(arcs, turns), np.full(n, deadhead), np.full(n, capture)


class TestLegField:
    def test_the_cost_of_a_leg_is_turns_plus_the_arcs_entered(self):
        """Depot arc excluded, every arc after it counted, one turn per step."""
        graph, deadhead, _ = line_graph(6)
        field = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
        assert field.out_s[0] == pytest.approx(0.0)
        assert field.out_s[1] == pytest.approx(105.0)
        assert field.out_s[3] == pytest.approx(3 * 105.0)

    def test_an_unreachable_node_is_infinite_not_zero(self):
        graph, deadhead, _ = line_graph(6)
        field = depotlegs.leg_field(graph, deadhead, 3, "3:0:F", 0.0)
        assert not np.isfinite(field.out_s[0]), "a one-way line cannot be driven backwards"

    def test_the_return_field_measures_the_way_home(self):
        graph, deadhead, _ = ring_graph(6)
        field = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
        assert field.back_s[1] == pytest.approx(5 * 105.0), "five arcs round the ring"

    def test_the_hoisted_manoeuvre_arrays_give_the_same_answer(self):
        graph, deadhead, _ = ring_graph(6)
        arrays = depotlegs.manoeuvre_arrays(graph)
        a = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
        b = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0, arrays=arrays)
        assert a.out_s.tolist() == b.out_s.tolist()


class TestNearestInZone:
    def test_it_finds_the_cheapest_entry(self):
        graph, deadhead, _ = line_graph(6)
        field = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
        seconds, node = depotlegs.nearest_in_zone(field, np.array([4, 2, 3]), outbound=True)
        assert node == 2 and seconds == pytest.approx(2 * 105.0)

    def test_an_unreachable_zone_reports_infinity(self):
        graph, deadhead, _ = line_graph(6)
        field = depotlegs.leg_field(graph, deadhead, 3, "3:0:F", 0.0)
        seconds, _ = depotlegs.nearest_in_zone(field, np.array([0, 1]), outbound=True)
        assert not np.isfinite(seconds)


class TestPaths:
    def test_an_outbound_path_runs_depot_first(self):
        graph, deadhead, _ = line_graph(6)
        field = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
        leg = depotlegs.plain_leg(field, 3, outbound=True)
        assert leg.path.tolist() == [0, 1, 2, 3]

    def test_a_return_path_runs_in_driving_order_and_ends_at_the_depot(self):
        """The Dijkstra runs on the transposed graph; the path must not come back
        reversed, or every turn cost after it is read off a manoeuvre that does
        not exist."""
        graph, deadhead, _ = ring_graph(6)
        field = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
        leg = depotlegs.plain_leg(field, 2, outbound=False)
        assert leg.path[0] == 2 and leg.path[-1] == 0
        for a, b in zip(leg.path, leg.path[1:]):
            assert b in graph.adjacency[int(a)], "every step must be a legal manoeuvre"

    def test_a_plain_leg_claims_no_coverage(self):
        graph, deadhead, _ = line_graph(6)
        field = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
        leg = depotlegs.plain_leg(field, 3, outbound=True)
        assert leg.capture_s == 0.0 and not leg.routed_for_coverage


class TestCoverageLeg:
    @staticmethod
    def setup(n=6, **kw):
        graph, deadhead, capture = line_graph(n, **kw)
        field = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
        return graph, deadhead, capture, field

    def test_it_captures_uncovered_required_arcs_on_the_way(self):
        graph, deadhead, capture, field = self.setup()
        required = np.ones(6, dtype=bool)
        covered = np.zeros(6, dtype=bool)
        baseline = depotlegs.plain_leg(field, 3, outbound=True)
        leg = depotlegs.coverage_leg(
            graph, capture, deadhead, required, covered, 0, np.array([3]), True, baseline
        )
        assert leg.routed_for_coverage
        assert sorted(leg.captured.tolist()) == [1, 2, 3]
        assert leg.capture_s == pytest.approx(3 * 200.0)

    def test_the_leg_takes_longer_when_it_captures(self):
        """Capture speed is capped and deadhead is not, so a productive leg is slower."""
        graph, deadhead, capture, field = self.setup()
        required = np.ones(6, dtype=bool)
        baseline = depotlegs.plain_leg(field, 3, outbound=True)
        leg = depotlegs.coverage_leg(
            graph, capture, deadhead, required, np.zeros(6, dtype=bool), 0,
            np.array([3]), True, baseline,
        )
        assert leg.seconds > baseline.seconds

    def test_already_covered_arcs_earn_nothing(self):
        graph, deadhead, capture, field = self.setup()
        baseline = depotlegs.plain_leg(field, 3, outbound=True)
        leg = depotlegs.coverage_leg(
            graph, capture, deadhead, np.ones(6, dtype=bool), np.ones(6, dtype=bool),
            0, np.array([3]), True, baseline,
        )
        assert leg.capture_s == 0.0

    def test_arcs_nothing_requires_earn_nothing(self):
        graph, deadhead, capture, field = self.setup()
        baseline = depotlegs.plain_leg(field, 3, outbound=True)
        leg = depotlegs.coverage_leg(
            graph, capture, deadhead, np.zeros(6, dtype=bool), np.zeros(6, dtype=bool),
            0, np.array([3]), True, baseline,
        )
        assert leg.capture_s == 0.0

    def test_the_saving_reported_is_the_deadhead_not_the_capture(self):
        """The conservative half of the accounting: the zone loses `capture(e)`
        and the leg gains `capture(e) − deadhead(e)`, netting `deadhead(e)`."""
        graph, deadhead, capture, field = self.setup()
        baseline = depotlegs.plain_leg(field, 3, outbound=True)
        leg = depotlegs.coverage_leg(
            graph, capture, deadhead, np.ones(6, dtype=bool), np.zeros(6, dtype=bool),
            0, np.array([3]), True, baseline,
        )
        assert leg.deadhead_saving_s == pytest.approx(3 * 100.0)
        assert leg.capture_s - (leg.seconds - baseline.seconds) == pytest.approx(
            leg.deadhead_saving_s
        )

    def test_a_leg_that_would_take_too_long_falls_back(self):
        graph, deadhead, capture, field = self.setup(capture=100000.0)
        baseline = depotlegs.plain_leg(field, 3, outbound=True)
        leg = depotlegs.coverage_leg(
            graph, capture, deadhead, np.ones(6, dtype=bool), np.zeros(6, dtype=bool),
            0, np.array([3]), True, baseline, detour_cap=1.5,
        )
        assert leg is baseline

    def test_an_unreachable_target_falls_back(self):
        graph, deadhead, capture, field = self.setup()
        baseline = depotlegs.plain_leg(field, 3, outbound=True)
        leg = depotlegs.coverage_leg(
            graph, capture, deadhead, np.ones(6, dtype=bool), np.zeros(6, dtype=bool),
            0, np.array([], dtype="int64"), True, baseline,
        )
        assert leg is baseline
