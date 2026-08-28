"""Stage 3 item 1 — the node-split transform.

Getting this wrong is the standard way an arc-routing problem gets solved
wrongly, so the structure is asserted rather than assumed.
"""
import numpy as np
import pytest
import toygraph

from efficientroute import lstar as LS


@pytest.fixture
def square():
    return toygraph.square()


class TestStructure:
    def test_every_l_node_becomes_two(self, square):
        g, star = square
        assert star.n_arc_nodes == g.n_nodes
        assert star.n_nodes == 2 * g.n_nodes

    def test_there_is_one_capture_and_one_deadhead_edge_per_node(self, square):
        g, star = square
        assert int((star.kind == LS.CAPTURE).sum()) == star.n_arc_nodes
        assert int((star.kind == LS.DEADHEAD).sum()) == star.n_arc_nodes

    def test_there_is_one_manoeuvre_edge_per_legal_turn(self, square):
        g, star = square
        assert star.n_manoeuvres == sum(len(row) for row in g.adjacency)

    def test_the_block_layout_is_the_documented_one(self, square):
        g, star = square
        n = star.n_arc_nodes
        assert (star.kind[:n] == LS.CAPTURE).all()
        assert (star.kind[n : 2 * n] == LS.DEADHEAD).all()
        assert (star.kind[2 * n :] == LS.MANOEUVRE).all()

    def test_capture_and_deadhead_edges_run_in_to_out(self, square):
        g, star = square
        n = star.n_arc_nodes
        assert (star.tail[: 2 * n] < n).all(), "they must leave an _in node"
        assert (star.head[: 2 * n] >= n).all(), "and arrive at the matching _out node"
        assert (star.head[:n] == star.tail[:n] + n).all()

    def test_manoeuvre_edges_run_out_to_in(self, square):
        g, star = square
        n = star.n_arc_nodes
        assert (star.tail[2 * n :] >= n).all()
        assert (star.head[2 * n :] < n).all()

    def test_the_capture_edge_carries_the_requirement_and_cannot_exceed_it(self, square):
        g, star = square
        n = star.n_arc_nodes
        assert (star.lower[:n] == star.upper[:n]).all(), (
            "an extra pass must go on the deadhead edge, not the capture edge"
        )

    def test_the_deadhead_edge_is_the_cheaper_of_the_two(self, square):
        g, star = square
        n = star.n_arc_nodes
        assert (star.cost_s[n : 2 * n] <= star.cost_s[:n]).all()


class TestSupplies:
    def test_an_out_node_is_a_source_and_an_in_node_a_sink(self, square):
        g, star = square
        supply = star.mcf_supplies()
        n = star.n_arc_nodes
        assert (supply[:n] == -star.lower[:n]).all()
        assert (supply[n:] == star.lower[:n]).all()

    def test_supply_and_demand_balance(self, square):
        g, star = square
        assert int(star.mcf_supplies().sum()) == 0

    def test_the_total_imbalance_does_not_depend_on_orientation(self):
        """The finding that moves the orientation heuristic onto base junctions."""
        g, _ = toygraph.pair_square()
        forward = LS.build(g, np.full(4, 100.0), np.full(4, 80.0),
                           np.array([1, 0, 1, 1], dtype="int64"))
        backward = LS.build(g, np.full(4, 100.0), np.full(4, 80.0),
                            np.array([0, 1, 1, 1], dtype="int64"))
        assert np.abs(forward.mcf_supplies()).sum() == np.abs(backward.mcf_supplies()).sum()


class TestScope:
    def test_an_out_of_scope_node_is_isolated_rather_than_renumbered(self, square):
        g, _ = square
        keep = np.array([True, True, True, False])
        star = LS.build(g, np.full(4, 100.0), np.full(4, 80.0),
                        np.ones(4, dtype="int64"), keep=keep)
        assert star.n_arc_nodes == 4, "indices must stay stable"
        assert star.lower[3] == 0
        assert star.upper[star.n_arc_nodes + 3] == 0
        touching = (star.edge_from_node[2 * star.n_arc_nodes :] == 3) | (
            star.edge_to_node[2 * star.n_arc_nodes :] == 3
        )
        assert (star.upper[2 * star.n_arc_nodes :][touching] == 0).all()

    def test_in_scope_defaults_to_everything(self, square):
        g, star = square
        assert star.in_scope.all()

    def test_a_mismatched_keep_is_an_error(self, square):
        g, _ = square
        with pytest.raises(ValueError, match="keep has"):
            LS.build(g, np.full(4, 100.0), np.full(4, 80.0),
                     np.ones(4, dtype="int64"), keep=np.array([True]))


class TestValidation:
    def test_a_deadhead_slower_than_capture_is_refused(self, square):
        g, _ = square
        with pytest.raises(ValueError, match="slower than a capture"):
            LS.build(g, np.full(4, 100.0), np.full(4, 120.0), np.ones(4, dtype="int64"))

    def test_a_negative_lower_bound_is_refused(self, square):
        g, _ = square
        with pytest.raises(ValueError, match="negative lower bound"):
            LS.build(g, np.full(4, 100.0), np.full(4, 80.0), np.array([-1, 1, 1, 1]))

    def test_a_wrong_length_array_is_refused(self, square):
        g, _ = square
        with pytest.raises(ValueError, match="rows for"):
            LS.build(g, np.full(3, 100.0), np.full(4, 80.0), np.ones(4, dtype="int64"))

    def test_saturating_the_capacity_sentinel_is_an_error_not_a_silent_answer(self, square):
        g, star = square
        flow = np.zeros(star.n_edges, dtype="int64")
        flow[star.n_arc_nodes] = LS.CAPACITY_INF
        with pytest.raises(AssertionError, match="CAPACITY_INF"):
            LS.assert_no_saturation(flow, star)


class TestPairsAndVariants:
    def test_a_narrow_pair_points_at_its_twin(self):
        g, star = toygraph.pair_square()
        assert star.partner[0] == 1 and star.partner[1] == 0

    def test_a_one_way_arc_has_no_partner(self):
        g, star = toygraph.pair_square()
        assert star.partner[2] == -1 and star.partner[3] == -1

    def test_variants_of_one_arc_share_an_arc_group(self):
        arcs = [
            {"arc_id": "1:0:F", "variant": 0},
            {"arc_id": "1:0:F", "variant": 1},
            {"arc_id": "2:0:F", "variant": 0},
        ]
        g = toygraph.graph(arcs, {(0, 2): 1.0, (2, 0): 1.0, (1, 2): 1.0})
        star = LS.build(g, np.full(3, 10.0), np.full(3, 8.0), np.array([1, 0, 1]))
        assert star.arc_group[0] == star.arc_group[1]
        assert star.arc_group[0] != star.arc_group[2]


class TestCostDiscretisation:
    def test_milliseconds_round_half_even(self):
        assert LS.to_ms(np.array([1.0005, 0.001, 12.3456])).tolist() == [1000, 1, 12346]

    def test_the_float_cost_is_kept_alongside_the_integer_one(self, square):
        g, star = square
        assert star.cost_s.dtype == np.float64
        assert star.cost_ms.dtype == np.int64
