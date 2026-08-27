"""Stage 4b — re-test the scope decision, and dispose of the trapped mainlines.

Two of the three items here exist because an *estimate* was used where a
measurement was available:

- Variant D was ruled out on 25 August using a flat 1.2 h/day depot-leg
  allowance.  Stage 4 routed the legs and measured 32 minutes.  The arithmetic
  that ruled D out was therefore wrong, and this stage measures D properly
  rather than scaling C's answer — scaling is what caused the error.
- Stage 4 reserved no room for capture on the commute because the calendar was
  the binding constraint.  Stage 4 then measured 42 days of slack, so it is not.

The third item disposes of the motorway and trunk arcs that no closed tour can
reach, which SPEC §1.1 requires before Stage 5 can consume the plan.
"""

from __future__ import annotations

import collections

import numpy as np

from . import config as C
from . import turnaudit, turngraph, zoning

def required_arrays(frame, graph):
    """Per L-node: required traversals and length, for the chosen scope."""
    index = graph.arc_index
    rows = frame.set_index("arc_id").loc[index["arc_id"].to_numpy()]
    return (
        zoning.required_traversals(index),
        rows["length_m"].to_numpy(dtype="float64"),
        index["highway_class"].to_numpy(),
    )


def is_fast(classes: np.ndarray) -> np.ndarray:
    """Motorway, trunk and their ramps — the network SPEC §3.2 captures degraded."""
    return np.array([str(c).startswith(("motorway", "trunk")) for c in classes])


def trap_disposition(frame, graph, keep, parsed, boundary) -> dict:
    """Attribute every trapped required arc to a cause, split by class.

    Reuses Stage 1's counterfactual attribution rather than reimplementing it:
    an arc that comes back when a rule is dropped was stranded by that rule.
    """
    traversals, length_m, classes = required_arrays(frame, graph)
    fast = is_fast(classes)
    arc_ids = graph.arc_index["arc_id"].to_numpy()

    lost = np.flatnonzero(~np.asarray(keep, dtype=bool) & (traversals > 0))
    causes = turnaudit.attribute_losses(
        frame, parsed, [str(arc_ids[i]) for i in lost], boundary=boundary
    )

    buckets: dict[str, dict] = collections.defaultdict(
        lambda: {"arcs": 0, "km": 0.0, "fast_arcs": 0, "fast_km": 0.0}
    )
    for i in lost:
        km = float(length_m[i] * traversals[i] / 1000.0)
        bucket = buckets[causes.get(str(arc_ids[i]), "unknown")]
        bucket["arcs"] += 1
        bucket["km"] += km
        if fast[i]:
            bucket["fast_arcs"] += 1
            bucket["fast_km"] += km

    fast_required = float((length_m * traversals)[fast].sum() / 1000.0)
    fast_trapped = float((length_m * traversals)[lost][fast[lost]].sum() / 1000.0)
    return {
        "trapped_arcs": int(len(lost)),
        "trapped_km": float((length_m * traversals)[lost].sum() / 1000.0),
        "fast_trapped_arcs": int(fast[lost].sum()),
        "fast_trapped_km": fast_trapped,
        "fast_required_km": fast_required,
        "fast_trapped_share": fast_trapped / fast_required if fast_required else 0.0,
        "by_cause": {
            name: dict(values)
            for name, values in sorted(buckets.items(), key=lambda kv: -kv[1]["km"])
        },
    }


def mainline_fix_effect(frame, parsed, boundary=None) -> dict:
    """What narrowing the mainline-entry rule recovers, and what it costs.

    SPEC §3.3 makes a mainline enterable only from a ramp.  Where OSM models no
    ramp at a junction, there is no ramp to insist on and the rule strands the
    mainline behind a restriction that is not there on the ground.  The narrowing
    keeps the rule wherever a ramp exists.
    """
    from . import lstar

    out = {}
    graphs = {}
    for label, fallback in (("as_built", False), ("narrowed", True)):
        graph = turngraph.build_turn_graph(frame, parsed, mainline_entry_fallback=fallback)
        keep = lstar.largest_strong_component(graph)
        traversals, length_m, classes = required_arrays(frame, graph)
        fast = is_fast(classes)
        lost = ~keep & (traversals > 0)
        graphs[label] = graph
        out[label] = {
            "edges": int(graph.n_edges),
            "tourable_nodes": int(keep.sum()),
            "trapped_km": float((length_m * traversals)[lost].sum() / 1000.0),
            "fast_trapped_km": float((length_m * traversals)[lost & fast].sum() / 1000.0),
        }

    base, narrowed = graphs["as_built"], graphs["narrowed"]
    index = narrowed.arc_index
    added = []
    for a, row in enumerate(narrowed.adjacency):
        for b in row:
            if b not in base.adjacency[a]:
                added.append(
                    {
                        "from_arc": str(index["arc_id"][a]),
                        "from_class": str(index["highway_class"][a]),
                        "to_arc": str(index["arc_id"][b]),
                        "to_class": str(index["highway_class"][b]),
                        "osm_node": int(narrowed.via_node[a]),
                    }
                )

    out["added_manoeuvres"] = sorted(added, key=lambda r: (r["from_arc"], r["to_arc"]))
    out["edges_added"] = len(added)
    out["km_recovered"] = out["as_built"]["trapped_km"] - out["narrowed"]["trapped_km"]
    out["fast_km_recovered"] = (
        out["as_built"]["fast_trapped_km"] - out["narrowed"]["fast_trapped_km"]
    )
    out["u1"] = u1_check(narrowed, parsed, out["added_manoeuvres"])
    return out


def u1_check(graph, parsed, added: list[dict]) -> dict:
    """Invariant U1 over the manoeuvres the rule change actually added.

    The Stage 1 gate proves U1 for `L(G)` by sampling random walks.  Narrowing a
    rule only *adds* edges, and everything else is the graph the gate already
    cleared — so the honest check here is not another sample but an exhaustive
    one over the additions.  Three manoeuvres can be checked completely; two
    thousand random walks can only fail to find a problem.
    """
    forbidden = _forbidden_pairs(parsed, graph)
    violations = [
        row for row in added if (row["from_arc"], row["to_arc"]) in forbidden
    ]
    return {
        "checked": len(added),
        "method": "exhaustive over the added manoeuvres",
        "forbidden_pairs_in_source": len(forbidden),
        "violations": len(violations),
        "violating": violations,
        "holds": not violations,
    }


def _forbidden_pairs(parsed, graph) -> set[tuple[str, str]]:
    """Arc pairs the parsed OSM relations forbid, read from the relations.

    Node-via restrictions only: a via-way restriction forbids a *triple*, and a
    single added manoeuvre cannot complete one on its own without the rest of the
    chain, which is unchanged.
    """
    ends_at: dict[tuple[int, int], list[str]] = collections.defaultdict(list)
    starts_at: dict[tuple[int, int], list[str]] = collections.defaultdict(list)
    starts_at_node: dict[int, list[str]] = collections.defaultdict(list)
    index = graph.arc_index
    for arc_id, way, tail, head in zip(
        index["arc_id"], index["way_id"].astype(int),
        index["from_node"].astype(int), index["to_node"].astype(int),
    ):
        ends_at[(way, head)].append(str(arc_id))
        starts_at[(way, tail)].append(str(arc_id))
        starts_at_node[tail].append(str(arc_id))

    applied = {
        row["relation_id"] for row in graph.restriction_log if row["status"] == "applied"
    }
    pairs: set[tuple[str, str]] = set()
    for restriction in parsed.applicable:
        if restriction.relation_id not in applied or restriction.is_via_way:
            continue
        node = restriction.via_nodes[0]
        from_arcs = ends_at.get((restriction.from_way, node), [])
        to_arcs = {
            arc for way in restriction.to_ways for arc in starts_at.get((way, node), [])
        }
        if not from_arcs or not to_arcs:
            continue
        for a in from_arcs:
            if restriction.kind == "no":
                pairs.update((a, b) for b in to_arcs)
            else:
                # `only_*`: every exit from this junction other than the named
                # ones is forbidden.
                pairs.update(
                    (a, b) for b in starts_at_node.get(node, []) if b not in to_arcs
                )
    return pairs
