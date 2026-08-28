"""Stage 2 item 1 — the capture-speed model.

The tests that matter here are the ones that pin a constant to the thing it was
derived from.  `k` is not a tuning parameter; it is SPEC §6's worked example
rearranged, and if someone edits it the anchor test says so.
"""
import math

import numpy as np
import pandas as pd
import pytest

from efficientroute import config as C
from efficientroute.speedmodel import MIN_SPEED_KMH, SpeedModel


def arc(**overrides) -> pd.DataFrame:
    row = {
        "highway_class": "residential",
        "maxspeed": float("nan"),
        "length_m": 1000.0,
        "gradient_pct": 0.0,
        "gradient_source": "tag",
        "structure": "",
        "surface": "asphalt",
        "width": float("nan"),
        "lanes": float("nan"),
        "oneway": "no",
        "capture_quality": "full",
    }
    row.update(overrides)
    return pd.DataFrame([row])


@pytest.fixture
def model() -> SpeedModel:
    return SpeedModel.from_config()


class TestBaseSpeed:
    def test_class_table_sets_the_base(self, model):
        assert model.free_flow_kmh(arc(highway_class="primary"))[0] == pytest.approx(60.0)

    def test_posted_maxspeed_overrides_the_class(self, model):
        assert model.free_flow_kmh(arc(highway_class="residential", maxspeed=50.0))[0] == 50.0

    def test_an_unknown_class_falls_back_rather_than_producing_nan(self, model):
        speed = model.free_flow_kmh(arc(highway_class="somethingelse"))[0]
        assert speed == pytest.approx(C.BASE_FREE_FLOW_DEFAULT_KMH)

    def test_stage2_base_speeds_match_the_stage1_provisional_table(self):
        """Drift here would silently invalidate turn_graph.pkl's edge costs."""
        assert C.BASE_FREE_FLOW_KMH == C.PROVISIONAL_FREE_FLOW_KMH
        assert C.BASE_FREE_FLOW_DEFAULT_KMH == C.PROVISIONAL_DEFAULT_KMH


class TestGradient:
    def test_the_spec_anchor_reproduces_spec_six(self, model):
        """SPEC §6: "a 12% Tbilisi lane is 12 km/h, not 40"."""
        speed = model.capture_speed_kmh(
            arc(gradient_pct=12.0, gradient_source="tag", highway_class="residential")
        )[0]
        assert speed == pytest.approx(12.0, abs=0.01)

    def test_the_decay_constant_is_the_anchor_rearranged(self):
        derived = -math.log(C.GRADIENT_ANCHOR_FACTOR) / C.GRADIENT_ANCHOR_PCT
        assert C.GRADIENT_UPHILL_DECAY_PER_PCT == pytest.approx(derived, rel=1e-4)

    def test_flat_ground_costs_nothing(self, model):
        assert model.gradient_factor(arc(gradient_pct=0.0))[0] == pytest.approx(1.0)

    def test_downhill_costs_less_than_uphill(self, model):
        up = model.gradient_factor(arc(gradient_pct=8.0, gradient_source="tag"))[0]
        down = model.gradient_factor(arc(gradient_pct=-8.0, gradient_source="tag"))[0]
        assert up < down < 1.0

    def test_the_penalty_saturates_at_the_cap(self, model):
        at_cap = model.gradient_factor(arc(gradient_pct=12.0, gradient_source="tag"))[0]
        beyond = model.gradient_factor(arc(gradient_pct=40.0, gradient_source="tag"))[0]
        assert beyond == pytest.approx(at_cap)
        assert at_cap == pytest.approx(C.GRADIENT_ANCHOR_FACTOR, abs=1e-4)

    def test_a_bridge_is_flat_however_the_dem_reads_it(self, model):
        steep = arc(gradient_pct=15.0, gradient_source="dem", structure="bridge")
        assert model.effective_gradient_pct(steep)[0] == 0.0

    def test_a_tagged_incline_on_a_bridge_is_still_evidence(self, model):
        """The DEM is what a structure invalidates, not a surveyor's tag."""
        tagged = arc(gradient_pct=9.0, gradient_source="tag", structure="bridge")
        assert model.effective_gradient_pct(tagged)[0] == pytest.approx(9.0)

    def test_the_deadband_scales_with_one_over_length(self, model):
        short = model.gradient_deadband_pct(arc(length_m=25.0))[0]
        long = model.gradient_deadband_pct(arc(length_m=250.0))[0]
        assert short == pytest.approx(10 * long)
        assert short == pytest.approx(C.GRADIENT_DEM_NOISE_M / 25.0 * 100.0)

    def test_the_deadband_is_bounded_so_a_tiny_arc_keeps_a_real_grade(self, model):
        assert model.gradient_deadband_pct(arc(length_m=1.0))[0] == pytest.approx(
            C.GRADIENT_DEADBAND_MAX_PCT
        )

    def test_the_deadband_only_applies_to_dem_gradients(self, model):
        dem = arc(gradient_pct=2.0, gradient_source="dem", length_m=50.0)
        tag = arc(gradient_pct=2.0, gradient_source="tag", length_m=50.0)
        assert abs(model.effective_gradient_pct(dem)[0]) < abs(
            model.effective_gradient_pct(tag)[0]
        )

    def test_the_deadband_shrinks_toward_zero_and_never_flips_sign(self, model):
        small = arc(gradient_pct=0.4, gradient_source="dem", length_m=50.0)
        assert model.effective_gradient_pct(small)[0] == 0.0


class TestSurfaceAndWidth:
    def test_asphalt_is_the_reference(self, model):
        assert model.surface_factor_of(arc(surface="asphalt"))[0] == 1.0

    def test_loose_surfaces_are_slower_than_rough_pavement_which_is_slower_than_asphalt(
        self, model
    ):
        loose = model.surface_factor_of(arc(surface="gravel"))[0]
        rough = model.surface_factor_of(arc(surface="sett"))[0]
        assert loose < rough < 1.0

    def test_an_untagged_surface_takes_the_declared_default(self, model):
        assert model.surface_factor_of(arc(surface=""))[0] == C.SURFACE_DEFAULT_FACTOR

    def test_an_unrecognised_surface_value_also_takes_the_default(self, model):
        assert model.surface_factor_of(arc(surface="lunar_regolith"))[0] == (
            C.SURFACE_DEFAULT_FACTOR
        )

    def test_width_is_read_per_direction_on_a_two_way_street(self, model):
        """5 m total on a two-way street is 2.5 m each way, which is narrow."""
        assert model.is_narrow(arc(width=5.0, oneway="no"))[0]
        assert not model.is_narrow(arc(width=5.0, oneway="yes"))[0]

    def test_a_single_lane_two_way_street_is_narrow_without_a_width_tag(self, model):
        assert model.is_narrow(arc(lanes=1.0, oneway="no"))[0]
        assert not model.is_narrow(arc(lanes=1.0, oneway="yes"))[0]

    def test_untagged_width_and_lanes_are_not_treated_as_narrow(self, model):
        assert not model.is_narrow(arc())[0]


class TestCaptureCap:
    def test_a_fast_road_is_capped_at_forty(self, model):
        assert model.capture_speed_kmh(arc(highway_class="primary"))[0] == pytest.approx(40.0)

    def test_a_reduced_quality_arc_is_exempt(self, model):
        """SPEC §3.2 / invariant I7."""
        motorway = arc(highway_class="motorway", capture_quality="reduced")
        assert model.capture_speed_kmh(motorway)[0] == pytest.approx(90.0)

    def test_a_slow_street_is_untouched_by_the_cap(self, model):
        assert model.capture_speed_kmh(arc(highway_class="service"))[0] == pytest.approx(20.0)

    def test_deadhead_is_uncapped(self, model):
        """SPEC §6: "Deadhead segments are uncapped"."""
        assert model.unconstrained_kmh(arc(highway_class="primary"))[0] == pytest.approx(60.0)

    def test_congestion_is_applied_before_the_cap_not_after(self, model):
        """The ordering that makes the campaign estimate robust — see the report §4.1."""
        fast = arc(highway_class="primary")  # 60 km/h free flow
        assert model.capture_speed_kmh(fast, 1.2)[0] == pytest.approx(40.0)
        assert model.capture_speed_kmh(fast, 2.0)[0] == pytest.approx(30.0)

    def test_a_pathological_tag_cannot_produce_an_arc_that_takes_a_day(self, model):
        crawl = model.capture_speed_kmh(arc(maxspeed=1.0, surface="gravel"))[0]
        assert crawl == pytest.approx(MIN_SPEED_KMH)


class TestTime:
    def test_time_is_length_over_speed(self, model):
        seconds = model.capture_time_s(arc(highway_class="service", length_m=2000.0))[0]
        assert seconds == pytest.approx(2.0 / 20.0 * 3600.0)

    def test_congestion_lengthens_time_where_the_cap_does_not_bind(self, model):
        base = model.capture_time_s(arc(highway_class="service"))[0]
        congested = model.capture_time_s(arc(highway_class="service"), 1.25)[0]
        assert congested == pytest.approx(base * 1.25)


class TestSerialisation:
    def test_round_trip_is_exact(self, model):
        assert SpeedModel.from_dict(model.to_dict()) == model

    def test_an_unknown_field_is_an_error_not_a_silent_drop(self, model):
        payload = model.to_dict() | {"vibes": 1.0}
        with pytest.raises(ValueError):
            SpeedModel.from_dict(payload)

    def test_replace_leaves_the_original_untouched(self, model):
        other = model.replace(narrow_width_factor=0.5)
        assert other.narrow_width_factor == 0.5
        assert model.narrow_width_factor == C.NARROW_WIDTH_FACTOR


class TestFit:
    """Stage 6's entry point.  Generate from a known model, recover it."""

    @staticmethod
    def population(truth: SpeedModel, n: int = 600) -> pd.DataFrame:
        rng = np.random.default_rng(20260825)  # CLAUDE.md rule 5
        classes = ["residential", "service", "tertiary", "primary"]
        surfaces = ["asphalt", "gravel", "sett", ""]
        return pd.DataFrame(
            {
                "highway_class": rng.choice(classes, n),
                "maxspeed": np.full(n, np.nan),
                "length_m": rng.uniform(50.0, 500.0, n),
                "gradient_pct": rng.uniform(-14.0, 14.0, n),
                "gradient_source": np.full(n, "tag"),
                "structure": np.full(n, ""),
                "surface": rng.choice(surfaces, n),
                "width": np.where(rng.random(n) < 0.3, 4.0, np.nan),
                "lanes": np.full(n, np.nan),
                "oneway": np.full(n, "no"),
                "capture_quality": np.full(n, "full"),
            }
        )

    def test_fit_recovers_the_model_that_generated_the_data(self):
        truth = SpeedModel.from_config()
        frame = self.population(truth)
        observed = truth.unconstrained_kmh(frame)

        prior = truth.replace(
            base_free_flow_kmh={k: 25.0 for k in truth.base_free_flow_kmh},
            surface_factor={k: 0.9 for k in truth.surface_factor},
            narrow_width_factor=1.0,
            gradient_uphill_decay_per_pct=0.02,
            gradient_downhill_decay_per_pct=0.02,
        )
        fitted, diagnostics = prior.fit(frame, observed)

        assert diagnostics["log_rmse"] < 1e-8
        assert fitted.gradient_uphill_decay_per_pct == pytest.approx(
            truth.gradient_uphill_decay_per_pct, rel=1e-4
        )
        assert fitted.gradient_downhill_decay_per_pct == pytest.approx(
            truth.gradient_downhill_decay_per_pct, rel=1e-4
        )
        assert fitted.narrow_width_factor == pytest.approx(truth.narrow_width_factor, rel=1e-4)
        for name in ("residential", "service", "tertiary", "primary"):
            assert fitted.base_free_flow_kmh[name] == pytest.approx(
                truth.base_free_flow_kmh[name], rel=1e-4
            )
        for name in ("asphalt", "gravel", "sett"):
            assert fitted.surface_factor[name] == pytest.approx(
                truth.surface_factor[name], rel=1e-4
            )

    def test_fit_divides_congestion_back_out(self):
        """A rush-hour trace must not permanently slow the class table."""
        truth = SpeedModel.from_config()
        frame = self.population(truth)
        index = np.full(len(frame), 1.4)
        observed = truth.unconstrained_kmh(frame, index)

        fitted, _ = truth.fit(frame, observed, congestion_index=index)
        assert fitted.base_free_flow_kmh["residential"] == pytest.approx(30.0, rel=1e-4)

    def test_a_coefficient_with_no_observations_keeps_its_prior(self):
        truth = SpeedModel.from_config()
        frame = self.population(truth)
        fitted, _ = truth.fit(frame, truth.unconstrained_kmh(frame))
        assert fitted.base_free_flow_kmh["motorway"] == truth.base_free_flow_kmh["motorway"]

    def test_a_posted_maxspeed_enters_as_an_offset_not_a_class_column(self):
        truth = SpeedModel.from_config()
        frame = self.population(truth)
        frame.loc[frame.index[:100], "maxspeed"] = 55.0
        matrix, columns, offset = truth.design(frame)

        posted = frame["maxspeed"].notna().to_numpy()
        class_columns = [i for i, c in enumerate(columns) if c.startswith("log_base_kmh[")]
        assert matrix[posted][:, class_columns].sum() == 0.0
        assert offset[posted] == pytest.approx(math.log(55.0))
        assert offset[~posted] == pytest.approx(0.0)

    def test_fit_refuses_an_empty_observation_set(self):
        truth = SpeedModel.from_config()
        frame = self.population(truth, n=10)
        with pytest.raises(ValueError):
            truth.fit(frame, np.zeros(10))

    def test_fit_ignores_unusable_observations_rather_than_failing(self):
        truth = SpeedModel.from_config()
        frame = self.population(truth)
        observed = truth.unconstrained_kmh(frame)
        observed[:50] = np.nan
        fitted, diagnostics = truth.fit(frame, observed)
        assert diagnostics["n_observations"] == len(frame) - 50
        assert fitted.base_free_flow_kmh["residential"] == pytest.approx(30.0, rel=1e-4)
