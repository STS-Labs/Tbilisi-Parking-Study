"""Stage 4 item 5 — sunset over Tbilisi, and the taper it puts on the shift.

SPEC §7.3 was rewritten on Stage 3 evidence: daylight *is* binding now.  A shift
that ends at 18:00 is only nine hours long while the sun is still up at 18:00, and
in Tbilisi that stops being true at the start of November.  So the productive day
is not a constant, and a campaign that runs into late October loses time to the
taper before it loses it to darkness.

The implementation is the NOAA solar position algorithm — a closed form, no
ephemeris file, no dependency, and deterministic.  It is accurate to well under a
minute at this latitude, which is two orders of magnitude finer than anything the
schedule can act on.

`test_daylight.py` checks it against the four sunset times SPEC §7.3 states in
prose.  Those numbers were written before this module existed, so they are an
independent check rather than a restatement.
"""

from __future__ import annotations

import datetime as dt
import math

from . import config as C

#: Sun centre 0.833° below the horizon: half the solar disc (0.267°) plus the
#: standard 0.567° of atmospheric refraction.  The same convention every
#: published sunset table uses.
SUNSET_ZENITH_DEG = 90.833


def _fractional_year(day_of_year: int, hour: float = 12.0) -> float:
    return 2.0 * math.pi / 365.0 * (day_of_year - 1 + (hour - 12.0) / 24.0)


def equation_of_time_min(day_of_year: int) -> float:
    """Difference between apparent and mean solar time, in minutes."""
    g = _fractional_year(day_of_year)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )


def declination_rad(day_of_year: int) -> float:
    """Solar declination in radians."""
    g = _fractional_year(day_of_year)
    return (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.001480 * math.sin(3 * g)
    )


def sunset_hour(
    date: dt.date,
    latitude: float = C.DAYLIGHT_LAT,
    longitude: float = C.DAYLIGHT_LON,
    utc_offset_h: float = C.UTC_OFFSET_HOURS,
) -> float:
    """Local clock hour of sunset, as a float (18.5 = 18:30).

    Returns `math.inf` inside a polar summer and `-math.inf` inside a polar
    night; neither happens at 41.7° N, but returning a number that silently
    wrapped would be worse than returning one the caller can test.
    """
    day_of_year = date.timetuple().tm_yday
    declination = declination_rad(day_of_year)
    latitude_rad = math.radians(latitude)

    cos_ha = (
        math.cos(math.radians(SUNSET_ZENITH_DEG))
        / (math.cos(latitude_rad) * math.cos(declination))
        - math.tan(latitude_rad) * math.tan(declination)
    )
    if cos_ha < -1.0:
        return math.inf   # the sun never sets
    if cos_ha > 1.0:
        return -math.inf  # the sun never rises

    hour_angle_deg = math.degrees(math.acos(cos_ha))
    solar_noon_min = 720.0 - 4.0 * longitude - equation_of_time_min(day_of_year) + utc_offset_h * 60.0
    return (solar_noon_min + 4.0 * hour_angle_deg) / 60.0


def sunrise_hour(
    date: dt.date,
    latitude: float = C.DAYLIGHT_LAT,
    longitude: float = C.DAYLIGHT_LON,
    utc_offset_h: float = C.UTC_OFFSET_HOURS,
) -> float:
    day_of_year = date.timetuple().tm_yday
    declination = declination_rad(day_of_year)
    latitude_rad = math.radians(latitude)
    cos_ha = (
        math.cos(math.radians(SUNSET_ZENITH_DEG))
        / (math.cos(latitude_rad) * math.cos(declination))
        - math.tan(latitude_rad) * math.tan(declination)
    )
    if cos_ha < -1.0:
        return -math.inf
    if cos_ha > 1.0:
        return math.inf
    hour_angle_deg = math.degrees(math.acos(cos_ha))
    solar_noon_min = 720.0 - 4.0 * longitude - equation_of_time_min(day_of_year) + utc_offset_h * 60.0
    return (solar_noon_min - 4.0 * hour_angle_deg) / 60.0


def usable_end_hour(date: dt.date, shift_end_hour: float) -> float:
    """`min(shift_end, sunset)` — the hour the day actually stops being usable."""
    return min(shift_end_hour, sunset_hour(date))


def window_hours(date: dt.date, shift_start_hour: float, shift_end_hour: float) -> float:
    """Hours of shift the daylight actually covers, never negative."""
    return max(0.0, usable_end_hour(date, shift_end_hour) - shift_start_hour)


def taper_hours(date: dt.date, shift_start_hour: float, shift_end_hour: float) -> float:
    """Hours of the nominal shift lost to early sunset on this date."""
    nominal = max(0.0, shift_end_hour - shift_start_hour)
    return nominal - window_hours(date, shift_start_hour, shift_end_hour)


def hhmm(hour: float) -> str:
    """A float hour as `HH:MM`, for the report."""
    if not math.isfinite(hour):
        return "—"
    total = int(round(hour * 60.0))
    return f"{total // 60:02d}:{total % 60:02d}"
