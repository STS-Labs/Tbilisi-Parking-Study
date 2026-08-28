"""SPEC §2.1 — the passes model, and the §1.1 fallback chain that feeds it.

Two questions are decided here and they tie-break in *opposite* directions:

``min_passes``
    "Does this arc need a second same-direction pass?"  A second pass is the
    more demanding requirement, so §1.1 makes it the answer when the chain runs
    out of evidence.

``is_narrow_pair``
    "Does one traversal of this two-way street capture both sides?"  A shared
    pair requirement is the *cheaper* option, so it needs positive evidence;
    running out of evidence means both directions stay required.
"""

from __future__ import annotations

from . import config as C

Basis = str  # "lanes" | "width" | "class" | "default"


def min_passes_for(
    dir_lanes: int | None, dir_width_m: float | None, highway_class: str
) -> tuple[int, Basis]:
    """Required same-direction passes for one arc, plus the basis of the decision."""
    if dir_lanes is not None:
        return (2 if dir_lanes > C.WIDE_LANE_THRESHOLD else 1, "lanes")
    if dir_width_m is not None:
        return (2 if dir_width_m > C.WIDE_ARC_MIN_DIR_WIDTH_M else 1, "width")
    class_verdict = C.CLASS_IS_WIDE.get(highway_class)
    if class_verdict is not None:
        return (2 if class_verdict else 1, "class")
    return (C.DEFAULT_MIN_PASSES, "default")


def is_narrow_pair(
    total_lanes: int | None, width_m: float | None, highway_class: str
) -> tuple[bool, Basis]:
    """Whether a two-way pair shares a single traversal requirement."""
    if total_lanes is not None:
        return (total_lanes <= C.NARROW_PAIR_MAX_TOTAL_LANES, "lanes")
    if width_m is not None:
        return (width_m <= C.NARROW_PAIR_MAX_WIDTH_M, "width")
    if highway_class in C.CLASS_IS_NARROW_PAIR:
        return (True, "class")
    if highway_class in C.CLASS_IS_WIDE:
        return (False, "class")
    return (False, "default")


def capture_quality(highway_class: str) -> str:
    """SPEC §3.2 — motorway/trunk mainlines and ramps are captured degraded."""
    return "reduced" if highway_class in C.REDUCED_QUALITY_CLASSES else "full"


def required_traversals(
    min_passes: int, pair_requirement: int, is_pair_representative: bool
) -> int:
    """Traversals this arc contributes to the required-traversal total.

    ``pair_requirement > 0`` means the arc belongs to a narrow two-way pair whose
    requirement is shared: it is counted once for the pair, on the representative
    arc, and zero times on its twin.
    """
    if pair_requirement > 0:
        return pair_requirement if is_pair_representative else 0
    return min_passes
