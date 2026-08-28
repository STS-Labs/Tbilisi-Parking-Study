"""Junction summaries for the Stage 1 manual spot-check.

The gate asks for 20 junctions verified against imagery, because automated tests
can only prove that L honours the restrictions OSM *records* — they cannot catch
a restriction that OSM does not have at all.  This module produces the machine
half of that table: which manoeuvres L permits at a junction, and which it bans.
The human half — what the imagery actually shows — is filled in by hand.
"""

from __future__ import annotations

import collections

from .turngraph import TURN_CLASSES, TurnGraph


def describe_junction(graph: TurnGraph, osm_node: int) -> dict:
    """Every manoeuvre L allows and bans at one OSM node."""
    index = graph.arc_index
    arc_ids = index["arc_id"].tolist()
    names = index["name"].fillna("").tolist()
    classes = index["highway_class"].tolist()
    heads = index["to_node"].astype(int).tolist()
    tails = index["from_node"].astype(int).tolist()

    incoming = [i for i, h in enumerate(heads) if h == osm_node]
    outgoing = [i for i, t in enumerate(tails) if t == osm_node]
    if not incoming or not outgoing:
        return {
            "osm_node": osm_node, "approaches": 0, "exits": 0,
            "candidates": 0, "legal": 0, "banned": [], "by_class": {},
        }

    banned: list[dict] = []
    legal = 0
    by_class: collections.Counter[str] = collections.Counter()
    for a in incoming:
        for b in outgoing:
            if b in graph.adjacency[a]:
                legal += 1
                by_class[TURN_CLASSES[graph.adjacency[a][b][0]]] += 1
            else:
                banned.append(
                    {
                        "from": arc_ids[a],
                        "to": arc_ids[b],
                        "from_name": names[a] or classes[a],
                        "to_name": names[b] or classes[b],
                    }
                )
    return {
        "osm_node": osm_node,
        "approaches": len(incoming),
        "exits": len(outgoing),
        "candidates": len(incoming) * len(outgoing),
        "legal": legal,
        "banned": banned,
        "by_class": dict(by_class),
        "approach_names": sorted({names[i] or classes[i] for i in incoming}),
    }


def summarise(summary: dict, limit: int = 3) -> str:
    """One table-cell line describing what L permits at a junction."""
    if not summary["approaches"]:
        return "no approaches in L"
    classes = ", ".join(f"{k} {v}" for k, v in sorted(summary["by_class"].items()))
    text = (
        f"{summary['approaches']}→{summary['exits']}: "
        f"{summary['legal']}/{summary['candidates']} legal ({classes})"
    )
    if summary["banned"]:
        shown = "; ".join(
            f"{b['from_name']}→{b['to_name']}" for b in summary["banned"][:limit]
        )
        more = len(summary["banned"]) - limit
        text += f". Banned: {shown}" + (f" +{more} more" if more > 0 else "")
    return text


def select_junctions(graph: TurnGraph, node_lonlat: dict, count: int = 20) -> list[dict]:
    """Pick the junctions most worth a human look, deterministically.

    Ranked by how much the restriction data does at the node — via-way relations
    first, because they are the ones a naive implementation gets wrong, then by
    the number of applied restrictions, then by node id so the choice is stable.
    """
    weight: dict[int, float] = collections.defaultdict(float)
    for row in graph.restriction_log:
        if row["status"] != "applied" or row["osm_node"] <= 0:
            continue
        weight[row["osm_node"]] += 10.0 if row["via"] == "way" else 1.0

    ranked = sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[dict] = []
    for node, score in ranked:
        if len(out) >= count:
            break
        lon, lat = node_lonlat.get(node, (None, None))
        if lon is None:
            continue
        summary = describe_junction(graph, node)
        out.append(
            {
                "osm_node": node,
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "restriction_weight": score,
                "graph_says": summarise(summary),
                "detail": summary,
            }
        )
    return out
