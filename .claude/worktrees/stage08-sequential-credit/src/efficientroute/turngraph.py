"""L(G) — the turn-expanded graph (SPEC §3.3).

A node of L is a directed arc of the base network; an edge of L is one legal
manoeuvre.  The point of building it this way is invariant U1: a path through L
is drivable *by construction*, so no later stage has to validate turn legality.

Three construction rules carry the weight:

**U-turns are absent, not penalised.**  A `a -> reverse(a)` edge is created only
at a dead-end tip, or where the carriageway carries positive evidence of room to
turn.  SPEC §3.3 leaves the width **[CONFIRM]**; §1.1 settles the direction,
because inventing a manoeuvre that cannot be driven breaks U1 while withholding
one only costs deadhead.

**`only_*` restrictions forbid everything else.**  They are the expensive half of
the semantics and remove far more edges than the `no_*` relations do.

**Via-way restrictions are honoured by cloning the via arc.**  The constraint
spans two manoeuvres, which a first-order edge-based graph cannot express.
Removing either edge instead would over-restrict — legal, but it would silently
delete drivable manoeuvres and manufacture traps.  Cloning is exact: the clone is
reachable only from the restriction's `from` arc and loses the forbidden
continuation, while the original keeps it for every other approach.
"""

from __future__ import annotations

import collections
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import bearings as B
from . import config as C
from .restrictions import ParsedRestrictions, Restriction

TURN_CLASSES: tuple[str, ...] = ("straight", "right", "left", "u_turn")
_CLASS_CODE = {name: code for code, name in enumerate(TURN_CLASSES)}

NodeKey = tuple[str, int]  # (arc_id, variant); variant 0 is the physical arc


@dataclass
class TurnGraph:
    """L(G) as adjacency plus the per-node attributes routing will need."""

    node_ids: list[NodeKey]
    adjacency: list[dict[int, tuple[int, float]]]
    arc_index: pd.DataFrame
    via_node: list[int]  # per L-node: the OSM node this arc arrives at
    restriction_log: list[dict] = field(default_factory=list)
    u_turn_log: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- lookups

    def __post_init__(self) -> None:
        self._index_of: dict[NodeKey, int] = {key: i for i, key in enumerate(self.node_ids)}
        self._variants: dict[str, list[int]] = collections.defaultdict(list)
        for i, (arc_id, _) in enumerate(self.node_ids):
            self._variants[arc_id].append(i)

    @property
    def n_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def n_edges(self) -> int:
        return sum(len(row) for row in self.adjacency)

    @property
    def mean_out_degree(self) -> float:
        return self.n_edges / self.n_nodes if self.n_nodes else 0.0

    def index_of(self, key: NodeKey) -> int:
        return self._index_of[key]

    def variants_of(self, arc_id: str) -> list[int]:
        return self._variants.get(arc_id, [])

    def successors(self, key: NodeKey) -> set[NodeKey]:
        return {self.node_ids[dst] for dst in self.adjacency[self._index_of[key]]}

    def has_manoeuvre(self, from_arc: str, to_arc: str) -> bool:
        """Whether any variant of `from_arc` may continue onto any variant of `to_arc`."""
        targets = set(self.variants_of(to_arc))
        return any(
            targets & set(self.adjacency[src]) for src in self.variants_of(from_arc)
        )

    def _edge_attr(self, from_arc: str, to_arc: str) -> tuple[int, float]:
        for src in self.variants_of(from_arc):
            for dst in self.variants_of(to_arc):
                if dst in self.adjacency[src]:
                    return self.adjacency[src][dst]
        raise KeyError(f"no manoeuvre {from_arc} -> {to_arc}")

    def turn_class_of(self, from_arc: str, to_arc: str) -> str:
        return TURN_CLASSES[self._edge_attr(from_arc, to_arc)[0]]

    def penalty_of(self, from_arc: str, to_arc: str) -> float:
        return self._edge_attr(from_arc, to_arc)[1]

    def edge_tuples(self):
        """(src index, dst index, OSM node the manoeuvre happens at)."""
        for src, row in enumerate(self.adjacency):
            node = self.via_node[src]
            for dst in row:
                yield src, dst, node

    def u_turn_reasons(self) -> dict[str, int]:
        counter: collections.Counter[str] = collections.Counter()
        for row in self.u_turn_log:
            counter[row["reason"]] += 1
        return dict(counter)

    # ------------------------------------------------------------------ costs

    def traverse_capture_s(self, key: NodeKey) -> float:
        return float(self.arc_index.loc[self._index_of[key], "traverse_capture_s"])

    def traverse_deadhead_s(self, key: NodeKey) -> float:
        return float(self.arc_index.loc[self._index_of[key], "traverse_deadhead_s"])

    def edge_cost_capture(self, src: NodeKey, dst: NodeKey) -> float:
        penalty = self.adjacency[self._index_of[src]][self._index_of[dst]][1]
        return penalty + self.traverse_capture_s(dst)

    # ------------------------------------------------------------------ audit

    def out_degrees(self) -> np.ndarray:
        return np.fromiter((len(row) for row in self.adjacency), dtype="int32", count=self.n_nodes)

    def in_degrees(self) -> np.ndarray:
        counts = np.zeros(self.n_nodes, dtype="int32")
        for row in self.adjacency:
            for dst in row:
                counts[dst] += 1
        return counts

    def dead_end_nodes(self) -> list[NodeKey]:
        return [self.node_ids[i] for i in np.flatnonzero(self.out_degrees() == 0)]

    def unreachable_nodes(self) -> list[NodeKey]:
        return [self.node_ids[i] for i in np.flatnonzero(self.in_degrees() == 0)]

    # ---------------------------------------------------------------- storage

    def save(self, path: Path) -> Path:
        src: list[int] = []
        dst: list[int] = []
        codes: list[int] = []
        penalties: list[float] = []
        for a, row in enumerate(self.adjacency):
            for b, (code, penalty) in row.items():
                src.append(a)
                dst.append(b)
                codes.append(code)
                penalties.append(penalty)
        payload = {
            "format": 1,
            "node_ids": self.node_ids,
            "via_node": np.asarray(self.via_node, dtype="int64"),
            "src": np.asarray(src, dtype="int32"),
            "dst": np.asarray(dst, dtype="int32"),
            "turn_class": np.asarray(codes, dtype="uint8"),
            "turn_penalty_s": np.asarray(penalties, dtype="float32"),
            "turn_classes": TURN_CLASSES,
            "arc_index": self.arc_index,
            "restriction_log": self.restriction_log,
            "u_turn_log": self.u_turn_log,
            "meta": self.meta,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(payload, handle, protocol=5)
        return path


def load(path: Path) -> TurnGraph:
    with Path(path).open("rb") as handle:
        payload = pickle.load(handle)
    adjacency: list[dict[int, tuple[int, float]]] = [{} for _ in payload["node_ids"]]
    for a, b, code, penalty in zip(
        payload["src"], payload["dst"], payload["turn_class"], payload["turn_penalty_s"]
    ):
        adjacency[int(a)][int(b)] = (int(code), float(penalty))
    return TurnGraph(
        node_ids=[tuple(k) for k in payload["node_ids"]],
        adjacency=adjacency,
        arc_index=payload["arc_index"],
        via_node=list(payload["via_node"]),
        restriction_log=payload["restriction_log"],
        u_turn_log=payload["u_turn_log"],
        meta=payload["meta"],
    )


# --------------------------------------------------------------------- build


def provisional_speeds_kmh(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Provisional free-flow and capture speeds.

    **Placeholder.**  SPEC §11 puts the time model in Stage 2; SPEC §3.3 needs a
    traversal time for the edge cost now.  This is the smallest thing that
    satisfies both — posted `maxspeed` where tagged, a free-flow-by-class table
    otherwise, capped at `capture_speed_max` for capture traversals except on the
    reduced-quality motorway and trunk arcs of §3.2.  No congestion, no gradient,
    no idle allowance.  It is kept separate from the turn penalty so Stage 2 can
    replace it without rebuilding L.
    """
    by_class = frame["highway_class"].map(C.PROVISIONAL_FREE_FLOW_KMH)
    free_flow = by_class.fillna(C.PROVISIONAL_DEFAULT_KMH).to_numpy(dtype="float64")

    tagged = frame["maxspeed"].to_numpy(dtype="float64")
    free_flow = np.where(np.isnan(tagged), free_flow, tagged)

    reduced = (frame["capture_quality"] == "reduced").to_numpy()
    capture = np.where(reduced, free_flow, np.minimum(free_flow, C.CAPTURE_SPEED_MAX_KMH))
    return free_flow, capture


def build_turn_graph(
    arcs: pd.DataFrame,
    parsed: ParsedRestrictions | None = None,
    mainline_entry_classes: frozenset[str] | None = None,
    permissive_u_turns: bool = False,
    mainline_entry_fallback: bool | None = None,
) -> TurnGraph:
    """Construct L(G) over the Stage 0 routable arcs."""
    parsed = parsed or ParsedRestrictions()
    fallback = (
        C.MAINLINE_ENTRY_FALLBACK_WHERE_NO_RAMP
        if mainline_entry_fallback is None
        else mainline_entry_fallback
    )
    mainline = (
        C.MAINLINE_ENTRY_VIA_RAMPS_ONLY
        if mainline_entry_classes is None
        else mainline_entry_classes
    )

    routable = (
        arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
        .sort_values("arc_id", kind="mergesort")
        .reset_index(drop=True)
    )
    if routable.empty:
        raise ValueError("no routable arcs — did Stage 0 run?")

    node_ids: list[NodeKey] = [(arc_id, 0) for arc_id in routable["arc_id"]]
    index_of = {key: i for i, key in enumerate(node_ids)}
    n = len(node_ids)

    from_node = routable["from_node"].to_numpy()
    to_node = routable["to_node"].to_numpy()
    way_id = routable["way_id"].to_numpy()
    highway_class = routable["highway_class"].tolist()
    pair_id = routable["pair_id"].fillna("").tolist()
    direction = routable["direction"].tolist()
    lanes = routable["lanes"].to_numpy(dtype="float64")
    width = routable["width"].to_numpy(dtype="float64")

    bearing_in = B.terminal_bearings(routable.geometry.tolist(), "end")
    bearing_out = B.terminal_bearings(routable.geometry.tolist(), "start")

    reverse_of = _reverse_map(pair_id, direction, index_of, routable["arc_id"].tolist())
    in_arcs, out_arcs = _incidence(from_node, to_node)
    tips = _dead_end_tips(from_node, to_node, way_id, routable["seg_index"].to_numpy())

    adjacency: list[dict[int, tuple[int, float]]] = [{} for _ in range(n)]
    u_turn_log: list[dict] = []

    for node, ins in in_arcs.items():
        outs = out_arcs.get(node)
        if not outs:
            continue
        is_tip = node in tips
        # SPEC §3.3 makes a mainline enterable only from a ramp. Where OSM models
        # no ramp at this junction, there is no ramp to insist on: the plain
        # junction is what the data says the access is, and refusing it invents a
        # restriction rather than modelling one. The rule still binds everywhere a
        # ramp exists, which is everywhere it was meant to.
        ramp_available = fallback and not any(
            highway_class[x] in mainline or highway_class[x].endswith("_link") for x in ins
        )
        for a in ins:
            for b in outs:
                if reverse_of.get(a) == b:
                    allowed, reason = _u_turn_allowed(
                        a, highway_class, lanes, width, is_tip, permissive_u_turns
                    )
                    if not allowed:
                        continue
                    code, penalty = _CLASS_CODE["u_turn"], C.TURN_PENALTY_S["u_turn"]
                    u_turn_log.append(
                        {"arc_id": node_ids[a][0], "osm_node": int(node), "reason": reason}
                    )
                else:
                    if _mainline_entry_blocked(
                        highway_class[a], highway_class[b], mainline,
                        no_ramp_at_node=ramp_available,
                    ):
                        continue
                    delta = B.turn_delta_deg(bearing_in[a], bearing_out[b])
                    turn_class = B.classify_turn(delta)
                    code, penalty = _CLASS_CODE[turn_class], C.TURN_PENALTY_S[turn_class]
                adjacency[a][b] = (code, penalty)

    arc_index = _arc_index(routable)
    graph = TurnGraph(
        node_ids=node_ids,
        adjacency=adjacency,
        arc_index=arc_index,
        via_node=[int(v) for v in to_node],
        u_turn_log=u_turn_log,
        meta={
            "mainline_entry_via_ramps_only": sorted(mainline),
            "mainline_entry_fallback_where_no_ramp": bool(fallback),
            "permissive_u_turns": permissive_u_turns,
            "u_turn_min_width_m": C.U_TURN_MIN_WIDTH_M,
            "u_turn_min_total_lanes": C.U_TURN_MIN_TOTAL_LANES,
            "turn_penalty_s": dict(C.TURN_PENALTY_S),
            "edges_before_restrictions": sum(len(r) for r in adjacency),
        },
    )
    _apply_restrictions(graph, parsed, routable)
    graph.__post_init__()
    graph.meta["edges_after_restrictions"] = graph.n_edges
    return graph


# ------------------------------------------------------------------ internals


def _reverse_map(pair_id, direction, index_of, arc_ids) -> dict[int, int]:
    """Map each arc index to its opposite direction, where one exists."""
    by_pair: dict[str, dict[str, int]] = collections.defaultdict(dict)
    for i, (pid, d) in enumerate(zip(pair_id, direction)):
        if pid:
            by_pair[pid][d] = i
    out: dict[int, int] = {}
    for members in by_pair.values():
        if "F" in members and "B" in members:
            out[members["F"]] = members["B"]
            out[members["B"]] = members["F"]
    return out


def _incidence(from_node, to_node):
    in_arcs: dict[int, list[int]] = collections.defaultdict(list)
    out_arcs: dict[int, list[int]] = collections.defaultdict(list)
    for i, node in enumerate(to_node):
        in_arcs[int(node)].append(i)
    for i, node in enumerate(from_node):
        out_arcs[int(node)].append(i)
    return in_arcs, out_arcs


def _dead_end_tips(from_node, to_node, way_id, seg_index) -> set[int]:
    """Nodes touched by exactly one physical segment — the tip of a dead end."""
    segments: dict[int, set[tuple[int, int]]] = collections.defaultdict(set)
    for i in range(len(way_id)):
        key = (int(way_id[i]), int(seg_index[i]))
        segments[int(from_node[i])].add(key)
        segments[int(to_node[i])].add(key)
    return {node for node, segs in segments.items() if len(segs) == 1}


def _u_turn_allowed(a, highway_class, lanes, width, is_tip, permissive=False) -> tuple[bool, str]:
    if highway_class[a] in C.NO_U_TURN_CLASSES:
        return False, ""
    if is_tip:
        return True, "dead_end_tip"
    if permissive:
        # counterfactual build used only by the audit, to attribute unreachable
        # arcs to the U-turn policy rather than to a restriction or the clip edge
        return True, "permissive"
    if not np.isnan(width[a]) and width[a] >= C.U_TURN_MIN_WIDTH_M:
        return True, "width_permitted"
    if not np.isnan(lanes[a]) and lanes[a] >= C.U_TURN_MIN_TOTAL_LANES:
        return True, "width_permitted"
    return False, ""


def _mainline_entry_blocked(
    from_class: str, to_class: str, mainline: frozenset[str],
    no_ramp_at_node: bool = False,
) -> bool:
    """SPEC §3.3: a mainline is enterable only from a ramp or from itself.

    `no_ramp_at_node` is the Stage 4b narrowing: at a junction where OSM models no
    ramp into the mainline at all, the rule has nothing to enforce and blocking
    the plain junction strands the mainline behind a restriction that does not
    exist on the ground.
    """
    if to_class not in mainline:
        return False
    if no_ramp_at_node:
        return False
    return not (from_class in mainline or from_class.endswith("_link"))


def _arc_index(routable: pd.DataFrame) -> pd.DataFrame:
    free_flow, capture = provisional_speeds_kmh(routable)
    length = routable["length_m"].to_numpy(dtype="float64")
    frame = routable[
        [
            "arc_id", "way_id", "seg_index", "direction", "from_node", "to_node",
            "highway_class", "name", "length_m", "min_passes", "pair_id",
            "pair_requirement", "is_pair_representative", "capture_quality",
            "lanes", "width", "gradient_pct",
        ]
    ].copy()
    frame["variant"] = 0
    frame["free_flow_kmh"] = free_flow
    frame["capture_kmh"] = capture
    frame["traverse_deadhead_s"] = length / (free_flow / 3.6)
    frame["traverse_capture_s"] = length / (capture / 3.6)
    return frame.reset_index(drop=True)


def _clone_row(graph: TurnGraph, source_index: int, variant: int) -> int:
    """Append a restriction clone of an existing L-node; return its index."""
    arc_id = graph.node_ids[source_index][0]
    new_index = len(graph.node_ids)
    graph.node_ids.append((arc_id, variant))
    graph.adjacency.append({})
    graph.via_node.append(graph.via_node[source_index])
    row = graph.arc_index.iloc[source_index].copy()
    row["variant"] = variant
    graph.arc_index = pd.concat(
        [graph.arc_index, row.to_frame().T], ignore_index=True
    )
    return new_index


def _apply_restrictions(
    graph: TurnGraph, parsed: ParsedRestrictions, routable: pd.DataFrame
) -> None:
    """Remove every manoeuvre a parsed restriction forbids."""
    ends_at: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    starts_at: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    by_way: dict[int, list[int]] = collections.defaultdict(list)
    for i, (w, tail, head) in enumerate(
        zip(routable["way_id"], routable["from_node"], routable["to_node"])
    ):
        ends_at[(int(w), int(head))].append(i)
        starts_at[(int(w), int(tail))].append(i)
        by_way[int(w)].append(i)

    heads = routable["to_node"].to_numpy(dtype="int64")

    graph.__post_init__()
    for restriction in parsed.applicable:
        if restriction.is_via_way:
            row = _apply_via_way(graph, restriction, by_way, starts_at, heads)
        else:
            row = _apply_via_node(graph, restriction, ends_at, starts_at)
        graph.restriction_log.append(row)


def _log_row(restriction: Restriction, **extra) -> dict:
    row = {
        "relation_id": restriction.relation_id,
        "kind": restriction.kind,
        "manoeuvre": restriction.manoeuvre,
        "via": "way" if restriction.is_via_way else "node",
        "status": "applied",
        "edges_removed": 0,
        "edges_already_absent": 0,
        "clones_created": 0,
        "osm_node": int(restriction.via_nodes[0]) if restriction.via_nodes else -1,
        "detail": "",
    }
    row.update(extra)
    return row


def _apply_via_node(graph: TurnGraph, r: Restriction, ends_at, starts_at) -> dict:
    node = r.via_nodes[0]
    from_arcs = ends_at.get((r.from_way, node), [])
    to_arcs = {i for w in r.to_ways for i in starts_at.get((w, node), [])}
    if not from_arcs:
        # the way never *ends* at the via node: either it is one-way pointing away
        # from the junction, or the relation names a node the way does not touch
        return _log_row(r, status="unresolvable", detail="from_way_does_not_end_at_via_node")
    if not to_arcs:
        return _log_row(r, status="unresolvable", detail="to_way_does_not_start_at_via_node")

    removed = absent = 0
    for a in from_arcs:
        for src in graph.variants_of(graph.node_ids[a][0]):
            if r.kind == "no":
                for b in to_arcs:
                    for dst in graph.variants_of(graph.node_ids[b][0]):
                        if dst in graph.adjacency[src]:
                            del graph.adjacency[src][dst]
                            removed += 1
                        else:
                            absent += 1
            else:  # only_*: everything except the named continuation is forbidden
                permitted = {
                    dst
                    for b in to_arcs
                    for dst in graph.variants_of(graph.node_ids[b][0])
                }
                for dst in list(graph.adjacency[src]):
                    if dst not in permitted:
                        del graph.adjacency[src][dst]
                        removed += 1
    return _log_row(r, edges_removed=removed, edges_already_absent=absent)


def _via_chain(by_way, starts_at, heads, r: Restriction) -> tuple[int, list[int], int] | None:
    """Resolve the (from arc, via-arc chain, to arc) triple a via-way restriction names.

    The via way may have been split into several segments by Stage 0's junction
    splitting, so the "via" is in general a chain of arcs, not one arc.
    """
    via_way = r.via_ways[0]
    if via_way not in by_way:
        return None

    for a in by_way.get(r.from_way, []):
        chain = _walk_via(starts_at, heads, via_way, int(heads[a]), r, len(by_way[via_way]))
        if not chain:
            continue
        last_head = int(heads[chain[-1]])
        for w in r.to_ways:
            for b in starts_at.get((w, last_head), []):
                return a, chain, b
    return None


def _walk_via(starts_at, heads, via_way, node, r: Restriction, limit: int) -> list[int] | None:
    """Follow the via way from `node` until a `to` way becomes reachable."""
    chain: list[int] = []
    current = node
    seen: set[int] = set()
    for _ in range(limit + 1):
        candidates = [i for i in starts_at.get((via_way, current), []) if i not in seen]
        if not candidates:
            return None
        step = candidates[0]
        seen.add(step)
        chain.append(step)
        current = int(heads[step])
        if any(starts_at.get((w, current)) for w in r.to_ways):
            return chain
    return None


def _apply_via_way(graph: TurnGraph, r: Restriction, by_way, starts_at, heads) -> dict:
    resolved = _via_chain(by_way, starts_at, heads, r)
    if resolved is None:
        return _log_row(r, status="unresolvable", detail="via-way chain does not connect")
    a, chain, b = resolved

    if graph.node_ids[a][1] != 0 or any(graph.node_ids[v][1] != 0 for v in chain):
        return _log_row(r, status="unresolvable", detail="overlapping via-way restrictions")
    if chain[0] not in graph.adjacency[a]:
        return _log_row(r, status="applied", edges_already_absent=1,
                        detail="entry manoeuvre already absent")

    entry_node = int(graph.via_node[a])
    variant = 1 + max((v for _, v in graph.node_ids), default=0)
    clones = [_clone_row(graph, v, variant) for v in chain]
    graph.__post_init__()

    entry_attr = graph.adjacency[a].pop(chain[0])
    graph.adjacency[a][clones[0]] = entry_attr

    for position, original in enumerate(chain):
        for dst, attr in graph.adjacency[original].items():
            if position + 1 < len(chain) and dst == chain[position + 1]:
                graph.adjacency[clones[position]][clones[position + 1]] = attr
            else:
                graph.adjacency[clones[position]][dst] = attr

    last = clones[-1]
    targets = {
        dst for w in r.to_ways
        for i in starts_at.get((w, graph.via_node[chain[-1]]), [])
        for dst in graph.variants_of(graph.node_ids[i][0])
    }
    removed = 0
    if r.kind == "no":
        for dst in list(graph.adjacency[last]):
            if dst in targets:
                del graph.adjacency[last][dst]
                removed += 1
    else:
        for dst in list(graph.adjacency[last]):
            if dst not in targets:
                del graph.adjacency[last][dst]
                removed += 1
    return _log_row(r, edges_removed=removed + 1, clones_created=len(clones), osm_node=entry_node)
