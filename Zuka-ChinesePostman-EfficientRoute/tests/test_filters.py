"""SPEC §3.1 drivability filter. Every exclusion carries a machine-readable reason."""
import pytest

from efficientroute import filters as F


class TestIncludedClasses:
    @pytest.mark.parametrize(
        "cls",
        [
            "motorway", "trunk", "primary", "secondary", "tertiary",
            "unclassified", "residential", "living_street", "service",
            "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
        ],
    )
    def test_required_classes_are_not_excluded_by_class(self, cls):
        assert F.classify_exclusion({"highway": cls}, cls, blocking_barrier=False) is None

    @pytest.mark.parametrize(
        "cls", ["pedestrian", "footway", "steps", "path", "track", "construction", "cycleway", "bridleway", "proposed"]
    )
    def test_non_drivable_classes_excluded(self, cls):
        assert F.classify_exclusion({"highway": cls}, cls, blocking_barrier=False) == "class_excluded"


class TestAccess:
    @pytest.mark.parametrize("key", ["access", "vehicle", "motor_vehicle", "motorcar"])
    def test_private_excluded(self, key):
        tags = {"highway": "service", key: "private"}
        assert F.classify_exclusion(tags, "service", blocking_barrier=False) == "access_private"

    @pytest.mark.parametrize("key", ["access", "vehicle", "motor_vehicle", "motorcar"])
    def test_no_excluded(self, key):
        tags = {"highway": "residential", key: "no"}
        assert F.classify_exclusion(tags, "residential", blocking_barrier=False) == "access_no"

    @pytest.mark.parametrize("value", ["destination", "yes", "permissive", "designated"])
    def test_public_access_values_are_kept(self, value):
        tags = {"highway": "residential", "access": value}
        assert F.classify_exclusion(tags, "residential", blocking_barrier=False) is None

    def test_specific_motorcar_yes_overrides_general_access_private(self):
        tags = {"highway": "service", "access": "private", "motorcar": "yes"}
        assert F.classify_exclusion(tags, "service", blocking_barrier=False) is None


class TestSurface:
    @pytest.mark.parametrize("surface", ["mud", "sand", "grass", "woodchips", "ice", "snow", "salt"])
    def test_impassable_surfaces_excluded(self, surface):
        tags = {"highway": "residential", "surface": surface}
        assert F.classify_exclusion(tags, "residential", blocking_barrier=False) == "surface_impassable"

    @pytest.mark.parametrize("surface", ["asphalt", "concrete", "paving_stones", "gravel", "unpaved", "ground", "dirt", "compacted", "cobblestone"])
    def test_rough_but_drivable_surfaces_kept(self, surface):
        tags = {"highway": "residential", "surface": surface}
        assert F.classify_exclusion(tags, "residential", blocking_barrier=False) is None

    def test_smoothness_impassable_excluded(self):
        tags = {"highway": "residential", "smoothness": "impassable"}
        assert F.classify_exclusion(tags, "residential", blocking_barrier=False) == "surface_impassable"


class TestIncline:
    def test_tagged_incline_above_limit_excluded(self):
        tags = {"highway": "residential", "incline": "25%"}
        assert F.classify_exclusion(tags, "residential", blocking_barrier=False) == "incline_too_steep"

    def test_steep_downhill_also_excluded(self):
        tags = {"highway": "residential", "incline": "-25%"}
        assert F.classify_exclusion(tags, "residential", blocking_barrier=False) == "incline_too_steep"

    def test_tbilisi_grade_of_twelve_percent_is_drivable(self):
        tags = {"highway": "residential", "incline": "12%"}
        assert F.classify_exclusion(tags, "residential", blocking_barrier=False) is None


class TestBarriersAndAreas:
    def test_blocking_barrier_excluded(self):
        assert F.classify_exclusion({"highway": "residential"}, "residential", blocking_barrier=True) == "barrier_blocking"

    def test_area_highway_excluded(self):
        tags = {"highway": "living_street", "area": "yes"}
        assert F.classify_exclusion(tags, "living_street", blocking_barrier=False) == "area_feature"


class TestBlockingBarrierNodes:
    @pytest.mark.parametrize("tags", [
        {"barrier": "bollard"},
        {"barrier": "block"},
        {"barrier": "cycle_barrier"},
        {"barrier": "gate", "locked": "yes"},
        {"barrier": "gate", "access": "private"},
        {"barrier": "lift_gate", "access": "no"},
    ])
    def test_blocking(self, tags):
        assert F.is_blocking_barrier(tags) is True

    @pytest.mark.parametrize("tags", [
        {"barrier": "gate"},
        {"barrier": "gate", "access": "yes"},
        {"barrier": "kerb"},
        {"barrier": "border_control"},
        {"highway": "crossing"},
        {},
    ])
    def test_not_blocking(self, tags):
        assert F.is_blocking_barrier(tags) is False
