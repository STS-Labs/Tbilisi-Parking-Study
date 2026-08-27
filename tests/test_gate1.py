"""Stage 1 gate. Every assertion is copied from prompts/01-turn-expanded-graph.md.

These checks rebuild what they verify from the *source data* rather than asking
the builder what it did — a test that trusts `turngraph` to report its own
restrictions would pass even if the builder never applied one.
"""
import json
import random

import pytest

from efficientroute import config as C

pytestmark = pytest.mark.gate1

WALK_COUNT = 1000
WALK_LENGTH = 20
SEED = 20260825  # CLAUDE.md rule 5: seed everything


@pytest.fixture(scope="module")
def graph():
    if not C.TURN_GRAPH_PATH.exists():
        pytest.skip(f"{C.TURN_GRAPH_PATH} not built — run `make stage1`")
    from efficientroute import turngraph

    return turngraph.load(C.TURN_GRAPH_PATH)


@pytest.fixture(scope="module")
def audit():
    if not C.TURN_STATS_JSON.exists():
        pytest.skip("Stage 1 stats missing — run `make stage1`")
    return json.loads(C.TURN_STATS_JSON.read_text())


@pytest.fixture(scope="module")
def parsed():
    if not C.PBF_PATH.exists() or not C.NETWORK_GPKG.exists():
        pytest.skip("source data missing")
    import geopandas as gpd

    from efficientroute import restrictions as R

    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    return R.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))


@pytest.fixture(scope="module")
def arc_rows(graph):
    """Per L-node: (arc_id, from_node, to_node) straight off the stored index."""
    index = graph.arc_index
    return list(
        zip(index["arc_id"], index["from_node"].astype(int), index["to_node"].astype(int))
    )


# ------------------------------------------------------------------ invariant U1


def test_u1_random_paths_are_legally_drivable(graph, arc_rows, parsed):
    """Invariant U1 over 1,000 seeded random walks through L."""
    forbidden_pairs, forbidden_triples = _forbidden_from_source(parsed, graph)
    rng = random.Random(SEED)
    live = [i for i in range(graph.n_nodes) if graph.adjacency[i]]
    assert live, "L has no edges at all"

    checked_steps = 0
    for _ in range(WALK_COUNT):
        node = rng.choice(live)
        path = [node]
        for _ in range(WALK_LENGTH):
            successors = list(graph.adjacency[node])
            if not successors:
                break
            node = rng.choice(successors)
            path.append(node)

        for a, b in zip(path, path[1:]):
            arc_a, _, head_a = arc_rows[a]
            arc_b, tail_b, _ = arc_rows[b]
            assert head_a == tail_b, (
                f"manoeuvre {arc_a} -> {arc_b} does not share a node "
                f"({head_a} != {tail_b})"
            )
            assert (arc_a, arc_b) not in forbidden_pairs, (
                f"walk used {arc_a} -> {arc_b}, which a parsed restriction forbids"
            )
            checked_steps += 1

        for a, b, c in zip(path, path[1:], path[2:]):
            triple = (arc_rows[a][0], arc_rows[b][0], arc_rows[c][0])
            assert triple not in forbidden_triples, (
                f"walk used the via-way sequence {triple}, which is forbidden"
            )

    assert checked_steps > 5000, f"only {checked_steps} manoeuvres exercised"


# -------------------------------------------------- adversarial restriction test


def test_no_edge_survives_that_a_parsed_restriction_forbids(graph, parsed):
    """For every applied restriction, assert the forbidden manoeuvre is absent."""
    applied = {r["relation_id"] for r in graph.restriction_log if r["status"] == "applied"}
    ends_at, starts_at = _arc_lookup(graph)

    violations: list[str] = []
    checked = 0
    for restriction in parsed.applicable:
        if restriction.relation_id not in applied or restriction.is_via_way:
            continue
        node = restriction.via_nodes[0]
        from_arcs = ends_at.get((restriction.from_way, node), [])
        to_arcs = {i for w in restriction.to_ways for i in starts_at.get((w, node), [])}
        if not from_arcs or not to_arcs:
            continue
        checked += 1
        for a in from_arcs:
            if restriction.kind == "no":
                for b in to_arcs:
                    if graph.has_manoeuvre(a, b):
                        violations.append(f"r{restriction.relation_id}: {a} -> {b} still present")
            else:
                for b in _successor_arc_ids(graph, a):
                    if b not in to_arcs:
                        violations.append(
                            f"r{restriction.relation_id} (only_*): {a} -> {b} still present"
                        )
    assert checked > 1000, f"only {checked} restrictions exercised"
    assert violations == [], violations[:20]


def test_via_way_restrictions_have_no_surviving_path(graph, parsed):
    """A via-way restriction forbids a two-manoeuvre sequence, not a single edge.

    The check has to follow L-node *variants*, not arc ids: cloning leaves the
    original via arc holding the forbidden continuation on purpose, for every
    other approach. Collapsing variants here would report the restriction as
    violated when it is in fact honoured.
    """
    ends_at, _ = _arc_lookup(graph)
    violations: list[str] = []
    checked = 0
    for restriction in parsed.applicable:
        if not restriction.is_via_way:
            continue
        checked += 1
        via_way = restriction.via_ways[0]
        from_arcs = [
            arc for (way, _node), arcs in ends_at.items()
            if way == restriction.from_way for arc in arcs
        ]
        for arc in from_arcs:
            for src in graph.variants_of(arc):
                for mid in graph.adjacency[src]:
                    mid_arc = graph.node_ids[mid][0]
                    if _way_of(graph, mid_arc) != via_way:
                        continue
                    for onward in graph.adjacency[mid]:
                        onward_arc = graph.node_ids[onward][0]
                        if _way_of(graph, onward_arc) in restriction.to_ways:
                            violations.append(
                                f"r{restriction.relation_id}: {arc} -> {mid_arc} -> {onward_arc}"
                            )
    assert checked == parsed.via_way_count
    assert violations == [], violations[:10]


# -------------------------------------------------------------- u-turn policy


def test_no_u_turn_edge_exists_where_the_spec_forbids_one(graph):
    """Every U-turn edge sits at a dead-end tip or on a carriageway with room."""
    index = graph.arc_index
    by_node = list(zip(index["arc_id"], index["from_node"].astype(int), index["to_node"].astype(int)))
    reverse = _reverse_pairs(index)
    tips = _dead_end_tips(index)
    lanes = dict(zip(index["arc_id"], index["lanes"]))
    width = dict(zip(index["arc_id"], index["width"]))
    klass = dict(zip(index["arc_id"], index["highway_class"]))

    offenders: list[str] = []
    u_turn_edges = 0
    for src, row in enumerate(graph.adjacency):
        arc_a, _, head = by_node[src]
        for dst in row:
            arc_b = by_node[dst][0]
            if reverse.get(arc_a) != arc_b:
                continue
            u_turn_edges += 1
            if klass[arc_a] in C.NO_U_TURN_CLASSES:
                offenders.append(f"{arc_a}: u-turn on {klass[arc_a]}")
                continue
            if head in tips:
                continue
            wide_enough = (
                (width[arc_a] == width[arc_a] and width[arc_a] >= C.U_TURN_MIN_WIDTH_M)
                or (lanes[arc_a] == lanes[arc_a] and lanes[arc_a] >= C.U_TURN_MIN_TOTAL_LANES)
            )
            if not wide_enough:
                offenders.append(f"{arc_a} at node {head}: no tip, no width evidence")
    assert u_turn_edges > 0, "no u-turn edges at all — the policy cannot be this strict"
    assert offenders == [], offenders[:20]


# ------------------------------------------------------------------------ scc


def test_largest_scc_of_l_covers_99_percent_of_required_km(audit):
    share = audit["scc"]["share_of_required_km"]
    lost = audit["scc"]["required_km_lost"]
    assert share >= 0.99, (
        f"largest SCC of L reaches only {share:.3%} of required traversal km "
        f"({lost:.1f} km unreachable). Per the stage brief, stop and report the "
        "exceptions individually — see reports/01-turn-audit.md §6."
    )


def test_every_unreachable_arc_is_reported_with_a_cause(audit):
    lost = audit["lost_detail"]
    assert len(lost) == audit["scc"]["lost_arc_count"]
    assert all(row["cause"] for row in lost)


def test_traps_are_listed_individually(audit):
    traps = audit["traps"]
    assert len(traps["rows"]) == traps["no_legal_exit"] + traps["no_legal_entry"]


# ------------------------------------------------------------------ spot-check


def test_twenty_junctions_were_checked_against_imagery(audit):
    rows = audit.get("spotchecks") or []
    assert len(rows) >= 20, (
        f"only {len(rows)} junctions spot-checked; the gate requires 20 verified "
        "against satellite or street imagery"
    )
    for row in rows:
        assert row["verdict"] in {"confirmed", "missing_in_osm", "mismatch", "inconclusive"}
        assert row["imagery"] and row["graph_says"]


# --------------------------------------------------------------------- helpers


def _arc_lookup(graph):
    ends_at: dict[tuple[int, int], list[str]] = {}
    starts_at: dict[tuple[int, int], list[str]] = {}
    index = graph.arc_index
    for arc_id, way, tail, head, variant in zip(
        index["arc_id"], index["way_id"].astype(int),
        index["from_node"].astype(int), index["to_node"].astype(int), index["variant"]
    ):
        if variant:
            continue
        ends_at.setdefault((way, head), []).append(arc_id)
        starts_at.setdefault((way, tail), []).append(arc_id)
    return ends_at, starts_at


def _successor_arc_ids(graph, arc_id: str) -> set[str]:
    out: set[str] = set()
    for src in graph.variants_of(arc_id):
        for dst in graph.adjacency[src]:
            out.add(graph.node_ids[dst][0])
    return out


def _way_of(graph, arc_id: str) -> int:
    return int(arc_id.split(":")[0])


def _forbidden_from_source(parsed, graph):
    """Rebuild the forbidden manoeuvre set straight from the OSM relations."""
    ends_at, starts_at = _arc_lookup(graph)
    pairs: set[tuple[str, str]] = set()
    triples: set[tuple[str, str, str]] = set()
    applied = {r["relation_id"] for r in graph.restriction_log if r["status"] == "applied"}

    for r in parsed.applicable:
        if r.relation_id not in applied:
            continue
        if r.is_via_way:
            continue  # handled as triples below, needs the resolved chain
        node = r.via_nodes[0]
        from_arcs = ends_at.get((r.from_way, node), [])
        to_arcs = {i for w in r.to_ways for i in starts_at.get((w, node), [])}
        if not from_arcs or not to_arcs:
            continue
        for a in from_arcs:
            if r.kind == "no":
                pairs.update((a, b) for b in to_arcs)
            else:
                for b in _successor_arc_ids(graph, a):
                    if b not in to_arcs:
                        pairs.add((a, b))
    return pairs, triples


def _reverse_pairs(index) -> dict[str, str]:
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


def _dead_end_tips(index) -> set[int]:
    segments: dict[int, set[tuple[int, int]]] = {}
    for way, seg, tail, head, variant in zip(
        index["way_id"].astype(int), index["seg_index"].astype(int),
        index["from_node"].astype(int), index["to_node"].astype(int), index["variant"]
    ):
        if variant:
            continue
        segments.setdefault(tail, set()).add((way, seg))
        segments.setdefault(head, set()).add((way, seg))
    return {node for node, segs in segments.items() if len(segs) == 1}


@pytest.mark.slow
def test_rebuilding_l_is_byte_identical(tmp_path):
    """Determinism (CLAUDE.md rule 5) — the rule is per stage, not per artifact."""
    import hashlib

    import geopandas as gpd

    from efficientroute import restrictions as R
    from efficientroute import turngraph

    if not C.NETWORK_GPKG.exists() or not C.PBF_PATH.exists():
        pytest.skip("source data missing")

    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    parsed = R.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))

    digests = []
    for i in range(2):
        out = tmp_path / f"run{i}.pkl"
        turngraph.build_turn_graph(arcs, parsed).save(out)
        digests.append(hashlib.sha256(out.read_bytes()).hexdigest())
    assert digests[0] == digests[1], "two identical builds of L produced different bytes"


# ------------------------------------------- Stage 0b — trap cause classification


def test_every_trap_carries_a_cause(audit):
    rows = audit["traps"]["rows"]
    assert rows, "no traps at all — the classification cannot be exercised"
    for row in rows:
        assert row["trap_cause"] in {"clip_boundary", "genuine"}
        assert "trap_cause_rule" in row
        assert "dangling_node" in row


def test_trap_causes_sum_to_the_totals(audit):
    traps = audit["traps"]
    by_cause = traps["by_cause"]
    assert (
        by_cause["clip_boundary"]["no_legal_exit"] + by_cause["genuine"]["no_legal_exit"]
        == traps["no_legal_exit"]
    )
    assert (
        by_cause["clip_boundary"]["no_legal_entry"] + by_cause["genuine"]["no_legal_entry"]
        == traps["no_legal_entry"]
    )


BOUNDARY_ROADS = (
    "თბილისის შემოსავლელი გზა",      # Tbilisi Bypass Road
    "თბილისი — სენაკი — ლესელიძე",    # Tbilisi-Senaki-Leselidze
    "ფონიჭალა — მარნეული — გუგუთი",  # Ponichala-Marneuli-Guguti
    "თბილისი — ბაკურციხე — ლაგოდეხი",  # Tbilisi-Bakurtsikhe-Lagodekhi
)


def test_the_substantial_boundary_road_traps_are_classified_as_clip_artefacts(audit):
    """The Stage 0b brief names these as the signature of a road leaving the extract.

    Scoped to traps of real length: a metre-scale stub on one of these roads deep
    inside the clip is a genuine OSM artefact and belongs in the genuine list, so
    asserting the *name* never appears there would be asserting the wrong thing.
    """
    offenders = [
        r
        for r in audit["traps"]["rows"]
        if r["trap_cause"] == "genuine"
        and r["name"] in BOUNDARY_ROADS
        and r["length_m"] > 100.0
    ]
    assert offenders == [], offenders


def test_boundary_road_traps_dominate_the_clip_classification(audit):
    clip_rows = [r for r in audit["traps"]["rows"] if r["trap_cause"] == "clip_boundary"]
    named = [r for r in clip_rows if r["name"] in BOUNDARY_ROADS]
    assert len(named) >= 8, "the named through-routes should account for most clip traps"
