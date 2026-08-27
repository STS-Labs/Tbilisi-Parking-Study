"""Stage 2 item 3 — day capacity and the campaign estimate.

Built on a hand-made four-arc network rather than on the city, so that the
arithmetic is checkable by hand.  `test_gate2` covers the real numbers.
"""
import math

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from efficientroute import campaign as CA
from efficientroute import config as C
from efficientroute.congestion import CongestionModel
from efficientroute.speedmodel import SpeedModel


class FakeGraph:
    """Just enough of a TurnGraph for the turn-time reader."""

    def __init__(self, rows):
        self.node_ids = [(arc_id, 0) for arc_id, _ in rows]
        self.adjacency = [{i: (0, p) for i, p in enumerate(penalties)}
                          for _, penalties in rows]


def network(distances_km=(1.0, 8.0, 13.0, 23.0)) -> gpd.GeoDataFrame:
    """Arcs placed due east of the depot at the requested straight-line distances."""
    rows, geometries = [], []
    for i, km in enumerate(distances_km):
        # ~111.32 km per degree of longitude at the equator; scaled for latitude.
        degrees = km / (111.320 * math.cos(math.radians(C.DEPOT_LAT)))
        lon = C.DEPOT_LON + degrees
        geometries.append(LineString([(lon, C.DEPOT_LAT), (lon + 1e-5, C.DEPOT_LAT)]))
        rows.append(
            {
                "arc_id": f"{i}:0:F", "highway_class": "residential", "maxspeed": np.nan,
                "length_m": 1000.0, "gradient_pct": 0.0, "gradient_source": "tag",
                "structure": "", "surface": "asphalt", "width": np.nan, "lanes": np.nan,
                "oneway": "yes", "capture_quality": "full", "excluded": False,
                "min_passes": 1, "pair_requirement": 0, "is_pair_representative": True,
                "from_node": i, "to_node": i + 1, "service_type": None,
                "service_role": "", "capture_speed_kmh": 30.0, "capture_time_s": 120.0,
            }
        )
    return gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")


@pytest.fixture
def model():
    return SpeedModel.from_config()


@pytest.fixture
def congestion():
    return CongestionModel.from_config()


class TestDepotGeometry:
    def test_distance_is_measured_from_the_depot(self):
        km = CA.depot_distance_km(network((1.0, 8.0, 13.0, 23.0)))
        assert km == pytest.approx([1.0, 8.0, 13.0, 23.0], abs=0.05)

    def test_bands_follow_the_declared_edges(self):
        index = CA.band_index(np.array([0.0, 4.9, 5.0, 12.0, 24.9, 25.0, 40.0]))
        assert index.tolist() == [0, 0, 1, 2, 4, 5, 5]

    def test_there_is_one_label_per_band(self):
        labels = CA.band_labels()
        assert len(labels) == len(C.DEPOT_DISTANCE_BANDS_KM) + 1
        assert labels[0].startswith("0")
        assert labels[-1].endswith("+")


class TestLegSpeed:
    def test_the_baseline_reproduces_the_spec_figure(self, congestion):
        """SPEC §7.1's "50–60 min each way in traffic" is the λ = 1 value."""
        assert CA.leg_speed_kmh(congestion) == pytest.approx(C.DEPOT_LEG_SPEED_KMH)

    def test_worse_congestion_slows_the_legs(self, congestion):
        assert CA.leg_speed_kmh(congestion.scaled(1.5)) < CA.leg_speed_kmh(congestion)

    def test_free_flow_legs_are_faster_than_the_spec_figure(self, congestion):
        assert CA.leg_speed_kmh(congestion.scaled(0.0)) > C.DEPOT_LEG_SPEED_KMH

    def test_the_detour_factor_comes_from_the_spec_worked_example(self):
        assert C.DEPOT_DETOUR_FACTOR == pytest.approx(30.0 / 22.0)


class TestDayModel:
    def test_a_zero_length_leg_leaves_the_shift_minus_the_break(self):
        assert CA.DayModel().productive_hours(0.0) == pytest.approx(
            C.SHIFT_HOURS - C.BREAK_HOURS
        )

    def test_both_legs_are_charged_not_one(self):
        day = CA.DayModel()
        assert day.productive_hours(1.0) == pytest.approx(C.SHIFT_HOURS - C.BREAK_HOURS - 2.0)


class TestTurnTime:
    def test_the_mean_and_the_floor_read_the_manoeuvres_available(self):
        graph = FakeGraph([("0:0:F", [0.0, 8.0]), ("1:0:F", [3.0])])
        mean_s, min_s = CA.turn_seconds_per_arc(graph)
        assert mean_s["0:0:F"] == pytest.approx(4.0)
        assert min_s["0:0:F"] == pytest.approx(0.0)
        assert mean_s["1:0:F"] == pytest.approx(3.0)

    def test_an_arc_with_no_legal_exit_is_absent_rather_than_zero(self):
        mean_s, _ = CA.turn_seconds_per_arc(FakeGraph([("0:0:F", []), ("1:0:F", [3.0])]))
        assert "0:0:F" not in mean_s

    def test_an_arc_absent_from_l_takes_its_class_mean_not_zero(self):
        frame = network()
        mean_s, min_s = CA.turn_seconds_per_arc(
            FakeGraph([("0:0:F", [6.0]), ("1:0:F", [2.0])])
        )
        out = CA.attach_turn_time(frame, mean_s, min_s)
        assert out["turn_mean_s"].tolist() == pytest.approx([6.0, 2.0, 4.0, 4.0])
        assert out["turn_mean_s"].notna().all()


class TestEstimate:
    def test_capture_hours_match_a_hand_computation(self, model, congestion):
        frame = CA.prepare(network((1.0,)))
        result = CA.estimate(frame, model, congestion.scaled(0.0))
        # 1 km of residential at 30 km/h free flow = 2 minutes
        assert result["capture_hours"] == pytest.approx(1.0 / 30.0, rel=1e-6)

    def test_turn_hours_are_counted_per_required_traversal(self, model, congestion):
        frame = CA.prepare(network((1.0, 1.5)))
        frame["turn_mean_s"] = 36.0
        frame["turn_min_s"] = 36.0
        result = CA.estimate(frame, model, congestion)
        assert result["turn_hours"] == pytest.approx(2 * 36.0 / 3600.0)

    def test_a_distant_band_has_less_productive_time_than_a_near_one(self, model, congestion):
        result = CA.estimate(CA.prepare(network((1.0, 23.0))), model, congestion)
        bands = [b for b in result["bands"] if b["required_km"] > 0]
        assert bands[0]["productive_hours"] > bands[-1]["productive_hours"]
        assert bands[0]["leg_hours"] < bands[-1]["leg_hours"]

    def test_a_bands_leg_uses_its_work_weighted_distance_not_its_edge(self, model, congestion):
        result = CA.estimate(CA.prepare(network((5.5, 9.5))), model, congestion)
        band = next(b for b in result["bands"] if b["required_km"] > 0)
        assert band["mean_depot_km"] == pytest.approx(7.5, abs=0.1)

    def test_days_is_work_over_productive_hours(self, model, congestion):
        result = CA.estimate(CA.prepare(network((1.0,))), model, congestion)
        band = next(b for b in result["bands"] if b["required_km"] > 0)
        assert band["days"] == pytest.approx(band["work_hours"] / band["productive_hours"])
        assert result["days"] == pytest.approx(band["days"])

    def test_the_floor_is_never_above_the_estimate(self, model, congestion):
        result = CA.estimate(CA.prepare(network()), model, congestion)
        assert result["turn_hours_floor"] <= result["turn_hours"]

    def test_an_empty_band_contributes_nothing(self, model, congestion):
        result = CA.estimate(CA.prepare(network((1.0,))), model, congestion)
        empty = [b for b in result["bands"] if b["required_km"] == 0]
        assert empty and all(b["days"] == 0.0 for b in empty)

    def test_a_leg_that_swallows_the_shift_is_reported_infeasible_not_negative(
        self, model, congestion
    ):
        frame = CA.prepare(network((400.0,)))
        result = CA.estimate(frame, model, congestion)
        assert result["infeasible_bands"]
        assert math.isinf(result["days"])
        assert result["days_rounded"] is None


class TestSensitivity:
    def test_more_congestion_never_shortens_the_campaign(self, model):
        frame = CA.prepare(network())
        rows = CA.sensitivity(model, frame)
        days = [r["days"] for r in rows]
        assert days == sorted(days)

    def test_the_baseline_row_is_its_own_reference(self, model):
        rows = CA.sensitivity(model, CA.prepare(network()))
        baseline = next(r for r in rows if r["scale"] == 1.0)
        assert baseline["delta_days"] == pytest.approx(0.0)
        assert baseline["delta_days_pct"] == pytest.approx(0.0)

    def test_the_sweep_spans_the_range_the_brief_requires(self, model):
        rows = CA.sensitivity(model, CA.prepare(network()))
        scales = [r["scale"] for r in rows]
        assert min(scales) <= 0.75 and max(scales) >= 1.5


class TestTurnSensitivity:
    def test_the_floor_gives_a_shorter_campaign_than_the_estimate(self, model, congestion):
        frame = CA.prepare(network())
        frame["turn_mean_s"], frame["turn_min_s"] = 20.0, 4.0
        out = CA.turn_sensitivity(frame, model, congestion)
        assert out["min_exit"]["days"] < out["mean_exit"]["days"]
        assert out["swing_days"] > 0


class TestDeadheadIllustration:
    def test_zero_deadhead_is_the_estimate_itself(self):
        rows = CA.deadhead_illustration(10.0)
        assert rows[0]["deadhead_ratio"] == 0.0
        assert rows[0]["days"] == pytest.approx(10.0)

    def test_it_scales_linearly_and_rounds_up(self):
        rows = CA.deadhead_illustration(10.0, (0.25,))
        assert rows[0]["days"] == pytest.approx(12.5)
        assert rows[0]["days_rounded"] == 13


class TestScopeVariants:
    def test_dropping_spurs_never_lengthens_the_campaign(self, model, congestion):
        frame = network()
        frame.loc[[2, 3], "highway_class"] = "service"
        frame.loc[2, "service_role"] = "through"
        frame.loc[3, "service_role"] = "spur"
        rows = CA.scope_variants(CA.prepare(frame), model, congestion)
        by_variant = {r["variant"]: r for r in rows}
        assert by_variant["A"]["days"] >= by_variant["D"]["days"] >= by_variant["C"]["days"]

    def test_variant_a_is_the_baseline_every_delta_is_measured_against(
        self, model, congestion
    ):
        rows = CA.scope_variants(CA.prepare(network()), model, congestion)
        assert rows[0]["variant"] == "A"
        assert rows[0]["delta_days"] == pytest.approx(0.0)
