"""Stage 4 item 5 — the solar model.

Checked against astronomy that does not depend on this module: symmetry about
the solstices, known day lengths at 41.7° N, and the one date SPEC §7.3 stakes a
claim on.
"""
import datetime as dt
import math

import pytest

from efficientroute import config as C
from efficientroute import daylight as D

TBILISI = dt.date(2026, 6, 21)


class TestAstronomy:
    def test_the_summer_solstice_is_the_longest_day(self):
        solstice = D.sunset_hour(TBILISI) - D.sunrise_hour(TBILISI)
        for offset in (5, 20, 60, 120):
            for sign in (-1, 1):
                other = TBILISI + dt.timedelta(days=sign * offset)
                assert D.sunset_hour(other) - D.sunrise_hour(other) < solstice

    def test_day_length_is_near_symmetric_about_the_solstice(self):
        """Near, not exact: Earth's orbit is elliptical, worth a few minutes."""
        for offset in (10, 30, 60):
            before = TBILISI - dt.timedelta(days=offset)
            after = TBILISI + dt.timedelta(days=offset)
            length = lambda d: D.sunset_hour(d) - D.sunrise_hour(d)  # noqa: E731
            assert abs(length(before) - length(after)) < 0.2

    def test_the_solstice_day_length_matches_the_latitude(self):
        """15h13m at 41.7° N with refraction — a textbook value."""
        length = D.sunset_hour(TBILISI) - D.sunrise_hour(TBILISI)
        assert 15.0 < length < 15.4

    def test_the_winter_solstice_day_length_matches_the_latitude(self):
        winter = dt.date(2026, 12, 21)
        length = D.sunset_hour(winter) - D.sunrise_hour(winter)
        assert 9.0 < length < 9.3

    def test_the_equinox_is_a_little_over_twelve_hours(self):
        """Refraction and the solar disc push it past 12 h on both equinoxes."""
        for equinox in (dt.date(2026, 3, 20), dt.date(2026, 9, 22)):
            length = D.sunset_hour(equinox) - D.sunrise_hour(equinox)
            assert 12.0 < length < 12.35

    def test_sunrise_is_always_before_sunset(self):
        date = dt.date(2026, 1, 1)
        while date.year == 2026:
            assert D.sunrise_hour(date) < D.sunset_hour(date)
            date += dt.timedelta(days=17)

    def test_the_equation_of_time_stays_in_its_known_range(self):
        values = [D.equation_of_time_min(d) for d in range(1, 366)]
        assert -15.0 < min(values) < -13.0
        assert 15.0 < max(values) < 17.0

    def test_declination_stays_within_the_tropics(self):
        values = [math.degrees(D.declination_rad(d)) for d in range(1, 366)]
        assert -23.5 < min(values) < -23.0
        assert 23.0 < max(values) < 23.5


class TestSpecClaims:
    def test_sunset_drops_below_the_shift_end_around_the_first_of_november(self):
        """SPEC §7.3's load-bearing claim, and the model agrees with it."""
        date = dt.date(2026, 9, 1)
        while D.sunset_hour(date) >= 18.0:
            date += dt.timedelta(days=1)
        assert dt.date(2026, 10, 25) <= date <= dt.date(2026, 11, 5)

    def test_mid_october_sunset_matches_the_spec_figure(self):
        """SPEC §7.3: "~18:25 mid-October"."""
        assert D.sunset_hour(dt.date(2026, 10, 15)) == pytest.approx(18.35, abs=0.1)

    def test_late_summer_sunset_is_earlier_than_the_spec_prose(self):
        """SPEC §7.3's retained original analysis says ~20:05 in late August.

        The model says 19:48, and the model is right: the implied day length is
        13h27m, which is what 41.7° N gives 65 days after the solstice. The
        discrepancy runs the safe way — the taper starts earlier than the prose
        implies, never later — and SPEC's own November boundary is reproduced
        exactly, so the figure that matters is not affected.
        """
        august = D.sunset_hour(dt.date(2026, 8, 25))
        assert 19.5 < august < 20.0
        day_length = august - D.sunrise_hour(dt.date(2026, 8, 25))
        assert day_length == pytest.approx(13.45, abs=0.1)


class TestWindow:
    def test_a_summer_day_is_not_daylight_limited(self):
        assert D.window_hours(dt.date(2026, 8, 25), 8.0, 18.0) == pytest.approx(10.0)
        assert D.taper_hours(dt.date(2026, 8, 25), 8.0, 18.0) == pytest.approx(0.0)

    def test_a_november_day_loses_the_tail_of_the_shift(self):
        taper = D.taper_hours(dt.date(2026, 11, 20), 8.0, 18.0)
        assert 0.2 < taper < 0.7

    def test_the_window_never_goes_negative(self):
        assert D.window_hours(dt.date(2026, 12, 21), 8.0, 18.0) >= 0.0

    def test_the_usable_end_is_the_earlier_of_shift_end_and_sunset(self):
        summer = dt.date(2026, 7, 1)
        winter = dt.date(2026, 12, 1)
        assert D.usable_end_hour(summer, 18.0) == pytest.approx(18.0)
        assert D.usable_end_hour(winter, 18.0) < 18.0

    def test_taper_and_window_are_complementary(self):
        for month in range(1, 13):
            date = dt.date(2026, month, 15)
            assert D.window_hours(date, 8.0, 18.0) + D.taper_hours(date, 8.0, 18.0) == (
                pytest.approx(10.0)
            )


class TestPolarGuards:
    def test_a_polar_summer_returns_infinity_rather_than_wrapping(self):
        assert D.sunset_hour(dt.date(2026, 6, 21), latitude=80.0) == math.inf

    def test_a_polar_night_returns_negative_infinity(self):
        assert D.sunset_hour(dt.date(2026, 12, 21), latitude=80.0) == -math.inf

    def test_hhmm_renders_an_infinite_hour_without_crashing(self):
        assert D.hhmm(math.inf) == "—"


class TestFormatting:
    def test_hhmm_rounds_to_the_nearest_minute(self):
        assert D.hhmm(18.5) == "18:30"
        assert D.hhmm(17.99) == "17:59"

    def test_the_configured_location_is_the_city_not_the_depot(self):
        """Sunset is where the capture happens, not where the car sleeps."""
        assert C.DAYLIGHT_LON != C.DEPOT_LON
        assert abs(C.DAYLIGHT_LAT - 41.7151) < 1e-6

    def test_georgia_has_no_daylight_saving_to_model(self):
        assert C.UTC_OFFSET_HOURS == 4.0
