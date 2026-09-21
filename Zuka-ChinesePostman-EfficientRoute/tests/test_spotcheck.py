"""Junction summaries for the manual imagery spot-check."""
from pathlib import Path

import pytest
from shapely.geometry import box

from efficientroute import extract as E
from efficientroute import network as N
from efficientroute import restrictions as R
from efficientroute import spotcheck as S
from efficientroute import turngraph as TG

FIXTURE = Path(__file__).parent / "fixtures" / "turns.osm"
CLIP = box(44.79, 41.71, 44.81, 41.73)


@pytest.fixture(scope="module")
def graph():
    arcs = N.build_arc_table(E.extract_ways(FIXTURE, CLIP), sampler=None)
    return TG.build_turn_graph(arcs, R.parse_restrictions(FIXTURE, {1000, 1001, 1002, 1003, 1004}))


class TestDescribeJunction:
    def test_counts_approaches_and_legal_manoeuvres(self, graph):
        summary = S.describe_junction(graph, 100)
        assert summary["approaches"] == 4
        assert summary["legal"] < summary["candidates"]

    def test_names_a_banned_manoeuvre_with_its_turn_class(self, graph):
        summary = S.describe_junction(graph, 100)
        banned = {(b["from"], b["to"]) for b in summary["banned"]}
        assert ("1000:0:F", "1001:0:F") in banned

    def test_renders_a_one_line_summary(self, graph):
        text = S.summarise(S.describe_junction(graph, 100))
        assert "legal" in text and "/" in text

    def test_unknown_node_is_empty_not_an_error(self, graph):
        assert S.describe_junction(graph, 99999999)["approaches"] == 0


class TestSelection:
    def test_selection_is_deterministic(self, graph):
        lonlat = {100: (44.800, 41.720), 3: (44.802, 41.720)}
        first = S.select_junctions(graph, lonlat, count=2)
        second = S.select_junctions(graph, lonlat, count=2)
        assert [j["osm_node"] for j in first] == [j["osm_node"] for j in second]

    def test_prefers_junctions_carrying_restrictions(self, graph):
        lonlat = {100: (44.800, 41.720), 3: (44.802, 41.720)}
        chosen = S.select_junctions(graph, lonlat, count=1)
        assert chosen[0]["osm_node"] == 100
