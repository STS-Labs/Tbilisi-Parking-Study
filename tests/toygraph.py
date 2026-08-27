"""Hand-built miniature L(G)s for the Stage 3 tests.

Small enough that every expected answer can be worked out on paper, which is the
point: the Stage 3 invariant suite is only worth anything if it was validated
against tours whose correctness was known independently of any solver.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from efficientroute import turngraph
from efficientroute.lstar import build as build_lstar

STRAIGHT, RIGHT, LEFT, U_TURN = 0, 1, 2, 3


def graph(arcs: list[dict], manoeuvres: dict[tuple[int, int], float]):
    """A `TurnGraph` over `arcs`, with the given manoeuvres and penalties.

    Each arc dict takes: `arc_id`, and optionally `min_passes`, `pair_id`,
    `pair_requirement`, `variant`.
    """
    rows = []
    for i, arc in enumerate(arcs):
        # Stage 4 collapses L onto physical segments, keyed by (way_id, seg_index),
        # so the toy arc ids carry the same "way:seg:direction" shape the real ones do.
        parts = str(arc["arc_id"]).split(":")
        rows.append(
            {
                "arc_id": arc["arc_id"],
                "way_id": arc.get("way_id", parts[0]),
                "seg_index": arc.get("seg_index", int(parts[1]) if len(parts) > 1 else 0),
                "variant": arc.get("variant", 0),
                "min_passes": arc.get("min_passes", 1),
                "pair_id": arc.get("pair_id", ""),
                "pair_requirement": arc.get("pair_requirement", 0),
                "is_pair_representative": arc.get("is_pair_representative", True),
                "length_m": arc.get("length_m", 1000.0),
                "highway_class": arc.get("highway_class", "residential"),
                "capture_quality": arc.get("capture_quality", "full"),
                "from_node": arc.get("from_node", i),
                "to_node": arc.get("to_node", i + 1),
            }
        )
    index = pd.DataFrame(rows)
    adjacency: list[dict[int, tuple[int, float]]] = [{} for _ in arcs]
    for (a, b), penalty in manoeuvres.items():
        adjacency[a][b] = (STRAIGHT, float(penalty))
    return turngraph.TurnGraph(
        node_ids=[(r["arc_id"], r["variant"]) for r in rows],
        adjacency=adjacency,
        arc_index=index,
        via_node=[0] * len(arcs),
    )


def square():
    """Four one-way arcs in a directed cycle: 0 → 1 → 2 → 3 → 0.

    Capture 100 s each, deadhead 80 s each, every manoeuvre 5 s.  A single lap is
    the whole requirement, so the optimal tour costs 4·100 + 4·5 = 420 s.
    """
    arcs = [{"arc_id": f"{i}:0:F"} for i in range(4)]
    turns = {(i, (i + 1) % 4): 5.0 for i in range(4)}
    g = graph(arcs, turns)
    star = build_lstar(
        g,
        capture_s=np.full(4, 100.0),
        deadhead_s=np.full(4, 80.0),
        lower_bounds=np.ones(4, dtype="int64"),
    )
    return g, star


def pair_square():
    """A directed cycle of four arcs where 0 and 1 are the two directions of one
    narrow two-way street, so exactly one of them is required.

    Layout: 0 and 1 are a pair; 2 and 3 are ordinary one-ways.  Manoeuvres form
    two overlapping cycles so that either orientation is drivable.
    """
    arcs = [
        {"arc_id": "9:0:F", "pair_id": "9:0", "pair_requirement": 1,
         "is_pair_representative": True},
        {"arc_id": "9:0:B", "pair_id": "9:0", "pair_requirement": 1,
         "is_pair_representative": False},
        {"arc_id": "2:0:F"},
        {"arc_id": "3:0:F"},
    ]
    turns = {
        (0, 2): 5.0, (2, 3): 5.0, (3, 0): 5.0,   # cycle using the F direction
        (1, 2): 5.0, (3, 1): 5.0,                # cycle using the B direction
    }
    g = graph(arcs, turns)
    star = build_lstar(
        g,
        capture_s=np.full(4, 100.0),
        deadhead_s=np.full(4, 80.0),
        lower_bounds=np.array([1, 0, 1, 1], dtype="int64"),  # oriented onto F
    )
    return g, star


def two_cycles():
    """Two disjoint 3-arc cycles with no manoeuvre between them.

    Balanced, coverable, and with no single Euler circuit — the failure mode that
    a connectivity check exists to catch.
    """
    arcs = [{"arc_id": f"{i}:0:F"} for i in range(6)]
    turns = {}
    for base in (0, 3):
        for i in range(3):
            turns[(base + i, base + (i + 1) % 3)] = 5.0
    g = graph(arcs, turns)
    star = build_lstar(
        g,
        capture_s=np.full(6, 100.0),
        deadhead_s=np.full(6, 80.0),
        lower_bounds=np.ones(6, dtype="int64"),
    )
    return g, star


def spur_and_loop():
    """A one-way loop plus a dead-end two-way spur — the real fragmentation case.

    This is how Tbilisi produces a thousand disconnected components.  The spur is
    a narrow pair, so exactly one direction is required.  The cheapest way to
    satisfy that requirement is to drive in, turn at the tip, and turn straight
    back in again — a self-contained two-cycle that touches nothing else and is
    perfectly balanced.  The flow finds it, and the result has no single circuit.

    Arcs 0,1,2 are the loop; 3 is junction → tip and 4 is tip → junction.
    """
    arcs = [
        {"arc_id": "0:0:F"},
        {"arc_id": "1:0:F"},
        {"arc_id": "2:0:F"},
        {"arc_id": "S:0:F", "pair_id": "S:0", "pair_requirement": 1,
         "is_pair_representative": True},
        {"arc_id": "S:0:B", "pair_id": "S:0", "pair_requirement": 1,
         "is_pair_representative": False},
    ]
    turns = {
        (0, 1): 5.0, (1, 2): 5.0, (2, 0): 5.0,   # the loop
        (1, 3): 5.0,                              # turn into the spur
        (3, 4): 5.0,                              # u-turn at the dead end
        (4, 2): 5.0,                              # come back out and carry on
        (4, 3): 5.0,                              # u-turn at the junction end
    }
    g = graph(arcs, turns)
    star = build_lstar(
        g,
        capture_s=np.full(5, 100.0),
        deadhead_s=np.full(5, 80.0),
        lower_bounds=np.array([1, 1, 1, 1, 0], dtype="int64"),
    )
    return g, star


def pair_index():
    """A tiny `arc_index` with two narrow pairs, for the orientation tests.

    Junction layout, with each pair between the same two junctions:
        pair P: 1 <-> 2      pair Q: 2 <-> 3
    plus a one-way 3 -> 1 that is required, which is what makes one orientation
    of each pair better than the other.
    """
    rows = [
        {"arc_id": "P:F", "variant": 0, "min_passes": 1, "pair_id": "P",
         "pair_requirement": 1, "is_pair_representative": True, "from_node": 1, "to_node": 2},
        {"arc_id": "P:B", "variant": 0, "min_passes": 1, "pair_id": "P",
         "pair_requirement": 1, "is_pair_representative": False, "from_node": 2, "to_node": 1},
        {"arc_id": "Q:F", "variant": 0, "min_passes": 1, "pair_id": "Q",
         "pair_requirement": 1, "is_pair_representative": True, "from_node": 2, "to_node": 3},
        {"arc_id": "Q:B", "variant": 0, "min_passes": 1, "pair_id": "Q",
         "pair_requirement": 1, "is_pair_representative": False, "from_node": 3, "to_node": 2},
        {"arc_id": "R:F", "variant": 0, "min_passes": 1, "pair_id": "",
         "pair_requirement": 0, "is_pair_representative": True, "from_node": 3, "to_node": 1},
    ]
    return pd.DataFrame(rows)


def zone_line(n: int = 8, capture_s: float = 600.0):
    """A chain of `n` one-way arcs, 0 → 1 → … → n-1, and its zone graph.

    A line is the most awkward shape a contiguity constraint can be given: every
    interior segment is an articulation point, so a balance pass can only move
    the two ends.  If the zoning code is going to strand a fragment, it will do it
    here.
    """
    import numpy as np

    from efficientroute import zoning

    arcs = [{"arc_id": f"{i}:0:F", "from_node": i, "to_node": i + 1} for i in range(n)]
    turns = {(i, i + 1): 5.0 for i in range(n - 1)}
    g = graph(arcs, turns)
    keep = np.ones(n, dtype=bool)
    zg = zoning.build(g, keep, np.full(n, capture_s), np.full(n, 1000.0))
    return g, zg


def zone_ring(n: int = 12, capture_s: float = 600.0):
    """A ring of `n` one-way arcs — connected, with no articulation points."""
    import numpy as np

    from efficientroute import zoning

    arcs = [{"arc_id": f"{i}:0:F", "from_node": i, "to_node": (i + 1) % n} for i in range(n)]
    turns = {(i, (i + 1) % n): 5.0 for i in range(n)}
    g = graph(arcs, turns)
    keep = np.ones(n, dtype=bool)
    zg = zoning.build(g, keep, np.full(n, capture_s), np.full(n, 1000.0))
    return g, zg


def arc_frame(rows: list[dict]):
    """A minimal Stage 0 arc table — enough for `turngraph.build_turn_graph`.

    Each row needs `arc_id`, `highway_class`, `from_node`, `to_node` and a
    two-point geometry; everything else takes a harmless default.
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    built = []
    geometries = []
    for i, row in enumerate(rows):
        parts = str(row["arc_id"]).split(":")
        built.append(
            {
                "arc_id": row["arc_id"],
                "way_id": int(parts[0]),
                "seg_index": int(parts[1]) if len(parts) > 1 else 0,
                "direction": parts[2] if len(parts) > 2 else "F",
                "from_node": row["from_node"],
                "to_node": row["to_node"],
                "highway_class": row.get("highway_class", "residential"),
                "name": row.get("name", ""),
                "length_m": row.get("length_m", 100.0),
                "lanes": row.get("lanes", float("nan")),
                "width": row.get("width", float("nan")),
                "maxspeed": float("nan"),
                "gradient_pct": 0.0,
                "min_passes": row.get("min_passes", 1),
                "pair_id": row.get("pair_id", ""),
                "pair_requirement": row.get("pair_requirement", 0),
                "is_pair_representative": row.get("is_pair_representative", True),
                "capture_quality": row.get("capture_quality", "full"),
                "excluded": False,
                "in_largest_scc": True,
            }
        )
        # Distinct geometry per arc so terminal bearings are well defined.
        geometries.append(LineString([(44.80 + i * 1e-3, 41.70), (44.80 + i * 1e-3, 41.701)]))
    return gpd.GeoDataFrame(built, geometry=geometries, crs="EPSG:4326")


def street(specs: list[dict], lat: float = 41.70, lon0: float = 44.80, seg_m: float = 120.0):
    """A straight west-east street whose geometry actually joins up.

    `arc_frame` gives every arc a parallel stub at a different longitude, which is
    fine for bearings and useless for map matching — a trace cannot be walked along
    a network that is not connected in space. Each spec becomes one arc from node
    `i` to node `i + 1`; a spec with `pair=True` also gets its reverse arc, sharing
    a `pair_id` so either direction satisfies the requirement.

    Returns `(frame, coords)` where `coords` is the west-east centreline, ready to
    hand to `trace.synthesise`.
    """
    import math

    import geopandas as gpd
    from shapely.geometry import LineString

    dlon = seg_m / (111_320.0 * math.cos(math.radians(lat)))
    nodes = [(lon0 + i * dlon, lat) for i in range(len(specs) + 1)]

    rows, geoms = [], []

    def add(arc_id, frm, to, geom, spec, representative):
        rows.append(
            {
                "arc_id": arc_id,
                "way_id": int(arc_id.split(":")[0]),
                "seg_index": int(arc_id.split(":")[1]),
                "direction": arc_id.split(":")[2],
                "from_node": frm,
                "to_node": to,
                "highway_class": spec.get("highway_class", "residential"),
                "name": spec.get("name", "Test Street"),
                "length_m": seg_m,
                "lanes": float("nan"),
                "width": float("nan"),
                "maxspeed": float("nan"),
                "gradient_pct": 0.0,
                "min_passes": spec.get("min_passes", 1),
                "pair_id": spec.get("pair_id", "") if spec.get("pair") else "",
                "pair_requirement": 1 if spec.get("pair") else 0,
                "is_pair_representative": representative,
                "capture_quality": spec.get("capture_quality", "full"),
                "capture_speed_kmh": spec.get("capture_speed_kmh", 30.0),
                "excluded": False,
                "in_largest_scc": True,
            }
        )
        geoms.append(geom)

    for i, spec in enumerate(specs):
        spec = dict(spec)
        spec.setdefault("pair_id", f"P{i}")
        forward = LineString([nodes[i], nodes[i + 1]])
        add(f"{100 + i}:0:F", i, i + 1, forward, spec, True)
        if spec.get("pair"):
            add(f"{100 + i}:0:B", i + 1, i, LineString([nodes[i + 1], nodes[i]]), spec, False)

    frame = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    return frame, nodes
