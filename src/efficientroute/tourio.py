"""Stage 3 — write the constructive tour out as GPX.

A sanity artifact, not a plan.  It is one closed circuit of the whole city with
no depot legs, no day boundaries and no breaks, so it is not drivable as a
schedule and the report says so.  What it is good for is opening in any mapping
tool and seeing that the thing the solver produced is a real route over real
streets.

CLAUDE.md rule 1: every coordinate here is copied out of an arc's own geometry.
Nothing is interpolated, smoothed or joined by a synthesised connector — where
two consecutive arcs meet, the shared node is written once rather than twice,
which removes a duplicate point rather than inventing one.

No timestamps and a fixed coordinate precision, so two runs produce byte-identical
files (CLAUDE.md rule 5).
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

#: 7 decimal places is ~1 cm at this latitude — below any error in the source.
COORD_PRECISION = 7


def tour_coordinates(tour: np.ndarray, star, geometry_by_arc: dict) -> list[tuple[float, float]]:
    """The tour as one polyline, in order, with shared nodes written once."""
    points: list[tuple[float, float]] = []
    for node in np.asarray(tour, dtype="int64"):
        coords = geometry_by_arc[star.arc_id[node]]
        if points and points[-1] == coords[0]:
            points.extend(coords[1:])
        else:
            points.extend(coords)
    return points


def geometry_lookup(arcs) -> dict:
    """arc_id -> its coordinate list, straight off the Stage 0 geometry."""
    return {
        arc_id: list(geometry.coords)
        for arc_id, geometry in zip(arcs["arc_id"], arcs.geometry)
    }


def write_gpx(
    path: Path,
    points: list[tuple[float, float]],
    name: str,
    description: str,
) -> Path:
    """One track, one segment, one point per vertex."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="efficientroute stage3" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        "  <metadata>\n"
        f"    <name>{escape(name)}</name>\n"
        f"    <desc>{escape(description)}</desc>\n"
        "  </metadata>\n"
        "  <trk>\n"
        f"    <name>{escape(name)}</name>\n"
        "    <trkseg>\n"
    )
    footer = "    </trkseg>\n  </trk>\n</gpx>\n"

    with path.open("w", encoding="utf-8") as handle:
        handle.write(header)
        for lon, lat in points:
            handle.write(
                f'      <trkpt lat="{lat:.{COORD_PRECISION}f}" '
                f'lon="{lon:.{COORD_PRECISION}f}"/>\n'
            )
        handle.write(footer)
    return path
