"""Stage 2 item 0 — `service_role` by connectivity.

The rule is easy to state and easy to get subtly wrong, so these tests build the
three cases by hand rather than asserting against the city.  `test_gate2` does
the reconciliation against the real network.
"""
import pandas as pd
import pytest

from efficientroute import servicerole as SR


def frame(rows: list[dict]) -> pd.DataFrame:
    """A minimal arc table: every column `classify` and `summarise` consult."""
    out = []
    for i, row in enumerate(rows):
        out.append(
            {
                "arc_id": f"{i}:0:F",
                "highway_class": row.get("highway_class", "service"),
                "from_node": row["from_node"],
                "to_node": row["to_node"],
                "excluded": row.get("excluded", False),
                "length_m": row.get("length_m", 1000.0),
                "is_pair_representative": row.get("rep", True),
                "service_type": row.get("service_type", "untagged"),
            }
        )
    return pd.DataFrame(out)


class TestClassify:
    def test_a_service_run_between_two_streets_is_through(self):
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 3, "to_node": 4, "highway_class": "residential"},
                {"from_node": 2, "to_node": 3},  # service, links the two
            ]
        )
        assert SR.classify(arcs).tolist() == ["", "", "through"]

    def test_a_dead_end_off_one_junction_is_a_spur(self):
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 2, "to_node": 3},
                {"from_node": 3, "to_node": 4},
            ]
        )
        assert SR.classify(arcs).tolist() == ["", "spur", "spur"]

    def test_service_touching_no_street_is_an_orphan(self):
        arcs = frame([{"from_node": 10, "to_node": 11}, {"from_node": 11, "to_node": 12}])
        assert SR.classify(arcs).tolist() == ["orphan", "orphan"]

    def test_the_whole_component_takes_one_role_not_each_arc(self):
        """A spur hanging off a through run is still part of the through component."""
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 3, "to_node": 4, "highway_class": "residential"},
                {"from_node": 2, "to_node": 3},
                {"from_node": 3, "to_node": 99},  # dead-end branch off the same run
            ]
        )
        assert SR.classify(arcs).tolist() == ["", "", "through", "through"]

    def test_two_touches_of_the_same_node_do_not_make_a_through_route(self):
        """A loop back onto its own junction is still a spur: one door, not two."""
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 2, "to_node": 3},
                {"from_node": 3, "to_node": 2},
            ]
        )
        assert SR.classify(arcs).tolist() == ["", "spur", "spur"]

    def test_an_excluded_street_is_not_a_door(self):
        """The §1.1-consistent reading: connectivity you cannot drive is not connectivity."""
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 3, "to_node": 4, "highway_class": "residential", "excluded": True},
                {"from_node": 2, "to_node": 3},
            ]
        )
        assert SR.classify(arcs).tolist() == ["", "", "spur"]

    def test_an_excluded_service_arc_is_labelled_not_left_blank(self):
        """CLAUDE.md rule 4 — a blank would read as 'not a service road'."""
        arcs = frame([{"from_node": 1, "to_node": 2, "excluded": True}])
        assert SR.classify(arcs).tolist() == ["excluded"]

    def test_an_excluded_service_arc_does_not_join_components(self):
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 5, "to_node": 6, "highway_class": "residential"},
                {"from_node": 2, "to_node": 3},
                {"from_node": 3, "to_node": 4, "excluded": True},  # the missing link
                {"from_node": 4, "to_node": 5},
            ]
        )
        assert SR.classify(arcs).tolist() == ["", "", "spur", "excluded", "spur"]

    def test_the_role_does_not_depend_on_row_order(self):
        rows = [
            {"from_node": 1, "to_node": 2, "highway_class": "residential"},
            {"from_node": 3, "to_node": 4, "highway_class": "residential"},
            {"from_node": 2, "to_node": 9},
            {"from_node": 9, "to_node": 3},
        ]
        forward = SR.classify(frame(rows))
        backward = SR.classify(frame(list(reversed(rows))))
        assert forward.tolist() == list(reversed(backward.tolist()))


class TestSummarise:
    def test_km_is_counted_once_per_physical_street_not_once_per_direction(self):
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 3, "to_node": 4, "highway_class": "residential"},
                {"from_node": 2, "to_node": 3, "rep": True},
                {"from_node": 3, "to_node": 2, "rep": False},
            ]
        )
        block = SR.summarise(arcs)["all_service"]
        assert block["centerline_km"] == pytest.approx(1.0)

    def test_untagged_is_a_subset_of_all_service(self):
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 2, "to_node": 3, "service_type": "untagged"},
                {"from_node": 3, "to_node": 4, "service_type": "driveway"},
            ]
        )
        out = SR.summarise(arcs)
        assert out["untagged_service"]["centerline_km"] <= out["all_service"]["centerline_km"]
        assert out["all_service"]["centerline_km"] == pytest.approx(2.0)
        assert out["untagged_service"]["centerline_km"] == pytest.approx(1.0)

    def test_shares_sum_to_one_when_there_is_anything_to_share(self):
        arcs = frame(
            [
                {"from_node": 1, "to_node": 2, "highway_class": "residential"},
                {"from_node": 2, "to_node": 3},
                {"from_node": 10, "to_node": 11},
            ]
        )
        for block in SR.summarise(arcs).values():
            assert sum(r["share"] for r in block["rows"]) == pytest.approx(1.0)
