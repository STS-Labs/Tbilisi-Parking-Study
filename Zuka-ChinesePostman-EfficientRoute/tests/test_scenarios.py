"""Service-scope scenarios A/B/C — measurement only, no switch and no default change."""
import numpy as np
import pandas as pd
import pytest

from efficientroute import scenarios as S

FRAME = pd.DataFrame(
    [
        {"arc_id": "1:0:F", "highway_class": "residential", "service_type": None},
        {"arc_id": "2:0:F", "highway_class": "service", "service_type": "alley"},
        {"arc_id": "3:0:F", "highway_class": "service", "service_type": "untagged"},
        {"arc_id": "4:0:F", "highway_class": "service", "service_type": "driveway"},
        {"arc_id": "5:0:F", "highway_class": "service", "service_type": "parking_aisle"},
    ]
)


class TestVariantMask:
    def test_variant_a_keeps_everything(self):
        assert S.variant_mask(FRAME, "A").tolist() == [True] * 5

    def test_variant_b_keeps_alleys_and_untagged_service(self):
        assert S.variant_mask(FRAME, "B").tolist() == [True, True, True, False, False]

    def test_variant_c_drops_all_service(self):
        assert S.variant_mask(FRAME, "C").tolist() == [True, False, False, False, False]

    def test_no_variant_touches_a_non_service_arc(self):
        for variant in S.VARIANTS:
            assert bool(S.variant_mask(FRAME, variant)[0]) is True

    def test_unknown_variant_is_an_error_not_a_silent_pass(self):
        with pytest.raises(ValueError):
            S.variant_mask(FRAME, "Z")

    def test_variants_are_nested(self):
        a = S.variant_mask(FRAME, "A")
        b = S.variant_mask(FRAME, "B")
        c = S.variant_mask(FRAME, "C")
        assert np.all(c <= b) and np.all(b <= a)


class TestVariantD:
    """Stage 2's axis: connectivity rather than tagging."""

    FRAME = FRAME.assign(service_role=["", "through", "spur", "spur", "orphan"])

    def test_variant_d_keeps_only_through_service(self):
        assert S.variant_mask(self.FRAME, "D").tolist() == [True, True, False, False, False]

    def test_variant_d_never_touches_a_non_service_arc(self):
        assert bool(S.variant_mask(self.FRAME, "D")[0]) is True

    def test_variant_d_without_the_column_is_an_error_not_a_silent_pass(self):
        with pytest.raises(KeyError):
            S.variant_mask(FRAME, "D")

    def test_variant_d_is_not_in_the_stage_0b_comparison(self):
        """Adding D must not change what `compare` — and so Stage 0b — reports."""
        assert "D" not in S.VARIANTS
        assert "D" in S.KNOWN_VARIANTS

    def test_variant_d_sits_between_a_and_c(self):
        a = S.variant_mask(self.FRAME, "A")
        d = S.variant_mask(self.FRAME, "D")
        c = S.variant_mask(self.FRAME, "C")
        assert np.all(c <= d) and np.all(d <= a)
