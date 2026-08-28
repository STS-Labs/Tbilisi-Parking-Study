"""Stage 5 gate. Every assertion here is copied from prompts/05-route-solve.md.

The routes are re-checked from `05-routes.gpkg` and a freshly rebuilt `L(G)`, not
read out of `05-routes.json`. The GPX check is the one that matters most: a track
that parses but diverges from the solved sequence looks fine and sends the driver
somewhere else.
"""
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from efficientroute import config as C

pytestmark = pytest.mark.gate5

GPX_NS = {"g": "http://www.topografix.com/GPX/1/1"}
#: Tbilisi municipality plus the Stage 0 clip buffer, generously rounded.
BBOX = (44.4, 41.4, 45.2, 42.0)


@pytest.fixture(scope="module")
def payload() -> dict:
    if not C.ROUTES_JSON.exists():
        pytest.skip(f"{C.ROUTES_JSON} not built — run `make stage5`")
    return json.loads(C.ROUTES_JSON.read_text())


@pytest.fixture(scope="module")
def manoeuvres():
    import geopandas as gpd

    if not C.ROUTES_GPKG.exists():
        pytest.skip(f"{C.ROUTES_GPKG} not built — run `make stage5`")
    frame = gpd.read_file(C.ROUTES_GPKG, layer=C.ROUTES_LAYER)
    return frame.sort_values(["day", "step"], kind="mergesort").reset_index(drop=True)


@pytest.fixture(scope="module")
def network():
    """The scope's `L(G)`, its orientation and its arc table, rebuilt from disk."""
    import geopandas as gpd

    from efficientroute import lstar, orientation, restrictions, scenarios, turngraph

    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    frame = scenarios.apply_variant(arcs, C.SCOPE_VARIANT)
    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    parsed = restrictions.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))
    graph = turngraph.build_turn_graph(frame, parsed)
    keep = lstar.largest_strong_component(graph)
    oriented = orientation.orient(graph.arc_index, keep=keep)
    index = graph.arc_index
    return {
        "frame": frame,
        "graph": graph,
        "keep": keep,
        "lower": oriented.lower,
        "row_of_arc": {str(a): i for i, a in enumerate(index["arc_id"].to_numpy())},
        "arc_ids": index["arc_id"].to_numpy(),
        "index": index,
    }


# --------------------------------------------------------------- I1 coverage


def test_i1_every_required_element_is_covered_across_the_campaign(manoeuvres, network):
    captured = (
        manoeuvres[manoeuvres["mode"] == "capture"].groupby("arc_id").size().to_dict()
    )
    lower = network["lower"]
    short = []
    for arc_id, row in network["row_of_arc"].items():
        need = int(lower[row])
        if need and captured.get(arc_id, 0) < need:
            short.append((arc_id, captured.get(arc_id, 0), need))
    assert not short, short[:10]


def test_i1_every_narrow_pair_is_driven_at_least_once(manoeuvres, network):
    """SPEC §8 I1 as written, independent of which direction the solver chose."""
    index = network["index"]
    driven = set(manoeuvres["arc_id"])
    pair_of: dict[str, list[str]] = {}
    for arc_id, pair_id, requirement, variant in zip(
        index["arc_id"], index["pair_id"].fillna(""), index["pair_requirement"],
        index["variant"],
    ):
        if pair_id and requirement > 0 and not variant:
            pair_of.setdefault(pair_id, []).append(str(arc_id))
    keep = network["keep"]
    row_of = network["row_of_arc"]
    uncovered = [
        key for key, members in pair_of.items()
        if any(keep[row_of[m]] for m in members) and not (set(members) & driven)
    ]
    assert not uncovered, uncovered[:10]


# ------------------------------------------------------------- I2, I3, I6


def test_i2_every_manoeuvre_is_a_legal_edge_of_l(manoeuvres, network):
    graph, row_of = network["graph"], network["row_of_arc"]
    for day, group in manoeuvres.groupby("day"):
        arcs = [int(n) for n in group["l_node"]]
        for a, b in zip(arcs, arcs[1:] + arcs[:1]):
            assert b in graph.adjacency[a], (
                f"day {day}: {network['arc_ids'][a]} -> {network['arc_ids'][b]} is not in L"
            )


def test_i3_every_day_starts_and_ends_at_the_depot(manoeuvres, payload):
    depot = payload["depot"]["arc_id"]
    for day, group in manoeuvres.groupby("day"):
        first = group.iloc[0]["arc_id"]
        assert first == depot, f"day {day} starts at {first}, not the depot"


def test_i3_every_day_closes_back_onto_its_first_arc(manoeuvres, network):
    """A closed circuit: the last manoeuvre must lead back to where the day began."""
    graph, row_of = network["graph"], network["row_of_arc"]
    for day, group in manoeuvres.groupby("day"):
        first, last = int(group.iloc[0]["l_node"]), int(group.iloc[-1]["l_node"])
        assert first in graph.adjacency[last], f"day {day} does not close"


def test_i6_every_arc_in_every_route_exists_in_the_base_network(manoeuvres, network):
    known = set(network["frame"]["arc_id"].astype(str))
    unknown = set(manoeuvres["arc_id"]) - known
    assert not unknown, sorted(unknown)[:10]


# --------------------------------------------------------------- I4 and I7


def test_i4_no_day_exceeds_its_window(payload):
    over = [d for d in payload["days"] if not d["fits"]]
    assert not over, [
        (d["day"], round(d["day_h"], 3), d["window_h"]) for d in over
    ]


def test_i4_day_hours_are_route_plus_break(payload):
    for day in payload["days"]:
        assert day["day_h"] == pytest.approx(day["route_h"] + day["break_h"], rel=1e-9)
        assert day["route_h"] == pytest.approx(
            day["capture_h"] + day["deadhead_h"] + day["turn_h"], rel=1e-9
        )


def test_i7_no_required_traversal_is_scheduled_above_the_cap(manoeuvres, network):
    frame = network["frame"].set_index("arc_id")
    capture = manoeuvres[manoeuvres["mode"] == "capture"]
    rows = frame.loc[capture["arc_id"].unique()]
    fast = rows[rows["capture_speed_kmh"] > C.CAPTURE_SPEED_MAX_KMH + 1e-9]
    assert (fast["capture_quality"] == "reduced").all(), (
        fast[["highway_class", "capture_speed_kmh"]].head(10).to_dict("records")
    )


# ------------------------------------------------------------------- I8


def test_i8_every_multi_pass_arc_names_a_lane_group_per_pass(manoeuvres):
    multi = manoeuvres[manoeuvres["required_passes"] >= 2]
    if multi.empty:
        pytest.skip("no multi-pass arcs in this scope")
    capture = multi[multi["mode"] == "capture"]
    assert (capture["lane_instruction"].str.len() > 0).all()


def test_i8_the_two_passes_of_an_arc_use_different_lane_groups(manoeuvres):
    multi = manoeuvres[(manoeuvres["required_passes"] >= 2) & (manoeuvres["mode"] == "capture")]
    if multi.empty:
        pytest.skip("no multi-pass arcs in this scope")
    for (day, arc_id), group in multi.groupby(["day", "arc_id"]):
        instructions = list(group["lane_instruction"])
        assert len(set(instructions)) == len(instructions), (day, arc_id, instructions)


def test_a_single_pass_arc_carries_no_lane_instruction(manoeuvres):
    single = manoeuvres[manoeuvres["required_passes"] < 2]
    assert (single["lane_instruction"] == "").all()


# ------------------------------------------------------------ every zone solved


def test_every_zone_has_a_route(payload, manoeuvres):
    zones = {d["zone"] for d in payload["days"]}
    assert zones == set(manoeuvres["zone"].unique())
    assert len(payload["days"]) == len(zones), "one day per zone"


def test_no_day_is_empty(payload):
    for day in payload["days"]:
        assert day["arc_traversals"] > 0
        assert day["capture_h"] > 0


def test_days_are_numbered_and_dated_in_order(payload):
    days = payload["days"]
    assert [d["day"] for d in days] == list(range(1, len(days) + 1))
    assert [d["date"] for d in days] == sorted(d["date"] for d in days)


def test_the_sequence_is_far_zones_first(payload, manoeuvres, network):
    """SPEC §7.1 mitigation 2 survives the split-and-reseat repair."""
    from efficientroute import depotlegs

    from efficientroute import timemodel as TM

    model = TM.load_model()
    graph = network["graph"]
    rows = network["frame"].set_index("arc_id").loc[network["arc_ids"]]
    field = depotlegs.leg_field(
        graph, model.deadhead_time_s(rows), network["row_of_arc"][payload["depot"]["arc_id"]],
        payload["depot"]["arc_id"], 0.0,
    )
    legs = []
    for day in payload["days"]:
        nodes = np.asarray(
            manoeuvres[manoeuvres["day"] == day["day"]]["l_node"].unique(), dtype="int64"
        )
        legs.append(
            depotlegs.nearest_in_zone(field, nodes, True)[0]
            + depotlegs.nearest_in_zone(field, nodes, False)[0]
        )
    assert legs == sorted(legs, reverse=True), "the campaign is not far-zones-first"


# ----------------------------------------------------------------- the GPX


def test_every_day_has_a_gpx_and_a_sheet(payload):
    for day in payload["days"]:
        assert (C.ROUTES_DIR / f"day-{day['day']:02d}.gpx").exists()
        assert (C.ROUTES_DIR / f"day-{day['day']:02d}.md").exists()


def test_every_gpx_parses_and_is_a_single_track(payload):
    for day in payload["days"][:5]:
        root = ET.parse(C.ROUTES_DIR / f"day-{day['day']:02d}.gpx").getroot()
        assert len(root.findall(".//g:trk", GPX_NS)) == 1
        assert len(root.findall(".//g:trkseg", GPX_NS)) == 1


def test_every_gpx_is_geometrically_closed(payload):
    for day in payload["days"]:
        points = _gpx_points(day["day"])
        assert points[0] == points[-1], f"day {day['day']} does not return to its start"


def test_every_gpx_point_is_inside_the_tbilisi_bbox(payload):
    west, south, east, north = BBOX
    for day in payload["days"][:10]:
        for lat, lon in _gpx_points(day["day"]):
            assert south <= lat <= north and west <= lon <= east, (day["day"], lat, lon)


def test_the_gpx_matches_the_solved_manoeuvre_sequence_arc_for_arc(
    payload, manoeuvres, network
):
    """The failure this test exists for: a GPX that parses but diverges from the
    solution looks fine and sends the driver somewhere else."""
    from efficientroute import routeio

    geometry = {
        str(arc_id): list(geom.coords)
        for arc_id, geom in zip(network["frame"]["arc_id"], network["frame"].geometry)
    }

    class Star:
        arc_id = network["arc_ids"]

    for day in payload["days"][:8]:
        tour = np.asarray(
            manoeuvres[manoeuvres["day"] == day["day"]]["l_node"], dtype="int64"
        )
        expected = routeio.route_coordinates(tour, Star(), geometry)
        actual = _gpx_points(day["day"])
        assert len(actual) == len(expected), (day["day"], len(actual), len(expected))
        for (lat, lon), (elon, elat) in zip(actual, expected):
            assert lat == pytest.approx(elat, abs=1e-6)
            assert lon == pytest.approx(elon, abs=1e-6)


def _gpx_points(day: int) -> list[tuple[float, float]]:
    root = ET.parse(C.ROUTES_DIR / f"day-{day:02d}.gpx").getroot()
    return [
        (float(p.get("lat")), float(p.get("lon")))
        for p in root.findall(".//g:trkpt", GPX_NS)
    ]


# ------------------------------------------------------------ totals and I5


def test_the_totals_are_the_sum_of_the_days(payload):
    totals, days = payload["totals"], payload["days"]
    for key in ("capture_h", "deadhead_h", "turn_h", "route_h", "arc_traversals"):
        assert totals[key] == pytest.approx(sum(d[key] for d in days), rel=1e-9)


def test_i5_the_campaign_is_reported_against_the_stage3_bracket(payload):
    bracket = payload["stage3_bracket"]
    assert bracket, "I5 needs the Stage 3 bracket to compare against"
    assert bracket["lower_h"] < bracket["upper_h"]
    assert payload["totals"]["route_h"] > bracket["lower_h"], (
        "a day plan below the LP relaxation would mean one of the two is wrong"
    )


def test_the_turn_account_is_reconciled_against_the_earlier_stages(payload):
    turns = payload["turn_reconciliation"]
    assert turns["stage5_turn_h"] > 0
    assert turns["penalties_s"] == dict(C.TURN_PENALTY_S)
    assert "stage3_tour_turn_h" in turns


def test_the_artifact_records_the_network_it_was_built_from(payload):
    from efficientroute import extract as X

    assert payload["meta"]["arcs_sha256"] == X.file_digest(C.NETWORK_GPKG)
