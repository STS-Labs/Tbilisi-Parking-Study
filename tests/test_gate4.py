"""Stage 4 gate. Every assertion here is copied from prompts/04-zoning.md.

The zoning is re-derived from `04-zones.gpkg` and a freshly rebuilt `L(G)`, not
read out of `04-zones.json`: a gate that asks a stage whether it did its job is
not a gate.
"""
import json

import numpy as np
import pytest

from efficientroute import config as C
from efficientroute import scenarios
from efficientroute import zoning

pytestmark = pytest.mark.gate4


@pytest.fixture(scope="module")
def payload() -> dict:
    if not C.ZONES_JSON.exists():
        pytest.skip(f"{C.ZONES_JSON} not built — run `make stage4`")
    return json.loads(C.ZONES_JSON.read_text())


@pytest.fixture(scope="module")
def window(payload) -> dict:
    return payload["windows"][payload["default_window"]]


@pytest.fixture(scope="module")
def rebuilt():
    """The chosen scope's L(G), zone graph and zone labels, rebuilt from disk."""
    import geopandas as gpd

    from efficientroute import lstar, restrictions, scenarios, turngraph
    from efficientroute import timemodel as TM

    for required in (C.NETWORK_GPKG, C.ZONES_GPKG, C.PBF_PATH):
        if not required.exists():
            pytest.skip(f"{required} missing — run `make stage4`")

    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    zones_gpkg = gpd.read_file(C.ZONES_GPKG, layer=C.ZONES_LAYER)
    frame = scenarios.apply_variant(arcs, C.SCOPE_VARIANT)

    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    parsed = restrictions.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))
    graph = turngraph.build_turn_graph(frame, parsed)
    keep = lstar.largest_strong_component(graph)

    arc_ids = graph.arc_index["arc_id"].to_numpy()
    rows = frame.set_index("arc_id").loc[arc_ids]
    model = TM.load_model()
    zone_graph = zoning.build(
        graph, keep,
        rows["capture_time_s"].to_numpy(dtype="float64"),
        rows["length_m"].to_numpy(dtype="float64"),
    )

    assert zones_gpkg["arc_id"].is_unique, "the zone layer must be one row per arc"
    zone_of_arc = zones_gpkg.set_index("arc_id")["zone_id"].to_dict()
    labels = np.full(zone_graph.n_segments, -1, dtype="int64")
    for node in range(graph.n_nodes):
        segment = zone_graph.segment_of_node[node]
        if segment >= 0:
            labels[segment] = int(zone_of_arc[arc_ids[node]])

    return {
        "graph": graph,
        "keep": keep,
        "zone_graph": zone_graph,
        "labels": labels,
        "frame": frame,
        "zones_gpkg": zones_gpkg,
        "deadhead_s": model.deadhead_time_s(rows),
        "traversals": zoning.required_traversals(graph.arc_index),
    }


# --------------------------------------------------- one zone per element


def test_every_required_element_is_in_exactly_one_zone(rebuilt):
    """The partition is a partition: no element uncovered, none counted twice."""
    labels = rebuilt["labels"]
    assert (labels >= 0).all(), int((labels < 0).sum())

    zone_graph = rebuilt["zone_graph"]
    assert len(labels) == zone_graph.n_segments
    # Every in-scope L-node maps to exactly one segment, and each segment to one zone.
    in_scope = np.flatnonzero(zone_graph.segment_of_node >= 0)
    assert len(in_scope) == int(rebuilt["keep"].sum())


def test_no_required_element_of_the_chosen_scope_is_missing(rebuilt):
    zone_graph, keep = rebuilt["zone_graph"], rebuilt["keep"]
    required = (rebuilt["traversals"] > 0) & keep
    assert (zone_graph.segment_of_node[required] >= 0).all()


def test_the_gpkg_carries_exactly_the_chosen_scope(rebuilt, payload):
    """The artifact must be the scope the run was configured for — whichever it is.

    This asserted `highway_class != "service"` outright, which is the right check
    for variant C and a false one for any other. It was Tbilisi's scope decision
    written down as an invariant, and a campaign configured for variant A failed it
    for being configured correctly.

    The invariant underneath is stronger and campaign-relative: whatever the
    variant, the arcs in the tour scope are exactly the arcs that variant keeps.
    Under C that still forbids every service road; under A it forbids nothing and
    instead catches an arc dropped by a filter nobody declared.
    """
    assert payload["variant"] == C.SCOPE_VARIANT
    in_scope = rebuilt["zones_gpkg"]
    kept = scenarios.variant_mask(in_scope, C.SCOPE_VARIANT)
    assert (~kept & in_scope["in_tour_scope"].to_numpy()).sum() == 0


def test_service_role_survived_as_a_column_for_phase_two(rebuilt):
    """SPEC §2.1.1 — re-including `through` service must be a config change."""
    assert "service_role" in rebuilt["zones_gpkg"].columns


# --------------------------------------------------- connectivity in L(G)


def test_every_zone_is_connected(rebuilt):
    zone_graph, labels = rebuilt["zone_graph"], rebuilt["labels"]
    broken = zoning.disconnected_zones(zone_graph, labels)
    assert broken == {}, f"zones in more than one piece: {broken}"


def test_zone_connectivity_is_measured_in_l_not_on_the_map(rebuilt):
    """Two segments a street apart may be six kilometres apart by road (SPEC §4)."""
    zone_graph, labels = rebuilt["zone_graph"], rebuilt["labels"]
    zone = int(labels[0])
    members = np.flatnonzero(labels == zone)
    assert zoning.is_connected(zone_graph, members)
    # The adjacency it is connected through is L's manoeuvres, not proximity.
    assert len(zone_graph.adjncy) > 0


# --------------------------------------------------------- I4 and balance


def test_i4_no_day_exceeds_its_window(payload):
    """Capture + turns + legs + break inside the usable hours, every day."""
    for name, block in payload["windows"].items():
        for day in block["campaign"]["day_table"]:
            assert day["total_h"] <= day["available_h"] + 1e-9, (
                f"{name} day {day['position']} (zone {day['zone']}): "
                f"{day['total_h']:.3f} h in a {day['available_h']:.3f} h window"
            )


def test_the_day_total_is_its_parts(payload):
    for block in payload["windows"].values():
        for day in block["campaign"]["day_table"]:
            assert day["total_h"] == pytest.approx(
                day["work_h"] + day["leg_out_h"] + day["leg_back_h"] + day["break_h"],
                rel=1e-9,
            )


def test_work_hours_are_capture_scaled_by_the_measured_overhead(payload):
    factor = payload["overhead"]["factor"]
    for block in payload["windows"].values():
        for day in block["campaign"]["day_table"]:
            assert day["work_h"] == pytest.approx(day["capture_h"] * factor, rel=1e-9)


def test_the_overhead_came_from_a_measurement_not_a_guess(payload):
    """Originally Stage 3's tour; since 26 Aug, Stage 5's solved day routes.

    Stage 4c, 27 Aug: the first version of that Stage 5 figure was `route_h /
    capture_h`, which includes the depot legs the cost model then adds again — so
    "measured" was necessary but not sufficient, and the value has to be the
    *intra-zone* ratio. `gate4c` checks the quantity; this checks the provenance.
    A pinned constant is allowed, but it must name the measurement it came from
    (`ZONE_OVERHEAD_PIN_SOURCE`), or it is indistinguishable from a guess."""
    source = payload["overhead"]["source"]
    assert "fallback" not in source, source
    assert any(stage in source for stage in ("Stage 3", "Stage 5")), source


def test_day_durations_are_balanced_within_the_stated_threshold(payload):
    for name, block in payload["windows"].items():
        stdev = block["campaign"]["day_hours_stdev"]
        assert stdev <= C.DAY_BALANCE_STDEV_MAX_H, (
            f"{name}: day durations vary by {stdev:.3f} h, above the "
            f"{C.DAY_BALANCE_STDEV_MAX_H} h threshold"
        )


def test_the_break_is_inside_every_day(payload):
    for block in payload["windows"].values():
        for day in block["campaign"]["day_table"]:
            assert day["break_h"] == pytest.approx(C.BREAK_HOURS)


# ------------------------------------------------------------- sequencing


def test_the_sequence_is_descending_in_depot_leg_cost(payload):
    """SPEC §7.1 mitigation 2. Easy to implement backwards, so it is asserted."""
    for name, block in payload["windows"].items():
        legs = [d["leg_baseline_h"] for d in block["campaign"]["day_table"]]
        assert legs == sorted(legs, reverse=True), f"{name} is not far-zones-first"


def test_the_first_day_is_further_out_than_the_last(payload):
    for block in payload["windows"].values():
        days = block["campaign"]["day_table"]
        assert days[0]["leg_baseline_h"] > days[-1]["leg_baseline_h"]


def test_days_are_numbered_and_dated_in_order(payload):
    for block in payload["windows"].values():
        days = block["campaign"]["day_table"]
        assert [d["position"] for d in days] == list(range(len(days)))
        assert [d["date"] for d in days] == sorted(d["date"] for d in days)


# ------------------------------------------------------------ routed legs


def test_depot_legs_are_routed_over_l_not_estimated(rebuilt, payload, window):
    """Recomputed from L(G) here; the artifact has to agree arc for arc."""
    from efficientroute import depotlegs

    graph = rebuilt["graph"]
    node, arc_id, offset = depotlegs.find_depot_node(rebuilt["frame"], graph)
    assert arc_id == payload["depot"]["arc_id"]
    field = depotlegs.leg_field(graph, rebuilt["deadhead_s"], node, arc_id, offset)

    zone_graph, labels = rebuilt["zone_graph"], rebuilt["labels"]
    for day in window["campaign"]["day_table"]:
        members = np.flatnonzero(labels == day["zone"])
        nodes = np.concatenate([zone_graph.nodes_of_segment[s] for s in members])
        out = depotlegs.nearest_in_zone(field, nodes, True)[0]
        back = depotlegs.nearest_in_zone(field, nodes, False)[0]
        assert (out + back) / 3600.0 == pytest.approx(day["leg_baseline_h"], rel=1e-9)


def test_a_routed_leg_is_slower_than_the_crow_flies(payload):
    """The known-pair check.

    A depot leg is deadhead, and SPEC §6 leaves deadhead uncapped, so it may run
    faster than the 40 km/h capture cap — the floor here is the fastest free-flow
    speed in the model, which nothing can beat on a real road network. A
    straight-line estimate would have no such floor at all.
    """
    ceiling = max(C.BASE_FREE_FLOW_KMH.values())
    for row in payload["leg_comparison"]["zones"]:
        if row["straight_km"] < 0.5:
            continue   # the zone the depot itself sits in; its leg is zero
        floor_h = 2.0 * row["straight_km"] / ceiling
        assert row["routed_h"] >= floor_h - 1e-9, row


def test_the_depot_sits_inside_one_zone_and_that_zone_has_no_leg(payload):
    nearest = min(payload["leg_comparison"]["zones"], key=lambda r: r["straight_km"])
    assert nearest["straight_km"] < 0.5
    assert nearest["routed_h"] < 0.05


def test_most_zones_are_further_by_road_than_by_air(payload):
    """The point of routing them: the road network is not a straight line."""
    rows = payload["leg_comparison"]["zones"]
    detoured = [r for r in rows if r["routed_h"] * C.DEPOT_LEG_SPEED_KMH > 2 * r["straight_km"]]
    assert len(detoured) > len(rows) // 2, "routing barely differs from the crow flight"


def test_the_routed_total_differs_from_the_stage_two_band_estimate(payload):
    """If they matched, the bands would not have been replaced by anything."""
    comparison = payload["leg_comparison"]
    assert comparison["routed_total_h"] != pytest.approx(
        comparison["stage2_estimate_total_h"], rel=1e-3
    )


def test_the_depot_maps_onto_a_real_arc_close_by(payload):
    assert payload["depot"]["offset_m"] < 200.0
    assert payload["depot"]["arc_id"]


# ---------------------------------------------------- commute and daylight


def test_commute_capture_is_accounted_not_invented(payload):
    for block in payload["windows"].values():
        campaign = block["campaign"]
        credited = sum(d["commute_capture_h"] for d in campaign["day_table"])
        assert campaign["commute_capture_h"] == pytest.approx(credited, rel=1e-9)
        assert campaign["coverage_routed_legs"] + campaign["plain_legs"] == campaign["days"]


def test_the_taper_is_computed_for_every_day(payload):
    for block in payload["windows"].values():
        for day in block["campaign"]["day_table"]:
            nominal = C.SHIFT_WINDOWS[block["campaign"]["window"]]
            assert day["taper_h"] == pytest.approx(
                (nominal[1] - nominal[0]) - day["available_h"], abs=1e-9
            )


def test_the_latest_feasible_start_is_reported(payload):
    for name, block in payload["daylight"].items():
        assert block["latest_feasible_start"] is not None, name


# ------------------------------------------------------------ unreachable


def test_the_unreachable_set_was_recomputed_for_this_scope(payload):
    """Stage 3 measured 129.9 km under variant A; most of it was service."""
    unreachable = payload["unreachable"]
    assert unreachable["required_km_unreachable"] < 100.0, (
        "the variant A figure appears to have been carried forward"
    )
    assert unreachable["required_km_absent_from_l"] + unreachable[
        "required_km_trapped_in_l"
    ] == pytest.approx(unreachable["required_km_unreachable"], rel=1e-9)


def test_the_unreachable_share_is_small_enough_for_the_plan_to_mean_something(payload):
    assert payload["unreachable"]["share_unreachable"] < 0.05


def test_the_trapped_arcs_are_attributed_by_class(payload):
    assert payload["unreachable"]["trapped_by_class"]


# ----------------------------------------------------------- determinism


def test_the_zone_graph_rebuilds_identically(rebuilt):
    """CLAUDE.md rule 5 — same inputs, same segments, same adjacency."""
    again = zoning.build(
        rebuilt["graph"], rebuilt["keep"],
        np.zeros(rebuilt["graph"].n_nodes), np.zeros(rebuilt["graph"].n_nodes),
    )
    assert again.segment_id.tolist() == rebuilt["zone_graph"].segment_id.tolist()
    assert again.adjncy.tolist() == rebuilt["zone_graph"].adjncy.tolist()


def test_partitioning_the_same_graph_twice_agrees(rebuilt):
    zone_graph = rebuilt["zone_graph"]
    a = zoning.partition(zone_graph, 8)
    b = zoning.partition(zone_graph, 8)
    assert a.tolist() == b.tolist()


def test_the_artifact_records_the_network_it_was_built_from(payload):
    from efficientroute import extract as X

    assert payload["meta"]["arcs_sha256"] == X.file_digest(C.NETWORK_GPKG)


# --------------------------------------------------------------- non-goals


def test_no_intra_zone_route_was_solved(payload, window):
    """Stage 4 says what each day covers, not the order within it — that is Stage 5."""
    day = window["campaign"]["day_table"][0]
    assert "route" not in day and "tour" not in day
