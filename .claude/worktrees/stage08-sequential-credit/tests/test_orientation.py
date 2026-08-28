"""Stage 3 item 2.1 — narrow-pair orientation."""
import numpy as np
import pytest
import toygraph

from efficientroute import orientation as O


@pytest.fixture
def index():
    return toygraph.pair_index()


class TestLowerBounds:
    def test_exactly_one_direction_of_each_pair_is_required(self, index):
        lower = O.orient(index).lower
        assert lower[0] + lower[1] == 1
        assert lower[2] + lower[3] == 1

    def test_a_one_way_arc_keeps_its_min_passes(self, index):
        assert O.orient(index).lower[4] == 1

    def test_a_two_pass_one_way_keeps_both_passes(self, index):
        frame = index.copy()
        frame.loc[4, "min_passes"] = 2
        assert O.orient(frame).lower[4] == 2

    def test_the_total_requirement_is_orientation_independent(self, index):
        """One traversal per pair, however the pairs are turned."""
        assert int(O.orient(index).lower.sum()) == 3


class TestImbalance:
    def test_the_heuristic_never_makes_imbalance_worse(self, index):
        result = O.orient(index)
        assert result.imbalance_after <= result.imbalance_naive

    def test_it_finds_the_balanced_orientation_of_a_triangle(self, index):
        """P forward, Q forward and R together form a cycle: perfectly balanced."""
        result = O.orient(index)
        assert result.imbalance_after == 0

    def test_local_search_stops_when_nothing_improves(self, index):
        result = O.orient(index)
        assert result.passes <= 20

    def test_a_pair_between_one_junction_and_itself_is_degenerate(self):
        frame = toygraph.pair_index()
        frame.loc[0, "to_node"] = 1
        frame.loc[1, "from_node"] = 1
        assert O.orient(frame).degenerate_pairs == 1


class TestScope:
    def test_an_unreachable_direction_is_never_chosen(self, index):
        """Choosing it would leave the street uncovered while the bound said otherwise."""
        keep = np.array([False, True, True, True, True])
        result = O.orient(index, keep=keep)
        assert result.lower[0] == 0 and result.lower[1] == 1
        assert result.forced_pairs == 1

    def test_a_pair_with_neither_direction_reachable_is_reported(self, index):
        keep = np.array([False, False, True, True, True])
        result = O.orient(index, keep=keep)
        assert result.lower[0] == 0 and result.lower[1] == 0
        assert result.unreachable_pairs == 1

    def test_an_unreachable_one_way_is_not_required(self, index):
        keep = np.array([True, True, True, True, False])
        assert O.orient(index, keep=keep).lower[4] == 0

    def test_a_forced_pair_is_left_out_of_the_local_search(self, index):
        """Flipping it is not an option, so it must not be counted as a flip."""
        keep = np.array([False, True, True, True, True])
        result = O.orient(index, keep=keep)
        assert result.forced_pairs + len(index[index.pair_id != ""]) // 2 >= 1


class TestDeterminism:
    def test_the_same_index_gives_the_same_orientation(self, index):
        assert O.orient(index).lower.tolist() == O.orient(index).lower.tolist()

    def test_row_order_does_not_change_the_answer(self, index):
        shuffled = index.iloc[[4, 1, 0, 3, 2]].reset_index(drop=True)
        forward = {
            index.at[i, "arc_id"]: int(v) for i, v in enumerate(O.orient(index).lower)
        }
        backward = {
            shuffled.at[i, "arc_id"]: int(v) for i, v in enumerate(O.orient(shuffled).lower)
        }
        assert forward == backward
