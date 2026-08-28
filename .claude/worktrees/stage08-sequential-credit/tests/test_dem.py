"""DEM sampling and gradient. SPEC §6: a 12% Tbilisi lane is 12 km/h, not 40."""
import numpy as np
import pytest
from affine import Affine

from efficientroute import dem as D


def _ramp_sampler():
    """3x3 grid, 1 degree pixels, origin at (0,3) going down; value == column index."""
    grid = np.array([[0.0, 10.0, 20.0], [0.0, 10.0, 20.0], [0.0, 10.0, 20.0]], dtype="float32")
    transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 3.0)
    return D.BilinearSampler(grid, transform, nodata=-32768.0)


class TestBilinearSampler:
    def test_samples_pixel_centres_exactly(self):
        s = _ramp_sampler()
        got = s.sample(np.array([0.5, 1.5, 2.5]), np.array([2.5, 2.5, 2.5]))
        assert got == pytest.approx([0.0, 10.0, 20.0])

    def test_interpolates_between_pixel_centres(self):
        s = _ramp_sampler()
        got = s.sample(np.array([1.0]), np.array([2.5]))
        assert got == pytest.approx([5.0])

    def test_outside_the_grid_is_nan(self):
        s = _ramp_sampler()
        got = s.sample(np.array([-5.0]), np.array([2.5]))
        assert np.isnan(got[0])

    def test_nodata_is_nan(self):
        grid = np.full((2, 2), -32768.0, dtype="float32")
        s = D.BilinearSampler(grid, Affine(1.0, 0.0, 0.0, 0.0, -1.0, 2.0), nodata=-32768.0)
        assert np.isnan(s.sample(np.array([0.5]), np.array([1.5]))[0])


class TestGradient:
    def test_uphill_is_positive(self):
        assert D.gradient_pct(100.0, 110.0, 200.0) == pytest.approx(5.0)

    def test_downhill_is_negative(self):
        assert D.gradient_pct(110.0, 100.0, 200.0) == pytest.approx(-5.0)

    def test_zero_length_is_zero_not_a_crash(self):
        assert D.gradient_pct(100.0, 110.0, 0.0) == 0.0

    def test_missing_elevation_is_nan(self):
        assert np.isnan(D.gradient_pct(float("nan"), 110.0, 200.0))


class TestTileCoverage:
    def test_bbox_maps_to_the_srtm_tiles_that_contain_it(self):
        assert D.srtm_tiles_for_bbox(44.5, 41.6, 45.1, 41.9) == ["N41E044", "N41E045"]

    def test_single_tile_bbox(self):
        assert D.srtm_tiles_for_bbox(44.7, 41.7, 44.8, 41.8) == ["N41E044"]

    def test_bbox_spanning_a_latitude_band(self):
        assert D.srtm_tiles_for_bbox(44.7, 41.9, 44.8, 42.1) == ["N41E044", "N42E044"]
