"""Stage 4b — the re-check helpers."""
import numpy as np
import pytest
import toygraph

from efficientroute import recheck


class TestIsFast:
    def test_it_selects_the_classes_spec_3_2_captures_degraded(self):
        classes = np.array(
            ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "residential"]
        )
        assert recheck.is_fast(classes).tolist() == [True, True, True, True, False, False]

    def test_an_empty_class_is_not_fast(self):
        assert recheck.is_fast(np.array([""])).tolist() == [False]


class TestU1Check:
    @staticmethod
    def graph_with(pairs):
        """A stub graph whose forbidden-pair lookup returns `pairs`."""
        class Stub:
            pass

        stub = Stub()
        stub._pairs = set(pairs)
        return stub

    def test_no_additions_holds_vacuously(self, monkeypatch):
        monkeypatch.setattr(recheck, "_forbidden_pairs", lambda g, p: {("a", "b")})
        result = recheck.u1_check(object(), object(), [])
        assert result["holds"] and result["checked"] == 0

    def test_an_addition_that_a_restriction_forbids_is_caught(self, monkeypatch):
        monkeypatch.setattr(recheck, "_forbidden_pairs", lambda g, p: {("a", "b")})
        added = [{"from_arc": "a", "to_arc": "b"}]
        result = recheck.u1_check(object(), object(), added)
        assert not result["holds"]
        assert result["violations"] == 1
        assert result["violating"] == added

    def test_an_allowed_addition_passes(self, monkeypatch):
        monkeypatch.setattr(recheck, "_forbidden_pairs", lambda g, p: {("a", "b")})
        result = recheck.u1_check(object(), object(), [{"from_arc": "a", "to_arc": "c"}])
        assert result["holds"] and result["violations"] == 0

    def test_the_check_is_exhaustive_not_sampled(self, monkeypatch):
        """Three manoeuvres can be checked completely; a sample cannot prove a
        negative, and this is the one place the graph changed."""
        monkeypatch.setattr(recheck, "_forbidden_pairs", lambda g, p: set())
        added = [{"from_arc": str(i), "to_arc": str(i + 1)} for i in range(7)]
        result = recheck.u1_check(object(), object(), added)
        assert result["checked"] == 7
        assert "exhaustive" in result["method"]


class TestMainlineRule:
    def test_the_rule_blocks_a_plain_junction_by_default(self):
        from efficientroute.turngraph import _mainline_entry_blocked

        mainline = frozenset({"motorway"})
        assert _mainline_entry_blocked("trunk", "motorway", mainline)

    def test_a_ramp_is_always_allowed_in(self):
        from efficientroute.turngraph import _mainline_entry_blocked

        mainline = frozenset({"motorway"})
        assert not _mainline_entry_blocked("motorway_link", "motorway", mainline)
        assert not _mainline_entry_blocked("primary_link", "motorway", mainline)

    def test_the_mainline_may_always_be_entered_from_itself(self):
        from efficientroute.turngraph import _mainline_entry_blocked

        assert not _mainline_entry_blocked("motorway", "motorway", frozenset({"motorway"}))

    def test_the_narrowing_only_fires_where_no_ramp_exists(self):
        from efficientroute.turngraph import _mainline_entry_blocked

        mainline = frozenset({"motorway"})
        assert _mainline_entry_blocked("trunk", "motorway", mainline, no_ramp_at_node=False)
        assert not _mainline_entry_blocked("trunk", "motorway", mainline, no_ramp_at_node=True)

    def test_it_does_not_touch_entry_into_anything_else(self):
        from efficientroute.turngraph import _mainline_entry_blocked

        mainline = frozenset({"motorway"})
        assert not _mainline_entry_blocked("residential", "primary", mainline)
        assert not _mainline_entry_blocked("residential", "primary", mainline, no_ramp_at_node=True)


class TestNarrowedRuleOnAToyNetwork:
    @staticmethod
    def network(with_ramp: bool):
        """A trunk meeting a motorway, with and without a tagged slip road."""
        arcs = [
            {"arc_id": "1:0:F", "highway_class": "trunk", "from_node": 1, "to_node": 2},
            {"arc_id": "2:0:F", "highway_class": "motorway", "from_node": 2, "to_node": 3},
        ]
        if with_ramp:
            arcs.append(
                {"arc_id": "3:0:F", "highway_class": "motorway_link",
                 "from_node": 4, "to_node": 2}
            )
        return toygraph.arc_frame(arcs)

    def test_without_a_ramp_the_narrowing_opens_the_junction(self):
        from efficientroute import turngraph

        frame = self.network(with_ramp=False)
        strict = turngraph.build_turn_graph(frame, mainline_entry_fallback=False)
        relaxed = turngraph.build_turn_graph(frame, mainline_entry_fallback=True)
        assert not strict.has_manoeuvre("1:0:F", "2:0:F")
        assert relaxed.has_manoeuvre("1:0:F", "2:0:F")

    def test_with_a_ramp_present_the_rule_still_binds(self):
        """The narrowing must not become a general relaxation."""
        from efficientroute import turngraph

        frame = self.network(with_ramp=True)
        relaxed = turngraph.build_turn_graph(frame, mainline_entry_fallback=True)
        assert not relaxed.has_manoeuvre("1:0:F", "2:0:F")
        assert relaxed.has_manoeuvre("3:0:F", "2:0:F")
