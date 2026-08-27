"""Audit L(G): strong components, reachable coverage, traps.

The critical check of Stage 1 is that components are computed **on L, not on the
base network**.  An arc can be present and reachable in the base graph and still
be a legal trap once turn restrictions apply — enterable, but not leavable.
"""

from __future__ import annotations

import collections

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

from . import config as C
from .turngraph import TURN_CLASSES, TurnGraph


def strong_components(adjacency: list[dict]) -> tuple[np.ndarray, int]:
    """Strongly connected components of an adjacency list, and the largest label."""
    n = len(adjacency)
    src: list[int] = []
    dst: list[int] = []
    for a, row in enumerate(adjacency):
        for b in row:
            src.append(a)
            dst.append(b)
    matrix = csr_matrix(
        (np.ones(len(src), dtype=np.int8), (src, dst)), shape=(n, n)
    )
    _, labels = connected_components(matrix, directed=True, connection="strong")
    largest = int(np.argmax(np.bincount(labels)))
    return labels, largest


def reachable_required_km(frame: pd.DataFrame, reachable: np.ndarray) -> float:
    """Required traversal km that a mask of reachable arcs still satisfies.

    SPEC §3.4: an arc with `min_passes = k` contributes `k x length` when it is
    reachable, but a narrow two-way pair contributes its length once as long as
    **either** direction is reachable.
    """
    lengths = frame["length_m"].to_numpy(dtype="float64")
    passes = frame["min_passes"].to_numpy(dtype="float64")
    shared = frame["pair_requirement"].to_numpy(dtype="float64") > 0
    pair_ids = frame["pair_id"].fillna("").to_numpy()
    reachable = np.asarray(reachable, dtype=bool)

    total = float((lengths * passes)[reachable & ~shared].sum())
    pairs: dict[str, list] = {}
    for i in np.flatnonzero(shared):
        entry = pairs.setdefault(pair_ids[i], [lengths[i], False])
        entry[1] = entry[1] or bool(reachable[i])
    total += sum(length for length, ok in pairs.values() if ok)
    return total / 1000.0


def reachable_arc_ids(graph: TurnGraph) -> set[str]:
    """Arc ids with at least one variant inside L's largest strong component."""
    labels, largest = strong_components(graph.adjacency)
    index = graph.arc_index.assign(in_largest=(labels == largest))
    return set(index.loc[index["in_largest"], "arc_id"])


def attribute_losses(arcs, parsed, lost_arc_ids: list[str], boundary=None) -> dict[str, str]:
    """Name the cause of every arc that fell out of L's largest component.

    Counterfactual builds, in order of how actionable the answer is: if the arc
    comes back when restrictions are dropped, a restriction stranded it; if it
    comes back under a permissive U-turn rule, the §3.3 U-turn policy did; if it
    comes back without the mainline-entry rule, that rule did.  Anything that
    survives all three and lies only in the clip buffer is an edge-of-extract
    artefact rather than a Tbilisi problem.
    """
    from .restrictions import ParsedRestrictions
    from .turngraph import build_turn_graph

    remaining = set(lost_arc_ids)
    causes: dict[str, str] = {}
    if not remaining:
        return causes

    trials = (
        ("turn_restrictions", dict(parsed=ParsedRestrictions())),
        ("u_turn_policy", dict(parsed=parsed, permissive_u_turns=True)),
        ("mainline_entry_rule", dict(parsed=parsed, mainline_entry_classes=frozenset())),
    )
    for cause, kwargs in trials:
        if not remaining:
            break
        trial_parsed = kwargs.pop("parsed")
        recovered = reachable_arc_ids(build_turn_graph(arcs, trial_parsed, **kwargs))
        for arc_id in sorted(remaining & recovered):
            causes[arc_id] = cause
        remaining -= recovered

    if remaining and boundary is not None:
        indexed = arcs.set_index("arc_id")
        for arc_id in sorted(remaining):
            inside = boundary.intersects(indexed.loc[arc_id].geometry)
            causes[arc_id] = "base_topology" if inside else "clip_buffer_edge"
    else:
        for arc_id in sorted(remaining):
            causes[arc_id] = "base_topology"
    return causes


def audit(
    graph: TurnGraph,
    meta: dict | None = None,
    node_lonlat: dict | None = None,
    clip=None,
) -> dict:
    """Every number `reports/01-turn-audit.md` and the Stage 1 gate need."""
    labels, largest = strong_components(graph.adjacency)
    in_largest = labels == largest

    index = graph.arc_index.copy()
    index["scc_label"] = labels
    index["in_largest_scc"] = in_largest

    originals = index[index["variant"] == 0].reset_index(drop=True)
    # an arc is reachable if any of its variants sits in the largest component
    reachable_arcs = (
        index.groupby("arc_id")["in_largest_scc"].any().reindex(originals["arc_id"]).to_numpy()
    )

    total_km = reachable_required_km(originals, np.ones(len(originals), dtype=bool))
    reachable_km = reachable_required_km(originals, reachable_arcs)

    out_degree = graph.out_degrees()
    in_degree = graph.in_degrees()
    lost = originals[~reachable_arcs]

    return {
        "meta": dict(meta or {}),
        "graph": _graph_stats(graph, index),
        "restrictions": _restriction_stats(graph),
        "u_turns": _u_turn_stats(graph, index),
        "traps": _trap_stats(graph, index, out_degree, in_degree, node_lonlat, clip),
        "scc": {
            "component_count": int(labels.max() + 1),
            "largest_node_count": int(in_largest.sum()),
            "largest_share_of_nodes": float(in_largest.mean()),
            "required_km_total": total_km,
            "required_km_reachable": reachable_km,
            "required_km_lost": total_km - reachable_km,
            "share_of_required_km": reachable_km / total_km if total_km else 0.0,
            "lost_arc_count": int(len(lost)),
            "lost_arc_km": float(lost["length_m"].sum() / 1000.0),
            "lost_by_class": _by_class(lost),
            "lost_rows": _lost_rows(lost),
        },
    }


def _graph_stats(graph: TurnGraph, index: pd.DataFrame) -> dict:
    counts: collections.Counter[str] = collections.Counter()
    for row in graph.adjacency:
        for code, _ in row.values():
            counts[TURN_CLASSES[code]] += 1
    return {
        "nodes": graph.n_nodes,
        "arc_nodes": int((index["variant"] == 0).sum()),
        "clone_nodes": int((index["variant"] > 0).sum()),
        "edges": graph.n_edges,
        "edges_before_restrictions": int(graph.meta.get("edges_before_restrictions", 0)),
        "mean_out_degree": graph.mean_out_degree,
        "turn_class_counts": {k: counts.get(k, 0) for k in TURN_CLASSES},
        "turn_penalty_s": graph.meta.get("turn_penalty_s", {}),
        "mainline_entry_via_ramps_only": graph.meta.get("mainline_entry_via_ramps_only", []),
    }


def _restriction_stats(graph: TurnGraph) -> dict:
    log = graph.restriction_log
    by_status: collections.Counter[str] = collections.Counter(r["status"] for r in log)
    by_detail: collections.Counter[str] = collections.Counter(
        r["detail"] for r in log if r["status"] == "unresolvable"
    )
    return {
        "resolved_total": len(log),
        "applied": int(by_status.get("applied", 0)),
        "unresolvable": int(by_status.get("unresolvable", 0)),
        "unresolvable_by_reason": dict(sorted(by_detail.items())),
        "via_way": sum(1 for r in log if r["via"] == "way"),
        "via_node": sum(1 for r in log if r["via"] == "node"),
        "clones_created": sum(r["clones_created"] for r in log),
        "edges_removed_total": sum(r["edges_removed"] for r in log),
        "edges_removed_no": sum(r["edges_removed"] for r in log if r["kind"] == "no"),
        "edges_removed_only": sum(r["edges_removed"] for r in log if r["kind"] == "only"),
        "edges_already_absent": sum(r["edges_already_absent"] for r in log),
        "by_type": dict(
            sorted(collections.Counter(f"{r['kind']}_{r['manoeuvre']}" for r in log).items())
        ),
    }


def _u_turn_stats(graph: TurnGraph, index: pd.DataFrame) -> dict:
    reasons = graph.u_turn_reasons()
    reverse = _reverse_arc_map(index)
    arc_of = index["arc_id"].tolist()

    reverse_edges = hairpin_edges = 0
    for src, row in enumerate(graph.adjacency):
        for dst, (code, _) in row.items():
            if TURN_CLASSES[code] != "u_turn":
                continue
            if reverse.get(arc_of[src]) == arc_of[dst]:
                reverse_edges += 1
            else:
                hairpin_edges += 1

    return {
        "total": sum(reasons.values()),
        "reverse_arc_edges": reverse_edges,
        "hairpin_edges": hairpin_edges,
        "by_reason": reasons,
        "min_width_m": graph.meta.get("u_turn_min_width_m"),
        "min_total_lanes": graph.meta.get("u_turn_min_total_lanes"),
        "no_u_turn_classes": sorted(C.NO_U_TURN_CLASSES),
    }


def _reverse_arc_map(index: pd.DataFrame) -> dict[str, str]:
    by_pair: dict[str, dict[str, str]] = {}
    for arc_id, pair_id, direction, variant in zip(
        index["arc_id"], index["pair_id"].fillna(""), index["direction"], index["variant"]
    ):
        if pair_id and not variant:
            by_pair.setdefault(pair_id, {})[direction] = arc_id
    out: dict[str, str] = {}
    for members in by_pair.values():
        if "F" in members and "B" in members:
            out[members["F"]] = members["B"]
            out[members["B"]] = members["F"]
    return out


def _trap_stats(graph, index, out_degree, in_degree, node_lonlat=None, clip=None) -> dict:
    no_out = np.flatnonzero(out_degree == 0)
    no_in = np.flatnonzero(in_degree == 0)
    rows = []
    for kind, indices in (("no_legal_exit", no_out), ("no_legal_entry", no_in)):
        for i in indices:
            row = index.iloc[int(i)]
            rows.append(
                {
                    "kind": kind,
                    "arc_id": str(row["arc_id"]),
                    "variant": int(row["variant"]),
                    "way_id": int(row["way_id"]),
                    "highway_class": str(row["highway_class"]),
                    "name": str(row["name"] or ""),
                    "length_m": round(float(row["length_m"]), 1),
                    "from_node": int(row["from_node"]),
                    "to_node": int(row["to_node"]),
                }
            )
    if node_lonlat is not None and clip is not None:
        rows = classify_trap_causes(rows, node_lonlat, clip, C.CLIP_EDGE_TOLERANCE_M)
    else:
        rows = [dict(r, trap_cause="genuine", trap_cause_rule="unclassified") for r in rows]
    rows.sort(key=lambda r: (r["trap_cause"], r["kind"], -r["length_m"]))

    def _tally(cause: str, kind: str) -> int:
        return sum(1 for r in rows if r["trap_cause"] == cause and r["kind"] == kind)

    return {
        "by_cause": {
            cause: {
                "no_legal_exit": _tally(cause, "no_legal_exit"),
                "no_legal_entry": _tally(cause, "no_legal_entry"),
                "km": round(
                    sum(r["length_m"] for r in rows if r["trap_cause"] == cause) / 1000.0, 3
                ),
            }
            for cause in ("clip_boundary", "genuine")
        },
        "by_rule": {
            rule: sum(1 for r in rows if r["trap_cause_rule"] == rule)
            for rule in sorted({r["trap_cause_rule"] for r in rows})
        },
        "no_legal_exit": int(len(no_out)),
        "no_legal_entry": int(len(no_in)),
        "no_legal_exit_km": float(index.iloc[no_out]["length_m"].sum() / 1000.0),
        "no_legal_entry_km": float(index.iloc[no_in]["length_m"].sum() / 1000.0),
        "rows": rows,
    }


def classify_trap_causes(
    rows: list[dict], node_lonlat: dict, clip, tolerance_m: float
) -> list[dict]:
    """Split traps into `clip_boundary` and `genuine`.

    The largest no-exit and no-entry arcs are trunk roads leaving the extract —
    the Bypass, the Senaki-Leselidze, the road to Marneuli — which appear as a
    matched pair of traps on the same way because the road simply continues past
    the 2 km buffer and no U-turn is permitted on trunk. Those are artefacts of
    where the extract stops. Listing them beside genuine broken junctions buries
    the handful that actually need fixing.

    Two rules, geometry first: the dangling node lies outside the clip polygon or
    within `tolerance_m` of its edge; failing that, the arc's reverse carries the
    mirrored trap at the same node. The rule that fired is recorded, so a
    mirrored pair deep inside the city stays visible as such rather than hiding
    behind the label.
    """
    from pyproj import Geod
    from shapely.geometry import Point

    geod = Geod(ellps="WGS84")
    boundary = clip.exterior if hasattr(clip, "exterior") else clip.boundary

    def dangling_node(row: dict) -> int:
        # a no-exit arc dangles at its head; a no-entry arc dangles at its tail
        return int(row["to_node"] if row["kind"] == "no_legal_exit" else row["from_node"])

    def edge_distance_m(node: int) -> float | None:
        point = node_lonlat.get(node)
        if point is None:
            return None
        geometry = Point(point)
        nearest = boundary.interpolate(boundary.project(geometry))
        return float(geod.inv(geometry.x, geometry.y, nearest.x, nearest.y)[2])

    mirrored: set[tuple[int, int, int]] = set()
    by_node: dict[int, set[str]] = {}
    for row in rows:
        by_node.setdefault(dangling_node(row), set()).add(row["kind"])
    for node, kinds in by_node.items():
        if {"no_legal_exit", "no_legal_entry"} <= kinds:
            mirrored.add(node)

    out: list[dict] = []
    for row in rows:
        node = dangling_node(row)
        distance = edge_distance_m(node)
        outside = not clip.contains(Point(node_lonlat[node])) if node in node_lonlat else False

        if distance is None:
            cause, rule = "genuine", "node_missing"
        elif outside or distance <= tolerance_m:
            cause, rule = "clip_boundary", "clip_edge_distance"
        elif node in mirrored:
            cause, rule = "clip_boundary", "mirrored_reverse"
        else:
            cause, rule = "genuine", ""
        out.append(
            dict(
                row,
                trap_cause=cause,
                trap_cause_rule=rule,
                dangling_node=node,
                clip_edge_distance_m=round(distance, 1) if distance is not None else None,
            )
        )
    return out


def _by_class(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    grouped = frame.groupby("highway_class")["length_m"].agg(["size", "sum"])
    return [
        {"highway_class": str(k), "arc_count": int(v["size"]), "arc_km": float(v["sum"] / 1000.0)}
        for k, v in grouped.sort_values("sum", ascending=False).iterrows()
    ]


def _lost_rows(frame: pd.DataFrame) -> list[dict]:
    return [
        {
            "arc_id": str(r["arc_id"]),
            "way_id": int(r["way_id"]),
            "highway_class": str(r["highway_class"]),
            "name": str(r["name"] or ""),
            "length_m": round(float(r["length_m"]), 1),
            "min_passes": int(r["min_passes"]),
            "from_node": int(r["from_node"]),
            "to_node": int(r["to_node"]),
        }
        for _, r in frame.sort_values("length_m", ascending=False).iterrows()
    ]
