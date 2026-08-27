"""Stage 3 gate. Every assertion here is copied from prompts/03-bounds.md.

The invariant suite is re-run from the persisted tour rather than read out of
`03-bounds.json`: a gate that asks a stage whether it did its job is not a gate.
`L*` is rebuilt from `turn_graph.pkl` and `network.gpkg`, so nothing the solver
kept in memory is trusted.
"""
import json

import numpy as np
import pytest

from efficientroute import config as C
from efficientroute import lowerbound as LB
from efficientroute import lstar as LS
from efficientroute import orientation as O
from efficientroute import tourcheck as TC

pytestmark = pytest.mark.gate3

VARIANT = "A"


@pytest.fixture(scope="module")
def payload() -> dict:
    if not C.BOUNDS_JSON.exists():
        pytest.skip(f"{C.BOUNDS_JSON} not built — run `make stage3`")
    return json.loads(C.BOUNDS_JSON.read_text())


@pytest.fixture(scope="module")
def variant_a(payload) -> dict:
    return next(r for r in payload["variants"] if r["variant"] == VARIANT)


@pytest.fixture(scope="module")
def rebuilt():
    """L*, the graph and the tour for variant A, rebuilt from the artifacts."""
    import geopandas as gpd

    from efficientroute import timemodel as TM
    from efficientroute import turngraph

    tour_path = C.ROOT / str(C.TOUR_NPZ).format(variant=VARIANT)
    for required in (C.NETWORK_GPKG, C.TURN_GRAPH_PATH, tour_path):
        if not required.exists():
            pytest.skip(f"{required} missing — run `make stage3`")

    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    graph = turngraph.load(C.TURN_GRAPH_PATH)
    model = TM.load_model()

    stored = np.load(tour_path)
    rows = arcs.set_index("arc_id").loc[graph.arc_index["arc_id"].to_numpy()]
    star = LS.build(
        graph,
        capture_s=rows["capture_time_s"].to_numpy(dtype="float64"),
        deadhead_s=model.deadhead_time_s(rows),
        lower_bounds=stored["lower"][: graph.n_nodes].astype("int64"),
        keep=stored["keep"],
    )
    return {
        "arcs": arcs,
        "graph": graph,
        "star": star,
        "tour": stored["tour"].astype("int64"),
        "flow": stored["flow"].astype("int64"),
        "lower": stored["lower"].astype("int64"),
        "keep": stored["keep"],
        "length_m": rows["length_m"].to_numpy(dtype="float64"),
    }


@pytest.fixture(scope="module")
def audit(rebuilt):
    return TC.audit(rebuilt["tour"], rebuilt["star"], rebuilt["graph"])


# ------------------------------------------------------------------ the tour


def test_i1_every_required_element_is_covered(audit):
    """I1 — every arc at least `min_passes`, every narrow pair at least once."""
    check = next(c for c in audit.checks if c.name == "I1")
    assert check.passed, check.detail


def test_i1_holds_against_the_oriented_lower_bounds_too(audit):
    check = next(c for c in audit.checks if c.name == "lower_bounds")
    assert check.passed, check.detail


def test_i2_every_manoeuvre_in_the_tour_is_legal(audit):
    """I2 — every consecutive arc pair is an edge of L."""
    check = next(c for c in audit.checks if c.name == "I2")
    assert check.passed, check.detail


def test_the_tour_is_closed(audit):
    check = next(c for c in audit.checks if c.name == "closed")
    assert check.passed, check.detail


def test_i6_every_arc_in_the_tour_exists_in_the_base_network(rebuilt, audit):
    """I6 — no invented geometry, checked against `network.gpkg` itself."""
    check = next(c for c in audit.checks if c.name == "I6")
    assert check.passed, check.detail

    star, tour = rebuilt["star"], rebuilt["tour"]
    driven = set(star.arc_id[np.unique(tour)])
    assert driven <= set(rebuilt["arcs"]["arc_id"]), "an arc in the tour is not in the network"


def test_the_tour_matches_the_flow_it_was_built_from(rebuilt, audit):
    check = TC.check_matches_flow(audit.visit_counts, rebuilt["flow"], rebuilt["star"])
    assert check.passed, check.detail


def test_the_tour_uses_only_edges_present_in_l_star(rebuilt):
    """Every edge the flow paid for is an edge L* actually offers."""
    star, flow = rebuilt["star"], rebuilt["flow"]
    assert len(flow) == star.n_edges
    assert (flow >= 0).all()
    assert (flow <= star.upper).all(), int((flow > star.upper).sum())


def test_no_arc_outside_the_tourable_component_is_driven(rebuilt):
    star, tour = rebuilt["star"], rebuilt["tour"]
    assert star.in_scope[np.unique(tour)].all()


# ------------------------------------------------------------------- costs


def test_the_total_time_is_the_sum_of_its_edge_costs_recomputed(rebuilt, audit, variant_a):
    """Recomputed from the tour, not read back from the solver's objective."""
    assert audit.total_s / 3600.0 == pytest.approx(variant_a["total_h"], rel=1e-9)
    assert audit.capture_s / 3600.0 == pytest.approx(variant_a["capture_h"], rel=1e-9)
    assert audit.turn_s / 3600.0 == pytest.approx(variant_a["turn_h"], rel=1e-9)
    assert audit.deadhead_s / 3600.0 == pytest.approx(variant_a["deadhead_h"], rel=1e-9)


def test_the_components_sum_to_the_total(variant_a):
    total = variant_a["capture_h"] + variant_a["turn_h"] + variant_a["deadhead_h"]
    assert total == pytest.approx(variant_a["total_h"], rel=1e-9)


def test_turn_time_is_recomputed_edge_by_edge(rebuilt, audit):
    """The independent recomputation the brief asks for, done a second way."""
    graph, tour = rebuilt["graph"], rebuilt["tour"]
    pairs = TC.steps(tour)
    total = sum(graph.adjacency[int(a)][int(b)][1] for a, b in pairs)
    assert total == pytest.approx(audit.turn_s, rel=1e-9)


def test_the_deadhead_ratio_is_reported_against_capture(variant_a):
    ratio = variant_a["deadhead_h"] / variant_a["capture_h"] * 100.0
    assert variant_a["deadhead_pct_of_capture"] == pytest.approx(ratio, rel=1e-9)


def test_driven_km_is_at_least_the_required_km(variant_a):
    assert variant_a["driven_km"] >= variant_a["required_km_in_scope"]


# ------------------------------------------------------------------ bounds


def test_upper_is_at_or_above_lower_for_every_variant(payload):
    """A violation means one of the two is wrong; there is no benign version."""
    for row in payload["variants"]:
        assert row["total_h"] >= row["lower_bound_h"], (
            f"variant {row['variant']}: upper {row['total_h']:.1f} h is below "
            f"lower {row['lower_bound_h']:.1f} h"
        )


def test_the_lp_bound_is_at_or_above_the_combinatorial_one(payload):
    """Both are valid, so the LP being weaker would mean it solved a wrong model."""
    for row in payload["variants"]:
        lp = row["lower_bound_lp"]
        if lp["status"] != "optimal":
            continue
        assert lp["lower_bound_h"] >= row["lower_bound_fallback"]["lower_bound_h"] - 1e-6


def test_the_gap_is_reported_and_consistent(payload):
    """CLAUDE.md rule 2 — a result with no stated optimality gap is incomplete."""
    for row in payload["variants"]:
        expected = (row["total_h"] - row["lower_bound_h"]) / row["lower_bound_h"]
        assert row["optimality_gap"] == pytest.approx(expected, rel=1e-9)


def test_the_bound_method_is_named(payload):
    for row in payload["variants"]:
        assert row["lower_bound_method"] in {"lp_relaxation", "capture_floor_plus_cheapest_exit"}


def test_every_variant_is_present(payload):
    assert [r["variant"] for r in payload["variants"]] == list(C.STAGE2_SCOPE_VARIANTS)


def test_dropping_service_roads_never_lengthens_the_tour(payload):
    by_variant = {r["variant"]: r for r in payload["variants"]}
    assert by_variant["A"]["total_h"] > by_variant["D"]["total_h"] > by_variant["C"]["total_h"]


# ------------------------------------------------------------------- days


def test_days_divide_the_total_by_the_stated_productive_hours(payload):
    day = payload["day"]
    assert day["productive_hours"] == pytest.approx(C.SHIFT_HOURS - C.BREAK_HOURS)
    for row in payload["variants"]:
        assert row["days"] == pytest.approx(row["total_h"] / day["productive_hours"], rel=1e-9)


def test_the_extended_shift_table_is_present_and_shorter(payload):
    day = payload["day"]
    assert day["extended_shift_hours"] == pytest.approx(10.0)
    for row in payload["variants"]:
        assert row["days_extended_shift"] == pytest.approx(
            row["total_h"] / day["extended_productive_hours"], rel=1e-9
        )
        assert row["days_extended_shift"] < row["days"]


# -------------------------------------------------------------- scope losses


def test_the_uncoverable_requirement_is_reported_not_absorbed(payload):
    """CLAUDE.md rule 4 — arcs no closed tour can reach are logged, never silent."""
    for row in payload["variants"]:
        assert row["required_km_out_of_scope"] >= 0.0
        assert row["required_km_in_scope"] + row["required_km_out_of_scope"] == pytest.approx(
            row["required_km_total"], rel=1e-9
        )


def test_the_scope_loss_is_small_enough_that_the_bound_still_means_something(payload):
    for row in payload["variants"]:
        share = row["required_km_out_of_scope"] / row["required_km_total"]
        assert share < 0.05, f"variant {row['variant']} cannot reach {share:.2%} of its requirement"


# ------------------------------------------------------------- determinism


def test_the_orientation_is_reproducible(rebuilt):
    """Rebuilt from the arc index alone and compared with what was persisted."""
    again = O.orient(rebuilt["graph"].arc_index, keep=rebuilt["keep"])
    assert again.lower.tolist() == rebuilt["lower"][: rebuilt["graph"].n_nodes].tolist()


def test_the_euler_circuit_is_reproducible_from_the_persisted_flow(rebuilt, variant_a):
    import hashlib

    from efficientroute import euler

    again = euler.tour(rebuilt["star"], rebuilt["flow"])
    assert again.tolist() == rebuilt["tour"].tolist()
    digest = hashlib.sha256(again.astype("int32").tobytes()).hexdigest()
    assert digest == variant_a["tour_sha256"]


def test_the_combinatorial_bound_is_reproducible(rebuilt, variant_a):
    again = LB.combinatorial_bound(rebuilt["star"], rebuilt["graph"])
    assert again.value_s / 3600.0 == pytest.approx(
        variant_a["lower_bound_fallback"]["lower_bound_h"], rel=1e-12
    )


@pytest.mark.slow
def test_the_min_cost_flow_is_reproducible(rebuilt):
    """The expensive half of determinism: re-solve and compare edge for edge."""
    from efficientroute import dcpp

    again = dcpp.solve(rebuilt["star"])
    assert again.x.tolist() == rebuilt["flow"].tolist()


# ---------------------------------------------------------------- artifacts


def test_the_gpx_exists_and_is_a_single_track(variant_a):
    path = C.ROOT / variant_a["gpx_path"]
    if not path.exists():
        pytest.skip("GPX not generated — run `make stage3`")
    head = path.read_text()[:4000]
    assert "<trkseg>" in head and "<gpx" in head


def test_the_spec_conflict_is_recorded_rather_than_resolved_silently(payload):
    """SPEC §4 calls the constructive result a lower bound. It is an upper one."""
    assert "upper" in payload["spec_note"].lower()
    assert "I5" in payload["spec_note"]
