"""SPEC §2.1 passes model and the §1.1 fallback chain: lanes -> width -> class -> default 2."""
import pytest

from efficientroute import passes as P


class TestMinPassesFallbackChain:
    def test_lanes_tag_wins_when_present(self):
        assert P.min_passes_for(dir_lanes=4, dir_width_m=3.0, highway_class="primary") == (2, "lanes")
        assert P.min_passes_for(dir_lanes=3, dir_width_m=30.0, highway_class="primary") == (1, "lanes")

    def test_width_used_when_lanes_absent(self):
        assert P.min_passes_for(dir_lanes=None, dir_width_m=12.0, highway_class="primary") == (2, "width")
        assert P.min_passes_for(dir_lanes=None, dir_width_m=7.0, highway_class="primary") == (1, "width")

    def test_class_used_when_lanes_and_width_absent(self):
        assert P.min_passes_for(dir_lanes=None, dir_width_m=None, highway_class="residential") == (1, "class")
        assert P.min_passes_for(dir_lanes=None, dir_width_m=None, highway_class="secondary") == (1, "class")

    def test_inconclusive_class_falls_back_to_two(self):
        # SPEC §1.1: all three inconclusive -> the more demanding requirement
        assert P.min_passes_for(dir_lanes=None, dir_width_m=None, highway_class="primary") == (2, "default")
        assert P.min_passes_for(dir_lanes=None, dir_width_m=None, highway_class="motorway") == (2, "default")
        assert P.min_passes_for(dir_lanes=None, dir_width_m=None, highway_class="trunk") == (2, "default")

    def test_unknown_class_falls_back_to_two(self):
        assert P.min_passes_for(dir_lanes=None, dir_width_m=None, highway_class="road") == (2, "default")

    def test_min_passes_is_never_below_one(self):
        assert P.min_passes_for(dir_lanes=1, dir_width_m=None, highway_class="residential")[0] >= 1


class TestNarrowPair:
    def test_lanes_tag_wins(self):
        assert P.is_narrow_pair(total_lanes=2, width_m=None, highway_class="residential") == (True, "lanes")
        assert P.is_narrow_pair(total_lanes=4, width_m=None, highway_class="residential") == (False, "lanes")

    def test_width_used_when_lanes_absent(self):
        assert P.is_narrow_pair(total_lanes=None, width_m=6.0, highway_class="tertiary") == (True, "width")
        assert P.is_narrow_pair(total_lanes=None, width_m=9.0, highway_class="tertiary") == (False, "width")

    @pytest.mark.parametrize("cls", ["residential", "living_street", "service", "unclassified"])
    def test_minor_classes_are_narrow_by_class(self, cls):
        assert P.is_narrow_pair(total_lanes=None, width_m=None, highway_class=cls) == (True, "class")

    @pytest.mark.parametrize("cls", ["tertiary", "secondary", "primary", "trunk", "motorway"])
    def test_major_classes_are_not_narrow(self, cls):
        # accuracy-first: a shared requirement is the *cheaper* option, so it needs evidence
        assert P.is_narrow_pair(total_lanes=None, width_m=None, highway_class=cls)[0] is False

    def test_unknown_class_is_not_narrow(self):
        assert P.is_narrow_pair(total_lanes=None, width_m=None, highway_class="road") == (False, "default")


class TestCaptureQuality:
    @pytest.mark.parametrize("cls", ["motorway", "motorway_link", "trunk", "trunk_link"])
    def test_reduced(self, cls):
        assert P.capture_quality(cls) == "reduced"

    @pytest.mark.parametrize("cls", ["primary", "primary_link", "residential", "service"])
    def test_full(self, cls):
        assert P.capture_quality(cls) == "full"


class TestRequiredTraversals:
    """Required traversal km = sum(length * required passes), narrow pairs counted once."""

    def test_oneway_arc_counts_its_min_passes(self):
        assert P.required_traversals(min_passes=2, pair_requirement=0, is_pair_representative=True) == 2

    def test_wide_twoway_pair_counts_both_arcs(self):
        # pair_requirement 0 => no shared requirement, each arc required on its own
        assert P.required_traversals(min_passes=1, pair_requirement=0, is_pair_representative=True) == 1
        assert P.required_traversals(min_passes=1, pair_requirement=0, is_pair_representative=False) == 1

    def test_narrow_pair_counts_once_across_the_pair(self):
        assert P.required_traversals(min_passes=1, pair_requirement=1, is_pair_representative=True) == 1
        assert P.required_traversals(min_passes=1, pair_requirement=1, is_pair_representative=False) == 0
