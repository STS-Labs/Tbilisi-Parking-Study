"""Way -> junction-split segment -> directed arc.

CLAUDE.md rule 1: every coordinate traces back to an OSM node.  Nothing here
interpolates, smooths or synthesises geometry — segments are built by slicing a
way's own node list, and a reversed arc reuses the same coordinates in reverse.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from pyproj import Geod
from shapely.geometry import LineString

_GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class ArcSkeleton:
    """A directed arc before geometry and tags are attached."""

    arc_id: str
    way_id: int
    seg_index: int
    from_node: int
    to_node: int
    node_ids: list[int] = field(compare=False)
    direction: str = "F"  # "F" follows the OSM way, "B" runs against it
    pair_id: str = ""


def dedupe_consecutive(node_ids: Iterable[int]) -> list[int]:
    out: list[int] = []
    for node in node_ids:
        if not out or out[-1] != node:
            out.append(node)
    return out


def find_junction_nodes(ways: Mapping[int, Sequence[int]]) -> set[int]:
    """Nodes where a segment must start or end.

    A node qualifies if it is a way endpoint, is shared by two or more ways, or
    appears twice within one way (a self-touching way that would otherwise hide
    a connection from the strongly-connected-component analysis).
    """
    junctions: set[int] = set()
    ways_per_node: Counter[int] = Counter()

    for node_ids in ways.values():
        clean = dedupe_consecutive(node_ids)
        if len(clean) < 2:
            continue
        junctions.add(clean[0])
        junctions.add(clean[-1])
        seen: set[int] = set()
        for node in clean:
            if node in seen:
                junctions.add(node)
            seen.add(node)
        for node in seen:
            ways_per_node[node] += 1

    junctions.update(node for node, count in ways_per_node.items() if count >= 2)
    return junctions


def split_way_into_segments(
    node_ids: Sequence[int], junction_ids: set[int]
) -> list[list[int]]:
    """Cut a way at every interior junction node."""
    clean = dedupe_consecutive(node_ids)
    if len(clean) < 2:
        return []

    segments: list[list[int]] = []
    start = 0
    for i in range(1, len(clean)):
        if clean[i] in junction_ids:
            segment = clean[start : i + 1]
            if len(segment) >= 2:
                segments.append(segment)
            start = i
    if start < len(clean) - 1:
        tail = clean[start:]
        if len(tail) >= 2:
            segments.append(tail)
    return segments


def directed_arcs(
    way_id: int, seg_index: int, node_ids: Sequence[int], oneway: str
) -> list[ArcSkeleton]:
    """One or two directed arcs for a segment, per SPEC §3.1."""
    base = f"{way_id}:{seg_index}"
    forward = list(node_ids)
    backward = list(reversed(node_ids))

    if oneway == "yes":
        return [ArcSkeleton(f"{base}:F", way_id, seg_index, forward[0], forward[-1], forward, "F", "")]
    if oneway == "-1":
        return [ArcSkeleton(f"{base}:B", way_id, seg_index, backward[0], backward[-1], backward, "B", "")]
    return [
        ArcSkeleton(f"{base}:F", way_id, seg_index, forward[0], forward[-1], forward, "F", base),
        ArcSkeleton(f"{base}:B", way_id, seg_index, backward[0], backward[-1], backward, "B", base),
    ]


def geodesic_length_m(line: LineString) -> float:
    """Length on the WGS84 ellipsoid.

    Geodesic rather than projected: it is direction-independent, needs no CRS
    choice, and does not accumulate projection error across the 40 km spread of
    the municipality.
    """
    return float(_GEOD.geometry_length(line))
