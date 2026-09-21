"""L(G) construction on the crossroads fixture, where every edge is countable by hand.

Junctions: node 100 is a 4-way crossroads (arms 1000/1001/1002/1003); node 3
joins 1002 to 1004; nodes 1, 2, 4, 5 are dead-end tips.  All ways are two-way
residential with no lane or width tag, so no mid-street U-turn has evidence.
"""
from pathlib import Path

import pytest
from shapely.geometry import box

from efficientroute import extract as E
from efficientroute import network as N
from efficientroute import restrictions as R
from efficientroute import turngraph as TG

FIXTURE = Path(__file__).parent / "fixtures" / "turns.osm"
CLIP = box(44.79, 41.71, 44.81, 41.73)
NETWORK_WAYS = {1000, 1001, 1002, 1003, 1004}


@pytest.fixture(scope="module")
def arcs():
    return N.build_arc_table(E.extract_ways(FIXTURE, CLIP), sampler=None)


@pytest.fixture(scope="module")
def graph(arcs):
    return TG.build_turn_graph(arcs, R.parse_restrictions(FIXTURE, NETWORK_WAYS))


@pytest.fixture(scope="module")
def unrestricted(arcs):
    return TG.build_turn_graph(arcs, R.ParsedRestrictions())


class TestNodes:
    def test_one_node_per_routable_arc_plus_clones(self, arcs, graph):
        routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
        assert len(routable) == 10
        assert graph.n_nodes == 11  # 10 arcs + 1 via-way clone

    def test_every_node_maps_back_to_a_physical_arc(self, arcs, graph):
        real = set(arcs["arc_id"])
        assert {arc_id for arc_id, _ in graph.node_ids} <= real

    def test_clones_are_marked_and_carry_the_original_arc_id(self, graph):
        clones = [(a, v) for a, v in graph.node_ids if v > 0]
        assert clones == [("1002:0:F", 1)]


class TestManoeuvres:
    def test_head_to_tail_is_required(self, unrestricted):
        # 1000:0:F ends at node 100; 1004:0:F starts at node 3 — never adjacent
        assert not unrestricted.has_manoeuvre("1000:0:F", "1004:0:F")

    def test_turn_classes_follow_the_geometry(self, unrestricted):
        assert unrestricted.turn_class_of("1000:0:F", "1001:0:F") == "left"
        assert unrestricted.turn_class_of("1000:0:F", "1003:0:F") == "right"
        assert unrestricted.turn_class_of("1000:0:F", "1002:0:F") == "straight"

    def test_penalties_follow_the_class(self, unrestricted):
        assert unrestricted.penalty_of("1000:0:F", "1001:0:F") == pytest.approx(8.0)
        assert unrestricted.penalty_of("1000:0:F", "1003:0:F") == pytest.approx(3.0)
        assert unrestricted.penalty_of("1000:0:F", "1002:0:F") == pytest.approx(0.0)

    def test_unrestricted_crossroads_has_twelve_edges(self, unrestricted):
        # 4 in x 4 out, minus the 4 u-turns that have no evidence of room
        at_100 = [e for e in unrestricted.edge_tuples() if e[2] == 100]
        assert len(at_100) == 12


class TestUTurnPolicy:
    def test_dead_end_tip_gets_a_u_turn(self, unrestricted):
        assert unrestricted.has_manoeuvre("1000:0:B", "1000:0:F")  # at node 1

    def test_mid_junction_u_turn_without_width_evidence_is_absent(self, unrestricted):
        assert not unrestricted.has_manoeuvre("1000:0:F", "1000:0:B")  # at node 100

    def test_u_turn_reasons_are_recorded(self, unrestricted):
        reasons = unrestricted.u_turn_reasons()
        assert reasons["dead_end_tip"] == 4  # nodes 1, 2, 4, 5
        assert reasons.get("width_permitted", 0) == 0


class TestRestrictionsApplied:
    def test_no_left_turn_edge_is_absent(self, graph):
        assert not graph.has_manoeuvre("1000:0:F", "1001:0:F")

    def test_no_right_turn_from_a_shift_covering_conditional_is_absent(self, graph):
        assert not graph.has_manoeuvre("1000:0:F", "1003:0:F")

    def test_only_straight_on_removes_the_other_manoeuvres(self, graph):
        assert graph.has_manoeuvre("1002:0:B", "1000:0:B")
        assert not graph.has_manoeuvre("1002:0:B", "1001:0:F")
        assert not graph.has_manoeuvre("1002:0:B", "1003:0:F")

    def test_unrelated_manoeuvres_survive(self, graph):
        assert graph.has_manoeuvre("1001:0:B", "1003:0:F")
        assert graph.has_manoeuvre("1003:0:B", "1001:0:F")

    def test_a_restriction_whose_edge_was_already_absent_is_recorded_as_such(self, graph):
        row = next(r for r in graph.restriction_log if r["relation_id"] == 2002)
        assert row["edges_removed"] == 0
        assert row["edges_already_absent"] == 1


class TestViaWayRestriction:
    def test_the_from_arc_now_enters_the_clone_not_the_original(self, graph):
        assert ("1002:0:F", 1) in graph.successors(("1000:0:F", 0))
        assert ("1002:0:F", 0) not in graph.successors(("1000:0:F", 0))

    def test_the_clone_cannot_complete_the_forbidden_manoeuvre(self, graph):
        assert ("1004:0:F", 0) not in graph.successors(("1002:0:F", 1))

    def test_the_original_via_arc_keeps_the_manoeuvre_for_other_approaches(self, graph):
        assert ("1004:0:F", 0) in graph.successors(("1002:0:F", 0))

    def test_via_way_restriction_is_logged_as_applied(self, graph):
        row = next(r for r in graph.restriction_log if r["relation_id"] == 2003)
        assert row["status"] == "applied"
        assert row["clones_created"] == 1


class TestCosts:
    def test_edge_cost_decomposes_into_turn_penalty_and_traversal(self, graph):
        src, dst = ("1001:0:B", 0), ("1003:0:F", 0)
        cost = graph.edge_cost_capture(src, dst)
        penalty = graph.penalty_of("1001:0:B", "1003:0:F")
        assert cost == pytest.approx(penalty + graph.traverse_capture_s(dst))

    def test_capture_traversal_is_capped_at_the_capture_speed(self, graph, arcs):
        node = ("1003:0:F", 0)
        length = arcs[arcs["arc_id"] == "1003:0:F"].iloc[0]["length_m"]
        assert graph.traverse_capture_s(node) >= length / (40.0 / 3.6) - 1e-6

    def test_deadhead_traversal_is_never_slower_than_capture(self, graph):
        for node in graph.node_ids:
            assert graph.traverse_deadhead_s(node) <= graph.traverse_capture_s(node) + 1e-9


class TestTraps:
    def test_the_clone_left_with_no_exit_is_reported_as_a_trap(self, graph):
        assert ("1002:0:F", 1) in graph.dead_end_nodes()


class TestUnresolvableRestrictions:
    """A restriction can parse cleanly and still not correspond to any manoeuvre.

    In the Tbilisi extract every such case is a restriction that contradicts the
    one-way tagging of its own members — the reason has to say which end failed,
    or the report cannot tell a mapping error from a bug in this code.
    """

    def test_from_way_not_ending_at_the_via_node(self, graph):
        row = next(r for r in graph.restriction_log if r["relation_id"] == 2010)
        assert row["status"] == "unresolvable"
        assert row["detail"] == "from_way_does_not_end_at_via_node"

    def test_to_way_not_starting_at_the_via_node(self, graph):
        row = next(r for r in graph.restriction_log if r["relation_id"] == 2011)
        assert row["status"] == "unresolvable"
        assert row["detail"] == "to_way_does_not_start_at_via_node"

    def test_unresolvable_restrictions_remove_nothing(self, graph):
        for rid in (2010, 2011):
            row = next(r for r in graph.restriction_log if r["relation_id"] == rid)
            assert row["edges_removed"] == 0


class TestPermissiveUTurnsForAttribution:
    """The audit needs a counterfactual build to attribute losses to a cause.

    Without it, an arc that fell out of L's largest SCC can only be reported as
    "unreachable", which tells nobody whether to fix a restriction, relax the
    U-turn rule, or widen the clip.
    """

    def test_permissive_build_adds_the_mid_junction_u_turn(self, arcs):
        from efficientroute import restrictions as R

        permissive = TG.build_turn_graph(arcs, R.ParsedRestrictions(), permissive_u_turns=True)
        assert permissive.has_manoeuvre("1000:0:F", "1000:0:B")

    def test_permissive_build_still_bars_motorway_and_trunk(self, arcs):
        from efficientroute import restrictions as R

        permissive = TG.build_turn_graph(arcs, R.ParsedRestrictions(), permissive_u_turns=True)
        for row in permissive.u_turn_log:
            cls = permissive.arc_index.loc[
                permissive.arc_index["arc_id"] == row["arc_id"], "highway_class"
            ].iloc[0]
            assert cls not in ("motorway", "trunk", "motorway_link", "trunk_link")
