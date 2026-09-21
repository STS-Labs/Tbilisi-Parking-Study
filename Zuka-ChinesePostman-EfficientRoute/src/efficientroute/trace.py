"""Stage 6 item 1 — the day's GPS trace, in one shape.

The rig's output format is not settled, so this reads the three plausible ones and
normalises them. Everything downstream sees a `Trace`: position, time, speed and
heading as parallel arrays, with speed and heading derived from the fixes when the
device does not report them.

Deriving heading rather than trusting the device is deliberate. A consumer GPS
reports heading from its own filter, which lags on a turn and is undefined at rest;
the fix-to-fix bearing is at least a quantity whose meaning is known. Where the
device does report it, it is kept — `read_*` fills the column and only the missing
entries are derived.
"""

from __future__ import annotations

import csv
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .bearings import bearing_deg

GPX_NS = {"g": "http://www.topografix.com/GPX/1/1"}

#: The baseline over which heading is measured, in metres.
#:
#: Not a per-fix threshold. A stationary car jitters a few metres a second and the
#: bearing between two jitters is uniformly random, so heading needs a baseline long
#: enough to be signal — but taking it from *consecutive* fixes makes it a function
#: of the log rate, and a fast rig then has no baseline at all. A 10 Hz trace at
#: 25 km/h puts its fixes 0.7 m apart; thresholding consecutive steps discards every
#: one of them and leaves the whole trace heading due north, which matches only
#: northbound arcs. Heading is therefore taken from the first later fix at least
#: this far away, whatever the rate.
HEADING_BASELINE_M = 3.0


@dataclass(frozen=True)
class Trace:
    """One day's fixes. All arrays are the same length and time-ordered."""

    lon: np.ndarray
    lat: np.ndarray
    t: np.ndarray
    speed_kmh: np.ndarray
    heading_deg: np.ndarray
    source: str = ""
    #: False when the file carried no timestamps and they were numbered instead.
    #: Speed is then meaningless, and SPEC §10.3's speed condition cannot be tested
    #: — which is not the same as it passing.
    has_time: bool = True

    def __len__(self) -> int:
        return len(self.lon)

    @property
    def duration_s(self) -> float:
        return float(self.t[-1] - self.t[0]) if len(self) > 1 else 0.0


def _metres(lon1, lat1, lon2, lat2) -> np.ndarray:
    """Equirectangular metres. Over a fix-to-fix step the error is far below GPS noise."""
    lat_mid = np.radians((lat1 + lat2) / 2.0)
    dx = np.radians(lon2 - lon1) * 6_371_000.0 * np.cos(lat_mid)
    dy = np.radians(lat2 - lat1) * 6_371_000.0
    return np.hypot(dx, dy)


def _derive(lon, lat, t, speed=None, heading=None, source="", has_time=True) -> Trace:
    lon = np.asarray(lon, dtype="float64")
    lat = np.asarray(lat, dtype="float64")
    t = np.asarray(t, dtype="float64")
    if len(lon) < 2:
        raise ValueError("a trace needs at least two fixes")

    step_m = _metres(lon[:-1], lat[:-1], lon[1:], lat[1:])
    step_s = np.diff(t)

    if speed is None or np.isnan(np.asarray(speed, dtype="float64")).any():
        derived = np.zeros(len(lon))
        with np.errstate(divide="ignore", invalid="ignore"):
            derived[1:] = np.where(step_s > 0, step_m / step_s * 3.6, 0.0)
        derived[0] = derived[1] if len(derived) > 1 else 0.0
        if speed is None:
            speed = derived
        else:
            speed = np.asarray(speed, dtype="float64")
            speed = np.where(np.isnan(speed), derived, speed)

    if heading is None or np.isnan(np.asarray(heading, dtype="float64")).any():
        n = len(lon)
        derived = np.full(n, np.nan)
        # Cumulative distance lets the baseline be found by search rather than by
        # walking forward from every fix, which would be quadratic on a 10 Hz day.
        cumulative = np.concatenate([[0.0], np.cumsum(step_m)])
        ahead = np.searchsorted(cumulative, cumulative + HEADING_BASELINE_M, side="left")
        for i in range(n):
            j = min(int(ahead[i]), n - 1)
            if j > i:
                derived[i] = bearing_deg(lon[i], lat[i], lon[j], lat[j])
        # A fix with no baseline ahead of it — the end of the trace, or a stop —
        # carries the last heading that meant something.
        last = np.nan
        for i in range(n):
            if math.isnan(derived[i]):
                derived[i] = last
            else:
                last = derived[i]
        backward = np.nan
        for i in range(n - 1, -1, -1):
            if math.isnan(derived[i]):
                derived[i] = backward
            else:
                backward = derived[i]
        derived = np.where(np.isnan(derived), 0.0, derived)
        if heading is None:
            heading = derived
        else:
            heading = np.asarray(heading, dtype="float64")
            heading = np.where(np.isnan(heading), derived, heading)

    return Trace(lon, lat, t, np.asarray(speed, "float64"),
                 np.asarray(heading, "float64"), source, has_time)


def synthesise(coords, speed_kmh, start_epoch: float = 0.0,
               hz: float = 1.0, dwell_s: dict | None = None) -> Trace:
    """Walk a polyline, one fix every `1/hz` seconds.

    `speed_kmh` is either a single speed for the whole walk, or one speed per
    segment of `coords`. The per-segment form exists because a constant-speed trace
    cannot distinguish one speed statistic from another: a car that crawls half a
    street and races the other half is the case the coverage speed rule is really
    about, and it has to be expressible here or the rule goes untested.

    Every gate assertion needs one of these, so it lives in the package rather than
    the tests: a synthetic trace is how the matcher is checked against a route whose
    answer is known, and Stage 7 will want the same generator for replay.
    """
    coords = [(float(x), float(y)) for x, y in coords]
    if len(coords) < 2:
        raise ValueError("need at least two coordinates")
    if np.isscalar(speed_kmh):
        speeds = [float(speed_kmh)] * (len(coords) - 1)
    else:
        speeds = [float(v) for v in speed_kmh]
        if len(speeds) != len(coords) - 1:
            raise ValueError("need one speed per segment")
    if min(speeds) <= 0:
        raise ValueError("speed must be positive")

    dwell_s = dwell_s or {}
    lon, lat, t = [coords[0][0]], [coords[0][1]], [start_epoch]
    carry = 0.0
    for index, ((x0, y0), (x1, y1), speed) in enumerate(zip(coords, coords[1:], speeds)):
        # Sitting at a junction: fixes keep arriving from the same place. This is
        # what makes turn penalties recoverable from a trace at all, so it has to be
        # expressible here or the extractor cannot be tested against a known answer.
        for _ in range(int(round(dwell_s.get(index, 0.0) * hz))):
            lon.append(x0)
            lat.append(y0)
            t.append(t[-1] + 1.0 / hz)
        step_m = speed / 3.6 / hz
        seg = float(_metres(np.array(x0), np.array(y0), np.array(x1), np.array(y1)))
        if seg <= 0:
            continue
        walked = step_m - carry
        while walked <= seg:
            f = walked / seg
            lon.append(x0 + (x1 - x0) * f)
            lat.append(y0 + (y1 - y0) * f)
            t.append(t[-1] + 1.0 / hz)
            walked += step_m
        carry = seg - (walked - step_m)
    # Always finish on the final vertex, so the last arc is fully traversed.
    if (lon[-1], lat[-1]) != coords[-1]:
        lon.append(coords[-1][0])
        lat.append(coords[-1][1])
        remainder = float(_metres(np.array(lon[-2]), np.array(lat[-2]),
                                  np.array(lon[-1]), np.array(lat[-1])))
        t.append(t[-1] + remainder / (speeds[-1] / 3.6))
    label = f"{speeds[0]:g}" if len(set(speeds)) == 1 else f"{min(speeds):g}-{max(speeds):g}"
    return _derive(lon, lat, t, source=f"synthetic@{label}kmh")


def read_gpx(path: Path) -> Trace:
    root = ET.parse(path).getroot()
    lon, lat, t = [], [], []
    timed = 0
    for point in root.iterfind(".//g:trkpt", GPX_NS):
        lon.append(float(point.get("lon")))
        lat.append(float(point.get("lat")))
        stamp = point.find("g:time", GPX_NS)
        if stamp is not None:
            t.append(_epoch(stamp.text))
            timed += 1
        else:
            # Numbered, not timed. Kept so the geometry is still usable, but flagged:
            # a planned route exported as GPX has no time in it, and scoring it as
            # though one point were one second invents speeds that reject real
            # coverage on a condition that was never actually tested.
            t.append(float(len(t)))
    return _derive(lon, lat, t, source=str(path), has_time=timed == len(lon) and timed > 0)


def read_csv(path: Path) -> Trace:
    """A CSV with lon/lat/time columns, and optionally speed and heading."""
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path} has no rows")
    keys = {k.lower().strip(): k for k in rows[0]}

    def column(*names, default=None):
        for name in names:
            if name in keys:
                return [r[keys[name]] for r in rows]
        return default

    lon = [float(v) for v in column("lon", "longitude", "x")]
    lat = [float(v) for v in column("lat", "latitude", "y")]
    raw_t = column("time", "timestamp", "t")
    t = [_epoch(v) if not _is_number(v) else float(v) for v in raw_t]
    speed = column("speed_kmh", "speed")
    heading = column("heading", "heading_deg", "course", "bearing")
    return _derive(
        lon, lat, t,
        speed=[_float_or_nan(v) for v in speed] if speed else None,
        heading=[_float_or_nan(v) for v in heading] if heading else None,
        source=str(path),
    )


def read_nmea(path: Path) -> Trace:
    """$GPRMC sentences — the lowest common denominator a rig will emit."""
    lon, lat, t, speed, heading = [], [], [], [], []
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.startswith(("$GPRMC", "$GNRMC")):
            continue
        f = line.split(",")
        if len(f) < 10 or f[2] != "A":
            continue  # 'V' is a void fix: the receiver is telling us not to trust it
        lat.append(_nmea_degrees(f[3], f[4]))
        lon.append(_nmea_degrees(f[5], f[6]))
        t.append(_nmea_epoch(f[9], f[1]))
        speed.append(float(f[7]) * 1.852 if f[7] else float("nan"))
        heading.append(float(f[8]) if f[8] else float("nan"))
    if not lon:
        raise ValueError(f"{path} contained no valid RMC fixes")
    return _derive(lon, lat, t, speed=speed, heading=heading, source=str(path))


def read(path) -> Trace:
    path = Path(path)
    match path.suffix.lower():
        case ".gpx":
            return read_gpx(path)
        case ".csv" | ".tsv" | ".txt":
            return read_csv(path)
        case ".nmea" | ".log":
            return read_nmea(path)
    raise ValueError(f"unrecognised trace format: {path.suffix}")


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _float_or_nan(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _epoch(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def _nmea_degrees(value: str, hemisphere: str) -> float:
    if not value:
        return float("nan")
    degrees = int(float(value) // 100)
    minutes = float(value) - degrees * 100
    signed = degrees + minutes / 60.0
    return -signed if hemisphere in ("S", "W") else signed


def _nmea_epoch(date: str, clock: str) -> float:
    day, month, year = int(date[0:2]), int(date[2:4]), 2000 + int(date[4:6])
    hour, minute = int(clock[0:2]), int(clock[2:4])
    second = float(clock[4:])
    return datetime(
        year, month, day, hour, minute, int(second),
        int((second % 1) * 1e6), tzinfo=timezone.utc,
    ).timestamp()
