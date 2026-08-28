"""Stage 5 — the artifacts a person actually uses.

Everything else in this project is analysis.  These are the files that go in the
car, so the bias is toward the driver: a route that is 3% suboptimal but
unambiguous at a junction beats one that is optimal and unclear.

Three outputs per day — a GPX track to follow, a turn-by-turn sheet to read, and
a row in the campaign GeoPackage — all generated from the same solved manoeuvre
sequence so they cannot disagree with each other.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

from . import config as C
from . import turngraph

COORD_PRECISION = 7

#: SPEC §2.3 — where an arc needs two same-direction passes, each pass must name a
#: different lane group or the driver repeats the same lane and the second pass is
#: wasted footage.  Right-hand traffic in Georgia, so pass 1 takes the kerb side.
LANE_GROUPS: tuple[str, ...] = ("right lanes", "left lanes", "centre lanes")


def lane_instruction(pass_number: int, total_passes: int) -> str:
    """Which lane group a given pass uses. Empty when only one pass is required."""
    if total_passes < 2:
        return ""
    group = LANE_GROUPS[min(pass_number, len(LANE_GROUPS)) - 1]
    return f"pass {pass_number} of {total_passes} — {group}"


def annotate(tour: np.ndarray, star, graph, required_passes: np.ndarray) -> list[dict]:
    """One row per step of the day: what to drive, and how to leave it.

    `pass_number` counts traversals of the *same arc within this day*, which is
    what the lane instruction has to key off — the second pass of a wide one-way
    is the one that needs different lanes, whether or not the first happened
    yesterday.
    """
    tour = np.asarray(tour, dtype="int64")
    seen: dict[int, int] = {}
    steps: list[dict] = []
    for index, node in enumerate(tour):
        node = int(node)
        seen[node] = seen.get(node, 0) + 1
        following = int(tour[(index + 1) % len(tour)])
        code, penalty = graph.adjacency[node][following]
        required = int(required_passes[node])
        steps.append(
            {
                "step": index + 1,
                "arc_node": node,
                "arc_id": str(star.arc_id[node]),
                "pass_number": seen[node],
                "required_passes": required,
                "is_capture": seen[node] <= required,
                "lane_instruction": lane_instruction(seen[node], required),
                "turn": turngraph.TURN_CLASSES[code],
                "turn_penalty_s": float(penalty),
                "next_arc_node": following,
            }
        )
    return steps


def write_gpx(path: Path, points: list[tuple[float, float]], name: str, description: str) -> Path:
    """One track, one segment. No timestamps, fixed precision — byte-reproducible."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="efficientroute stage5" '
            'xmlns="http://www.topografix.com/GPX/1/1">\n'
            "  <metadata>\n"
            f"    <name>{escape(name)}</name>\n"
            f"    <desc>{escape(description)}</desc>\n"
            "  </metadata>\n"
            "  <trk>\n"
            f"    <name>{escape(name)}</name>\n"
            "    <trkseg>\n"
        )
        for lon, lat in points:
            handle.write(
                f'      <trkpt lat="{lat:.{COORD_PRECISION}f}" '
                f'lon="{lon:.{COORD_PRECISION}f}"/>\n'
            )
        handle.write("    </trkseg>\n  </trk>\n</gpx>\n")
    return path


def route_coordinates(tour: np.ndarray, star, geometry_by_arc: dict) -> list[tuple[float, float]]:
    """The day as one polyline, in driving order, shared nodes written once.

    CLAUDE.md rule 1: every coordinate is copied from an arc's own geometry.

    The track is **not** the arc sequence with the first arc repeated at the end.
    A circuit closes because the last manoeuvre leads back to the first arc, which
    means the last arc *ends* where the first arc *begins* — so writing the arcs
    once already returns the track to its starting point.  Repeating the first arc
    drives it a second time and leaves the driver a whole street away from the
    depot, which is exactly the kind of plausible-looking error a closure check
    catches.
    """
    points: list[tuple[float, float]] = []
    for node in np.asarray(tour, dtype="int64"):
        coords = geometry_by_arc[str(star.arc_id[int(node)])]
        if points and points[-1] == coords[0]:
            points.extend(coords[1:])
        else:
            points.extend(coords)
    return points


TURN_WORDS = {
    "straight": "continue",
    "right": "turn right",
    "left": "turn left",
    "u_turn": "U-turn",
}


def _unverified_notice(steps: list[dict], unverified: set) -> str:
    """The warning at the head of a sheet that contains an unverified street."""
    hits = {step["arc_id"] for step in steps if step["arc_id"] in unverified}
    if not hits:
        return ""
    return (
        f"\n> **{len(hits)} arcs on this route are marked [UNVERIFIED].** They come "
        "from the customer's street layer and not from OpenStreetMap, so their "
        "direction, width and junction rules are assumptions, not tags. Treat them "
        "as two-way residential, obey what the signs actually say, and note any "
        "one-way, gate or building site you find — see "
        "`surveys/unverified-streets.md`.\n"
    )


def write_day_sheet(
    path: Path, day: dict, steps: list[dict], names: dict, lengths: dict,
    speeds: dict, unverified: set | None = None,
) -> Path:
    """A turn-by-turn sheet a driver can follow without the map.

    Consecutive steps along the same named street are folded into one line —
    a sheet with 1,500 rows saying "continue" is not usable, and the driver only
    needs an instruction where something changes.

    `unverified` names the arcs whose class, direction and width are assumptions
    rather than tags — streets taken from a customer layer that the OSM network
    could not carry. The flag has to reach *this* document or it is worthless: the
    driver is the instrument that settles them, and a warning that stops at a JSON
    artifact never reaches the windscreen. A run of steps breaks at the flag as well
    as at the street name, so an unverified street is never folded into a verified
    one's instruction.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Day {day['day']:02d} — {day['date']}\n",
        f"Zone {day['zone']} · {day['arc_traversals']:,} arc traversals · "
        f"{day['route_h']:.2f} h driving + {day['break_h']:.2f} h break = "
        f"**{day['day_h']:.2f} h**\n",
        f"Capture {day['capture_h']:.2f} h · deadhead {day['deadhead_h']:.2f} h · "
        f"turns {day['turn_h']:.2f} h\n",
        "\nStart and finish at the depot. **Capture** rows are required footage: "
        "keep to 40 km/h or below unless the row says *reduced*. **Deadhead** rows "
        "are repositioning — drive them normally, the camera is not counted.\n",
        _unverified_notice(steps, unverified),
        "\n| # | Street | Instruction | km | Mode | Lane |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ]

    unverified = unverified or set()

    def described(step: dict) -> tuple[str, str, str, bool]:
        return (
            names.get(step["arc_id"], "") or "(unnamed)",
            "capture" if step["is_capture"] else "deadhead",
            step["lane_instruction"],
            step["arc_id"] in unverified,
        )

    row = 0
    index = 0
    while index < len(steps):
        name, mode, lane, flagged = described(steps[index])
        distance = lengths.get(steps[index]["arc_id"], 0.0)
        # Fold a run along the same street into one instruction. OSM splits a
        # street at every junction it touches, so an unfolded sheet gives the
        # driver seven consecutive rows of "continue" for thirty metres of the
        # same road. The run breaks when the street, the mode or the lane group
        # changes — or at a U-turn, which is a real manoeuvre and must be said out
        # loud. Bends within one street are not instructions.
        while (
            index + 1 < len(steps)
            and steps[index]["turn"] != "u_turn"
            and described(steps[index + 1]) == (name, mode, lane)
        ):
            index += 1
            distance += lengths.get(steps[index]["arc_id"], 0.0)
        step = steps[index]
        row += 1
        label = f"{name} **[UNVERIFIED]**" if flagged else name
        lines.append(
            f"| {row} | {label} | {TURN_WORDS.get(step['turn'], step['turn'])} | "
            f"{distance / 1000.0:.2f} | {mode} | {lane or '—'} |"
        )
        index += 1

    lines.append(
        f"\n*{row:,} instructions folded from {len(steps):,} arc traversals. "
        "Generated by `efficientroute stage5`; every arc is from the base network.*\n"
    )
    path.write_text("\n".join(lines))
    return path
