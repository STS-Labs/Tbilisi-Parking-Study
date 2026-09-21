"""Stage 2 item 2 — congestion.  Every coefficient is an assumption; the tests
here are about the *arithmetic* around them, which is not."""
import numpy as np
import pandas as pd
import pytest

from efficientroute import config as C
from efficientroute.congestion import CongestionModel, sensitivity_levels


@pytest.fixture
def model() -> CongestionModel:
    return CongestionModel.from_config()


def frame(classes: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"highway_class": classes})


class TestScaling:
    def test_lambda_one_is_the_declared_assumption(self, model):
        assert model.value("primary", "am_peak") == C.CONGESTION_INDEX["primary"]["am_peak"]

    def test_lambda_zero_is_free_flow_for_every_class_and_band(self, model):
        free = model.scaled(0.0)
        for name in C.CONGESTION_INDEX:
            for band in free.band_names():
                assert free.value(name, band) == pytest.approx(1.0)

    def test_scaling_multiplies_the_delay_not_the_ratio(self, model):
        """+50% congestion on a 1.20 road is 1.30, not 1.80."""
        assert model.scaled(1.5).value("unclassified", "am_peak") == pytest.approx(1.30)

    def test_a_minus_25_percent_scale_reduces_the_delay_by_a_quarter(self, model):
        base = model.value("primary", "pm_peak") - 1.0
        assert model.scaled(0.75).value("primary", "pm_peak") - 1.0 == pytest.approx(
            base * 0.75
        )

    def test_an_unlisted_class_takes_the_declared_default(self, model):
        assert model.value("raceway", "midday") == C.CONGESTION_DEFAULT["midday"]

    def test_arterials_are_assumed_worse_than_residential_streets(self, model):
        assert model.value("primary", "am_peak") > model.value("residential", "am_peak")

    def test_peaks_are_assumed_worse_than_midday(self, model):
        for name in C.CONGESTION_INDEX:
            assert model.value(name, "am_peak") >= model.value(name, "midday")


class TestBands:
    def test_the_bands_tile_the_shift_window(self, model):
        assert sum(model.band_hours().values()) == pytest.approx(C.SHIFT_HOURS)
        assert model.bands[0][1] == 9.0
        assert model.bands[-1][2] == 18.0

    def test_overlap_of_the_whole_window_is_the_whole_band(self, model):
        assert model.overlap_hours(9.0, 18.0) == model.band_hours()

    def test_a_longer_depot_leg_pushes_capture_work_out_of_the_peaks(self, model):
        """SPEC §7.2 — the legs sit in the peaks, so long legs shield the work."""
        short = model.work_band_weights(0.25)
        long = model.work_band_weights(1.25)
        assert long["am_peak"] < short["am_peak"]
        assert long["pm_peak"] < short["pm_peak"]

    def test_the_break_comes_out_of_the_productive_window(self, model):
        weights = model.work_band_weights(0.5, break_hours=0.75)
        assert sum(weights.values()) == pytest.approx(9.0 - 2 * 0.5 - 0.75)

    def test_a_leg_long_enough_to_swallow_the_shift_leaves_no_work_time(self, model):
        weights = model.work_band_weights(5.0, break_hours=0.75)
        assert sum(weights.values()) == pytest.approx(0.0)

    def test_depot_legs_are_split_between_the_two_peaks(self, model):
        weights = model.leg_band_weights()
        assert set(weights) == {"am_peak", "pm_peak"}
        assert sum(weights.values()) == pytest.approx(1.0)


class TestBlending:
    def test_a_single_band_reproduces_that_band(self, model):
        arcs = frame(["primary", "service"])
        blended = model.blended_index(arcs, {"am_peak": 1.0})
        assert blended == pytest.approx(model.index_for(arcs, "am_peak"))

    def test_blending_lands_between_the_bands_it_mixes(self, model):
        arcs = frame(["primary"])
        weights = {"am_peak": 1.0, "midday": 1.0}
        blended = model.blended_index(arcs, weights)[0]
        assert model.value("primary", "midday") < blended < model.value("primary", "am_peak")

    def test_zero_weight_everywhere_is_free_flow_rather_than_a_divide_by_zero(self, model):
        arcs = frame(["primary"])
        assert model.blended_index(arcs, {"am_peak": 0.0})[0] == pytest.approx(1.0)

    def test_index_is_per_arc_not_per_network(self, model):
        arcs = frame(["primary", "service", "primary"])
        values = model.index_for(arcs, "am_peak")
        assert values[0] == values[2] > values[1]


class TestSerialisation:
    def test_round_trip_preserves_the_model(self, model):
        assert CongestionModel.from_dict(model.to_dict()).to_dict() == model.to_dict()

    def test_the_scale_survives_the_round_trip(self, model):
        scaled = model.scaled(1.25)
        assert CongestionModel.from_dict(scaled.to_dict()).scale == 1.25


def test_the_sensitivity_range_spans_what_the_gate_requires():
    levels = sensitivity_levels()
    assert min(levels) <= 0.75, "the brief requires at least -25%"
    assert max(levels) >= 1.5, "the brief requires at least +50%"
    assert 1.0 in levels, "the baseline must be in the sweep it is compared against"
    assert levels == sorted(set(levels)), "deterministic, deduplicated"
