"""Stage 3 — Euler circuit extraction, on graphs whose circuits are known."""
import numpy as np
import pytest
import toygraph

from efficientroute import euler
from efficientroute import tourcheck as TC


@pytest.fixture
def square():
    return toygraph.square()


@pytest.fixture
def pair_square():
    return toygraph.pair_square()


def _manoeuvre(star, a: int, b: int) -> int:
    """Index of the manoeuvre edge a -> b."""
    block = 2 * star.n_arc_nodes
    matches = np.flatnonzero(
        (star.edge_from_node[block:] == a) & (star.edge_to_node[block:] == b)
    )
    assert matches.size == 1, f"no unique manoeuvre {a} -> {b}"
    return int(block + matches[0])


def _double_lap(square):
    """A balanced flow that laps the square twice: one capture, one deadhead."""
    g, star = square
    x = np.zeros(star.n_edges, dtype="int64")
    x[: star.n_arc_nodes] = star.lower[: star.n_arc_nodes]
    x[star.n_arc_nodes : 2 * star.n_arc_nodes] = 1
    x[2 * star.n_arc_nodes :] = 2
    return star, x


def unit_flow(star):
    """One capture pass of every arc, plus every manoeuvre once."""
    x = np.zeros(star.n_edges, dtype="int64")
    x[: star.n_arc_nodes] = star.lower[: star.n_arc_nodes]
    x[2 * star.n_arc_nodes :] = 1
    return x


class TestCircuit:
    def test_a_simple_cycle_yields_every_arc_once(self, square):
        g, star = square
        result = euler.tour(star, unit_flow(star))
        assert sorted(result.tolist()) == [0, 1, 2, 3]

    def test_the_circuit_is_a_legal_closed_tour(self, square):
        g, star = square
        audit = TC.audit(euler.tour(star, unit_flow(star)), star, g)
        assert audit.ok, [(c.name, c.detail) for c in audit.failures]

    def test_it_consumes_every_edge_copy(self, square):
        walk = euler.circuit(*_double_lap(square))
        assert len(walk) == int(_double_lap(square)[1].sum())

    def test_a_repeated_arc_appears_twice_in_the_tour(self, square):
        """A second lap of the square: every arc once required, once deadhead."""
        g, star = square
        result = euler.tour(*_double_lap(square))
        assert list(result).count(0) == 2
        assert TC.audit(result, star, g).ok

    def test_an_asymmetric_repeat_is_handled(self, pair_square):
        """Driving both halves of a pair repeats arcs 2 and 3 but not arcs 0 or 1."""
        g, star = pair_square
        x = np.zeros(star.n_edges, dtype="int64")
        n = star.n_arc_nodes
        x[0] = 1                       # capture arc 0 (the oriented half)
        x[n + 1] = 1                   # deadhead arc 1 (the other half)
        x[2] = x[3] = 1                # capture arcs 2 and 3
        x[n + 2] = x[n + 3] = 1        # and drive each of them a second time
        for (a, b), count in {(0, 2): 1, (2, 3): 2, (3, 1): 1, (1, 2): 1, (3, 0): 1}.items():
            x[_manoeuvre(star, a, b)] = count
        result = euler.tour(star, x)
        assert sorted(result.tolist()) == [0, 1, 2, 2, 3, 3]
        assert TC.audit(result, star, g).ok

    def test_the_walk_alternates_in_and_out_nodes(self, square):
        g, star = square
        walk = euler.circuit(star, unit_flow(star))
        sides = (walk >= star.n_arc_nodes).astype(int)
        assert (np.diff(sides) != 0).all(), "an _in node must be followed by its _out"

    def test_the_start_node_is_not_repeated_at_the_end(self, square):
        g, star = square
        walk = euler.circuit(star, unit_flow(star))
        assert len(walk) == int(unit_flow(star).sum())
        assert walk[0] != walk[-1] or len(walk) == 1


class TestFailureModes:
    def test_a_disconnected_multigraph_is_refused_rather_than_truncated(self):
        """Two balanced but mutually unreachable cycles have no single circuit."""
        g, star = toygraph.two_cycles()
        x = unit_flow(star)
        with pytest.raises(RuntimeError, match="not connected"):
            euler.circuit(star, x)

    def test_an_unbalanced_multigraph_is_refused_rather_than_walked(self, square):
        """Hierholzer on an unbalanced graph returns an open walk that looks like
        a tour; the balance check is what stops that reaching the report."""
        g, star = square
        x = np.zeros(star.n_edges, dtype="int64")
        x[0] = 1
        x[_manoeuvre(star, 0, 1)] = 1
        with pytest.raises(ValueError, match="unbalanced"):
            euler.circuit(star, x)

    def test_an_empty_multigraph_is_an_error(self, square):
        g, star = square
        with pytest.raises(ValueError, match="no edges"):
            euler.circuit(star, np.zeros(star.n_edges, dtype="int64"))

    def test_a_negative_multiplicity_is_an_error(self, square):
        g, star = square
        x = unit_flow(star)
        x[0] = -1
        with pytest.raises(ValueError, match="negative"):
            euler.circuit(star, x)


class TestDeterminism:
    def test_the_same_flow_gives_the_same_tour(self, square):
        g, star = square
        first = euler.tour(star, unit_flow(star))
        second = euler.tour(star, unit_flow(star))
        assert first.tolist() == second.tolist()
