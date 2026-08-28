"""SPEC §3.1 drivability filter.

CLAUDE.md rule 4: every exclusion carries a machine-readable reason and the row
stays in the table.  The reasons form a closed vocabulary so the report can group
by them without string wrangling.
"""

from __future__ import annotations

from collections.abc import Mapping

from . import config as C
from . import tags as T

Tags = Mapping[str, str]

#: The closed vocabulary of exclusion reasons.
REASONS: tuple[str, ...] = (
    "class_excluded",
    "area_feature",
    "access_private",
    "access_no",
    "barrier_blocking",
    "surface_impassable",
    "incline_too_steep",
)


def _clean(tags: Tags, key: str) -> str:
    value = tags.get(key)
    return "" if value is None else str(value).strip().lower()


def effective_access(tags: Tags) -> str | None:
    """The access value that actually governs a car.

    OSM resolves access from general to specific: ``access`` < ``vehicle`` <
    ``motor_vehicle`` < ``motorcar``.  A specific ``motorcar=yes`` therefore
    reopens a way that a blanket ``access=private`` had closed.
    """
    value: str | None = None
    for key in C.ACCESS_KEYS:
        raw = _clean(tags, key)
        if raw:
            value = raw
    return value


def is_blocking_barrier(tags: Tags) -> bool:
    """Whether a *node's* tags stop a passenger car outright."""
    barrier = _clean(tags, "barrier")
    if not barrier:
        return False
    if barrier in C.BLOCKING_BARRIERS:
        return True
    if barrier in C.CONDITIONAL_BARRIERS:
        if _clean(tags, "locked") in {"yes", "true"}:
            return True
        access = effective_access(tags)
        if access in C.ACCESS_PRIVATE_VALUES or access in C.ACCESS_NO_VALUES:
            return True
    return False


def classify_exclusion(
    tags: Tags, highway_class: str, blocking_barrier: bool = False
) -> str | None:
    """Return the exclusion reason for a way, or None if it stays in the network.

    Checks run in a fixed order so the reason attached to a way with several
    problems is deterministic.
    """
    if highway_class not in C.INCLUDED_HIGHWAY_CLASSES:
        return "class_excluded"
    if _clean(tags, "area") in {"yes", "true"}:
        return "area_feature"

    access = effective_access(tags)
    if access in C.ACCESS_PRIVATE_VALUES:
        return "access_private"
    if access in C.ACCESS_NO_VALUES:
        return "access_no"

    if blocking_barrier:
        return "barrier_blocking"

    if _clean(tags, "surface") in C.IMPASSABLE_SURFACES:
        return "surface_impassable"
    if _clean(tags, "smoothness") in C.IMPASSABLE_SMOOTHNESS:
        return "surface_impassable"

    incline = T.parse_incline(tags)
    if incline is not None and abs(incline) > C.MAX_INCLINE_PCT:
        return "incline_too_steep"

    return None
