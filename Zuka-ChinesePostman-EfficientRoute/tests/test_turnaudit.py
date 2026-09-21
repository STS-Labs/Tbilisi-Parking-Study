"""Auditing L: components, reachable required km, traps.

The reachability measure is the subtle one. SPEC §3.4 says a narrow two-way pair
needs *at least one of* {a, reverse(a)}, so a pair with only its backward arc
reachable is still fully coverable. Counting it as lost would overstate the
damage and could fail the gate on arcs that are in fact fine.
"""
import numpy as np
import pandas as pd
import pytest

from efficientroute import turnaudit as A


def _frame(rows):
    return pd.DataFrame(rows)


NARROW_PAIR = [
    {"arc_id": "1:0:F", "length_m": 100.0, "min_passes": 1, "pair_id": "1:0",
     "pair_requirement": 1, "is_pair_representative": True},
    {"arc_id": "1:0:B", "length_m": 100.0, "min_passes": 1, "pair_id": "1:0",
     "pair_requirement": 1, "is_pair_representative": False},
]
WIDE_PAIR = [
    {"arc_id": "2:0:F", "length_m": 200.0, "min_passes": 1, "pair_id": "2:0",
     "pair_requirement": 0, "is_pair_representative": True},
    {"arc_id": "2:0:B", "length_m": 200.0, "min_passes": 1, "pair_id": "2:0",
     "pair_requirement": 0, "is_pair_representative": False},
]
TWO_PASS_ONEWAY = [
    {"arc_id": "3:0:F", "length_m": 300.0, "min_passes": 2, "pair_id": "",
     "pair_requirement": 0, "is_pair_representative": True},
]


class TestReachableRequiredKm:
    def test_narrow_pair_counts_once_when_both_directions_reach(self):
        frame = _frame(NARROW_PAIR)
        assert A.reachable_required_km(frame, np.array([True, True])) == pytest.approx(0.1)

    def test_narrow_pair_still_counts_when_only_one_direction_reaches(self):
        frame = _frame(NARROW_PAIR)
        assert A.reachable_required_km(frame, np.array([False, True])) == pytest.approx(0.1)

    def test_narrow_pair_is_lost_only_when_both_directions_are_unreachable(self):
        frame = _frame(NARROW_PAIR)
        assert A.reachable_required_km(frame, np.array([False, False])) == pytest.approx(0.0)

    def test_wide_pair_loses_the_unreachable_direction(self):
        frame = _frame(WIDE_PAIR)
        assert A.reachable_required_km(frame, np.array([True, False])) == pytest.approx(0.2)

    def test_two_pass_one_way_counts_its_passes(self):
        frame = _frame(TWO_PASS_ONEWAY)
        assert A.reachable_required_km(frame, np.array([True])) == pytest.approx(0.6)

    def test_all_reachable_matches_the_stage_zero_headline_definition(self):
        from efficientroute import network as N

        frame = _frame(NARROW_PAIR + WIDE_PAIR + TWO_PASS_ONEWAY)
        everything = np.ones(len(frame), dtype=bool)
        assert A.reachable_required_km(frame, everything) == pytest.approx(
            N.required_traversal_km(frame)
        )


class TestStrongComponents:
    def test_labels_every_node(self):
        adjacency = [{1: None}, {0: None}, {}]
        labels, largest = A.strong_components(adjacency)
        assert len(labels) == 3
        assert labels[0] == labels[1] == largest
        assert labels[2] != largest

    def test_largest_is_the_biggest_component(self):
        adjacency = [{1: None}, {2: None}, {0: None}, {4: None}, {3: None}]
        labels, largest = A.strong_components(adjacency)
        assert (labels == largest).sum() == 3

    def test_single_node_graph(self):
        labels, largest = A.strong_components([{}])
        assert labels.tolist() == [largest]


class TestUTurnAccounting:
    """A geometric hairpin is not the same thing as a reverse-arc U-turn.

    SPEC §3.3's U-turn policy governs `a -> reverse(a)`. A manoeuvre that doubles
    back onto a *different* arc — a switchback on a hillside road, or a dedicated
    turnaround loop between the carriageways of a dual — is an ordinary legal
    manoeuvre that merely classifies as `u_turn` by bearing. Reporting one count
    for both makes the U-turn policy look like it created thousands of edges it
    did not.
    """

    def test_u_turn_edges_split_into_reverse_arc_and_hairpin(self):
        from pathlib import Path

        from shapely.geometry import box

        from efficientroute import extract as E
        from efficientroute import network as N
        from efficientroute import restrictions as R
        from efficientroute import turnaudit as A
        from efficientroute import turngraph as TG

        fixture = Path(__file__).parent / "fixtures" / "turns.osm"
        arcs = N.build_arc_table(E.extract_ways(fixture, box(44.79, 41.71, 44.81, 41.73)), sampler=None)
        graph = TG.build_turn_graph(arcs, R.ParsedRestrictions())
        audit = A.audit(graph)

        u_turns = audit["u_turns"]
        assert u_turns["reverse_arc_edges"] + u_turns["hairpin_edges"] == (
            audit["graph"]["turn_class_counts"]["u_turn"]
        )
        assert u_turns["reverse_arc_edges"] == u_turns["total"]


class TestTrapCause:
    """A road that continues past the 2 km clip buffer is trapped by where the
    extract stops, not by a broken junction. Mixing the two buries the traps that
    actually need fixing."""

    CLIP = None  # set in fixture

    @staticmethod
    def _clip():
        from shapely.geometry import box

        return box(44.60, 41.60, 45.00, 41.85)

    @staticmethod
    def _rows():
        return [
            # dangling node far outside the clip
            {"kind": "no_legal_exit", "arc_id": "1:0:F", "way_id": 1, "variant": 0,
             "from_node": 10, "to_node": 11},
            # dangling node deep inside the clip
            {"kind": "no_legal_exit", "arc_id": "2:0:F", "way_id": 2, "variant": 0,
             "from_node": 20, "to_node": 21},
            # mirrored pair: F has no entry, B has no exit, same physical node
            {"kind": "no_legal_entry", "arc_id": "3:0:F", "way_id": 3, "variant": 0,
             "from_node": 30, "to_node": 31},
            {"kind": "no_legal_exit", "arc_id": "3:0:B", "way_id": 3, "variant": 0,
             "from_node": 31, "to_node": 30},
        ]

    LONLAT = {
        10: (44.80, 41.75), 11: (45.30, 41.75),   # 11 is outside
        20: (44.80, 41.70), 21: (44.81, 41.70),   # both well inside
        30: (44.79, 41.70), 31: (44.79, 41.71),   # both inside, but mirrored
    }

    def _classify(self):
        from efficientroute import turnaudit as A

        return A.classify_trap_causes(self._rows(), self.LONLAT, self._clip(), tolerance_m=100.0)

    def test_node_outside_the_clip_is_a_clip_boundary_trap(self):
        rows = {r["arc_id"]: r for r in self._classify()}
        assert rows["1:0:F"]["trap_cause"] == "clip_boundary"
        assert rows["1:0:F"]["trap_cause_rule"] == "clip_edge_distance"

    def test_node_deep_inside_is_a_genuine_trap(self):
        rows = {r["arc_id"]: r for r in self._classify()}
        assert rows["2:0:F"]["trap_cause"] == "genuine"

    def test_mirrored_reverse_pair_is_a_clip_boundary_trap(self):
        rows = {r["arc_id"]: r for r in self._classify()}
        assert rows["3:0:F"]["trap_cause"] == "clip_boundary"
        assert rows["3:0:F"]["trap_cause_rule"] == "mirrored_reverse"
        assert rows["3:0:B"]["trap_cause"] == "clip_boundary"

    def test_every_trap_gets_a_cause(self):
        rows = self._classify()
        assert all(r["trap_cause"] in {"clip_boundary", "genuine"} for r in rows)
        assert len(rows) == 4

    def test_distance_to_the_clip_edge_is_recorded(self):
        rows = {r["arc_id"]: r for r in self._classify()}
        assert rows["2:0:F"]["clip_edge_distance_m"] > 100.0

    def test_a_node_just_inside_the_edge_still_counts_as_clip_boundary(self):
        from efficientroute import turnaudit as A

        rows = [{"kind": "no_legal_exit", "arc_id": "9:0:F", "way_id": 9, "variant": 0,
                 "from_node": 90, "to_node": 91}]
        lonlat = {90: (44.80, 41.70), 91: (44.9995, 41.70)}  # ~40 m inside the eastern edge
        out = A.classify_trap_causes(rows, lonlat, self._clip(), tolerance_m=100.0)
        assert out[0]["trap_cause"] == "clip_boundary"
