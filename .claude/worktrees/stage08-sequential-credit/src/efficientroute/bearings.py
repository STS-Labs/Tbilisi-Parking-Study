"""Turn geometry: bearings, signed turn deltas, and the turn class of a manoeuvre.

Bearings here are geographic — 0 = north, increasing clockwise — so a **positive**
delta is a right turn.  The whole turn-penalty table depends on that sign.

Terminal bearings are sampled over a short run of the geometry rather than read
off the last vertex pair: OSM centrelines carry metre-scale jitter, and a single
noisy vertex on a straight street would otherwise read as a turn and attract a
penalty.
"""

from __future__ import annotations

import math

from pyproj import Geod
from shapely.geometry import LineString

from . import config as C

_GEOD = Geod(ellps="WGS84")


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial geodesic bearing from point 1 to point 2, in [0, 360)."""
    azimuth, _, _ = _GEOD.inv(lon1, lat1, lon2, lat2)
    return azimuth % 360.0


def turn_delta_deg(incoming: float, outgoing: float) -> float:
    """Signed change of heading in (-180, 180]. Positive = right, negative = left."""
    delta = (outgoing - incoming) % 360.0
    if delta > 180.0:
        delta -= 360.0
    return 180.0 if delta == -180.0 else delta


def classify_turn(delta_deg: float) -> str:
    """Turn class from a signed delta, per the SPEC §3.3 penalty table."""
    magnitude = abs(delta_deg)
    if magnitude <= C.TURN_STRAIGHT_MAX_DEG:
        return "straight"
    if magnitude >= C.TURN_UTURN_MIN_DEG:
        return "u_turn"
    return "right" if delta_deg > 0 else "left"


def terminal_bearing(line: LineString, at: str, sample_m: float | None = None) -> float:
    """Direction of travel at one end of a directed arc.

    `at="end"` gives the heading with which the arc arrives at its head node;
    `at="start"` the heading with which it leaves its tail node.  Both are
    measured over roughly `sample_m` of geometry, falling back to the whole line
    when it is shorter than that.
    """
    sample_m = C.BEARING_SAMPLE_M if sample_m is None else sample_m
    coords = list(line.coords)
    if len(coords) < 2:
        raise ValueError("a bearing needs at least two coordinates")
    if at not in ("start", "end"):
        raise ValueError(f"at must be 'start' or 'end', got {at!r}")
    tip, anchor = _anchor(coords, at, sample_m)
    return bearing_deg(*anchor, *tip) if at == "end" else bearing_deg(*tip, *anchor)


def turn_penalty_s(turn_class: str) -> float:
    return C.TURN_PENALTY_S[turn_class]


def manoeuvre(incoming_line: LineString, outgoing_line: LineString) -> tuple[str, float]:
    """Turn class and signed delta for the manoeuvre from one arc to the next."""
    incoming = terminal_bearing(incoming_line, "end")
    outgoing = terminal_bearing(outgoing_line, "start")
    delta = turn_delta_deg(incoming, outgoing)
    return classify_turn(delta), delta


def _approx_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Equirectangular distance — used only to decide which vertex to anchor on.

    The anchor choice needs metres-scale accuracy, not geodesic accuracy; the
    bearing itself is still computed geodesically.  Doing the walk this way turns
    ~1M pyproj calls into arithmetic.
    """
    mean_lat = math.radians((lat1 + lat2) * 0.5)
    dx = math.radians(lon2 - lon1) * math.cos(mean_lat)
    dy = math.radians(lat2 - lat1)
    return math.hypot(dx, dy) * 6371008.8


def _anchor(coords: list[tuple[float, float]], at: str, sample_m: float):
    if at == "end":
        tip = coords[-1]
        walk = reversed(coords[:-1])
    else:
        tip = coords[0]
        walk = iter(coords[1:])

    anchor = tip
    travelled = 0.0
    for point in walk:
        anchor = point
        travelled = _approx_m(tip[0], tip[1], point[0], point[1])
        if travelled >= sample_m:
            break
    if travelled == 0.0:
        anchor = coords[0] if at == "end" else coords[-1]
    return tip, anchor


def terminal_bearings(lines, at: str, sample_m: float | None = None):
    """Vectorised `terminal_bearing` over many geometries."""
    import numpy as np

    sample_m = C.BEARING_SAMPLE_M if sample_m is None else sample_m
    tips: list[tuple[float, float]] = []
    anchors: list[tuple[float, float]] = []
    for line in lines:
        coords = list(line.coords)
        tip, anchor = _anchor(coords, at, sample_m)
        tips.append(tip)
        anchors.append(anchor)

    tip_arr = np.asarray(tips, dtype="float64")
    anchor_arr = np.asarray(anchors, dtype="float64")
    if at == "end":
        azimuth, _, _ = _GEOD.inv(anchor_arr[:, 0], anchor_arr[:, 1], tip_arr[:, 0], tip_arr[:, 1])
    else:
        azimuth, _, _ = _GEOD.inv(tip_arr[:, 0], tip_arr[:, 1], anchor_arr[:, 0], anchor_arr[:, 1])
    return np.asarray(azimuth) % 360.0
