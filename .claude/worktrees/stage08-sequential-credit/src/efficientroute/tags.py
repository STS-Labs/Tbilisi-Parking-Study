"""OSM tag parsing.

The §1.1 fallback chain is only as good as this module: a tag that fails to
parse is indistinguishable from an absent tag, and an absent tag pushes the arc
toward `min_passes = 2`.  Every parser therefore fails *closed* (returns None)
rather than guessing, and multi-valued tags resolve to the widest reading, which
is the more demanding one.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

Tags = Mapping[str, str]

_TRUE_ONEWAY = frozenset({"yes", "true", "1"})
_REVERSE_ONEWAY = frozenset({"-1", "reverse"})
_FALSE_ONEWAY = frozenset({"no", "false", "0"})

#: OSM wiki: oneway=yes is implied on highway=motorway.  It is *not* implied on
#: motorway_link, so those are left two-way unless tagged; Stage 0 reports how
#: many links rely on that.
_IMPLIED_ONEWAY_CLASSES = frozenset({"motorway"})
_IMPLIED_ONEWAY_JUNCTIONS = frozenset({"roundabout", "circular"})

_NUMBER = r"[+-]?\d+(?:\.\d+)?"
_FEET_RE = re.compile(rf"^({_NUMBER})\s*'\s*(?:({_NUMBER})\s*\"?)?$")
_METRE_RE = re.compile(rf"^({_NUMBER})\s*(?:m|meter|meters|metre|metres)?$")
_SPEED_RE = re.compile(rf"^({_NUMBER})\s*(mph|km/h|kmh|kph)?$")
_INCLINE_RE = re.compile(rf"^({_NUMBER})\s*(%|°|deg)?$")

_FEET_TO_M = 0.3048
_INCH_TO_M = 0.0254
_MPH_TO_KMH = 1.609344


def _clean(tags: Tags, key: str) -> str:
    value = tags.get(key)
    return "" if value is None else str(value).strip().lower()


def parse_oneway(tags: Tags) -> str:
    """Return ``"yes"``, ``"no"`` or ``"-1"`` (digitised direction reversed)."""
    raw = _clean(tags, "oneway")
    if raw in _TRUE_ONEWAY:
        return "yes"
    if raw in _REVERSE_ONEWAY:
        return "-1"
    if raw in _FALSE_ONEWAY:
        return "no"
    if _clean(tags, "junction") in _IMPLIED_ONEWAY_JUNCTIONS:
        return "yes"
    if _clean(tags, "highway") in _IMPLIED_ONEWAY_CLASSES:
        return "yes"
    return "no"


def is_oneway(tags: Tags) -> bool:
    return parse_oneway(tags) != "no"


def _lane_count(raw: object) -> int | None:
    if raw is None:
        return None
    values: list[int] = []
    for part in re.split(r"[;|]", str(raw)):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part)
        except ValueError:
            continue
        if value <= 0:
            continue
        # a fractional lane count rounds up: the wider reading (SPEC §1.1)
        values.append(math.ceil(value - 1e-9))
    return max(values) if values else None


def parse_lanes(tags: Tags) -> int | None:
    """Total lane count across both directions, or None."""
    return _lane_count(tags.get("lanes"))


def directional_lanes(tags: Tags, direction: str) -> int | None:
    """Lanes available to one direction of travel.

    ``lanes:forward`` / ``lanes:backward`` win outright.  Otherwise a one-way
    way keeps the whole ``lanes`` count and a two-way way splits it, rounding
    up so that an odd count resolves to the wider reading.
    """
    key = "lanes:forward" if direction == "forward" else "lanes:backward"
    explicit = _lane_count(tags.get(key))
    if explicit is not None:
        return explicit
    total = parse_lanes(tags)
    if total is None:
        return None
    if is_oneway(tags):
        return total
    return math.ceil(total / 2)


def _one_width(raw: str) -> float | None:
    text = raw.strip().lower().replace("’", "'")
    if not text:
        return None
    feet = _FEET_RE.match(text)
    if feet:
        value = float(feet.group(1)) * _FEET_TO_M + float(feet.group(2) or 0) * _INCH_TO_M
    else:
        metres = _METRE_RE.match(text)
        if not metres:
            return None
        value = float(metres.group(1))
    return value if value > 0 else None


def parse_width(tags: Tags) -> float | None:
    """Carriageway width in metres across both directions, or None."""
    raw = tags.get("width")
    if raw is None:
        return None
    values = [v for v in (_one_width(p) for p in str(raw).split(";")) if v is not None]
    return max(values) if values else None


def directional_width(tags: Tags) -> float | None:
    """Carriageway width available to one direction of travel."""
    total = parse_width(tags)
    if total is None:
        return None
    return total if is_oneway(tags) else total / 2.0


def parse_maxspeed(tags: Tags) -> float | None:
    """Posted speed in km/h, or None for `walk`, `none`, implicit zone codes."""
    raw = tags.get("maxspeed")
    if raw is None:
        return None
    match = _SPEED_RE.match(str(raw).strip().lower())
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2) == "mph":
        value *= _MPH_TO_KMH
    return value if value > 0 else None


def parse_incline(tags: Tags) -> float | None:
    """Tagged incline as a percentage.  Qualitative values (`up`) yield None."""
    raw = tags.get("incline")
    if raw is None:
        return None
    match = _INCLINE_RE.match(str(raw).strip().lower().replace(" ", ""))
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2) in ("°", "deg"):
        value = math.tan(math.radians(value)) * 100.0
    return value


def parse_service_type(tags: Tags) -> str | None:
    """The OSM `service=*` subtag, for `highway=service` ways only.

    SPEC §2.1 leaves `highway=service` open as a single yes/no, but the parent tag
    covers unrelated things: an alley is a street the campaign must capture, a
    driveway or a parking aisle is not.  The raw subtag is retained verbatim —
    normalised for case and whitespace, never reclassified — so the scope decision
    is made against the real distribution rather than against this module's
    opinion of it.

    Returns None for every non-service way, including the ones that carry a stray
    `service=*` tag of their own.
    """
    if _clean(tags, "highway") != "service":
        return None
    value = _clean(tags, "service")
    return value or "untagged"
