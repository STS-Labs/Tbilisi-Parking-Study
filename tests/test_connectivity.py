"""Strongly connected components over the directed arc graph (SPEC §3.1)."""
from efficientroute import connectivity as K

ARCS = [
    ("a1", 1, 2), ("a2", 2, 3), ("a3", 3, 1),   # 3-cycle, the largest component
    ("a4", 4, 5), ("a5", 5, 4),                  # 2-cycle, an orphan fragment
    ("a6", 3, 4),                                # bridge: inside no component
]


class TestLabelComponents:
    def test_largest_component_is_index_zero(self):
        labels = K.label_components(ARCS)
        assert labels["a1"] == labels["a2"] == labels["a3"] == 0

    def test_smaller_component_gets_a_later_index(self):
        labels = K.label_components(ARCS)
        assert labels["a4"] == labels["a5"] == 1

    def test_arc_spanning_two_components_belongs_to_neither(self):
        assert K.label_components(ARCS)["a6"] == -1

    def test_every_arc_is_labelled(self):
        assert set(K.label_components(ARCS)) == {a[0] for a in ARCS}

    def test_ranking_is_deterministic_for_equal_sized_components(self):
        arcs = [("x1", 7, 8), ("x2", 8, 7), ("y1", 1, 2), ("y2", 2, 1)]
        first = K.label_components(arcs)
        second = K.label_components(list(reversed(arcs)))
        assert first == second
        # ties break on the lowest node id, so the 1<->2 cycle wins
        assert first["y1"] == 0

    def test_self_loop_is_its_own_component(self):
        assert K.label_components([("s", 1, 1)])["s"] == 0
