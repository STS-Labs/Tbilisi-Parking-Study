"""Stage 2 — attaching the model to the arc table."""
import json

import numpy as np
import pandas as pd
import pytest

from efficientroute import config as C
from efficientroute import passes as P
from efficientroute import timemodel as TM
from efficientroute.speedmodel import SpeedModel


def table() -> pd.DataFrame:
    rows = [
        # a narrow two-way residential pair: shared requirement, counted once
        dict(arc_id="1:0:F", highway_class="residential", min_passes=1, pair_requirement=1,
             is_pair_representative=True),
        dict(arc_id="1:0:B", highway_class="residential", min_passes=1, pair_requirement=1,
             is_pair_representative=False),
        # a wide one-way needing two same-direction passes
        dict(arc_id="2:0:F", highway_class="primary", min_passes=2, pair_requirement=0,
             is_pair_representative=True),
        # a service spur
        dict(arc_id="3:0:F", highway_class="service", min_passes=1, pair_requirement=0,
             is_pair_representative=True),
    ]
    defaults = dict(
        maxspeed=float("nan"), length_m=1000.0, gradient_pct=0.0, gradient_source="tag",
        structure="", surface="asphalt", width=float("nan"), lanes=float("nan"),
        oneway="no", capture_quality="full", excluded=False, from_node=1, to_node=2,
        service_type=None,
    )
    return pd.DataFrame([defaults | row for row in rows])


class TestRequiredTraversals:
    def test_it_agrees_with_the_stage_zero_scalar_rule_row_by_row(self):
        frame = table()
        vector = TM.required_traversals(frame)
        scalar = [
            P.required_traversals(int(r.min_passes), int(r.pair_requirement),
                                  bool(r.is_pair_representative))
            for r in frame.itertuples()
        ]
        assert vector.tolist() == scalar

    def test_a_shared_pair_is_counted_once_not_twice(self):
        assert TM.required_traversals(table()).tolist() == [1, 0, 2, 1]


class TestAugment:
    def test_it_adds_exactly_the_three_stage_two_columns(self):
        before = set(table().columns)
        after = set(TM.augment(table()).columns)
        assert after - before == set(TM.STAGE2_COLUMNS)

    def test_it_is_idempotent(self):
        once = TM.augment(table())
        twice = TM.augment(once)
        pd.testing.assert_frame_equal(once, twice)

    def test_the_new_columns_sit_immediately_before_geometry(self):
        frame = table()
        frame["geometry"] = None
        columns = TM.augment(frame).columns.tolist()
        assert columns[-4:] == list(TM.STAGE2_COLUMNS) + ["geometry"]

    def test_capture_time_is_length_over_capture_speed(self):
        out = TM.augment(table())
        expected = out["length_m"] / (out["capture_speed_kmh"] / 3.6)
        assert out["capture_time_s"].to_numpy() == pytest.approx(expected.to_numpy())

    def test_every_row_gets_a_positive_time(self):
        out = TM.augment(table())
        assert out["capture_time_s"].notna().all()
        assert (out["capture_time_s"] > 0).all()

    def test_the_same_inputs_give_the_same_output(self):
        """CLAUDE.md rule 5."""
        pd.testing.assert_frame_equal(TM.augment(table()), TM.augment(table()))

    def test_a_different_model_gives_a_different_answer(self):
        """The columns follow the persisted coefficients, not a hard-coded table."""
        slow = SpeedModel.from_config().replace(default_free_flow_kmh=5.0,
                                                base_free_flow_kmh={})
        assert (
            TM.augment(table(), slow)["capture_time_s"].sum()
            > TM.augment(table())["capture_time_s"].sum()
        )


class TestCaptureHours:
    def test_it_sums_capture_time_over_required_traversals(self):
        out = TM.augment(table())
        traversals = TM.required_traversals(out)
        expected = (out["capture_time_s"].to_numpy() * traversals).sum() / 3600.0
        assert TM.capture_hours(out) == pytest.approx(expected)

    def test_the_non_representative_twin_contributes_nothing(self):
        out = TM.augment(table())
        without_twin = TM.augment(table().drop(index=1))
        assert TM.capture_hours(out) == pytest.approx(TM.capture_hours(without_twin))


class TestLoadModel:
    def test_a_missing_artifact_falls_back_to_the_config_prior(self, tmp_path):
        assert TM.load_model(tmp_path / "absent.json") == SpeedModel.from_config()

    def test_a_persisted_model_is_read_back_rather_than_rebuilt(self, tmp_path):
        model = SpeedModel.from_config().replace(narrow_width_factor=0.42)
        path = tmp_path / "02-time-model.json"
        path.write_text(json.dumps({"speed_model": model.to_dict()}))
        assert TM.load_model(path).narrow_width_factor == 0.42


class TestCaptureHoursUnderCongestion:
    def test_congestion_recomputes_rather_than_multiplying_the_column(self):
        """The 40 km/h cap means hours do not scale linearly with the index."""
        out = TM.augment(table())
        free = TM.capture_hours(out)
        congested = TM.capture_hours(out, np.full(len(out), 1.5))
        assert free < congested < free * 1.5

    def test_it_honours_a_supplied_model_rather_than_the_config_prior(self):
        out = TM.augment(table())
        slow = SpeedModel.from_config().replace(capture_speed_max_kmh=5.0)
        assert TM.capture_hours(out, 1.0, slow) > TM.capture_hours(out, 1.0)
