"""Stage 0 gate. Every assertion here is copied from prompts/00-extract-and-measure.md.

A failing assertion is a hard stop for Stage 1 (CLAUDE.md, "Stages are gated").
"""
import hashlib

import pytest

from efficientroute import config as C

pytestmark = pytest.mark.gate

REQUIRED_COLUMNS = [
    "arc_id", "way_id", "from_node", "to_node", "geometry", "length_m",
    "highway_class", "lanes", "width", "surface", "maxspeed", "oneway",
    "incline", "gradient_pct", "min_passes", "pair_id", "pair_requirement",
    "capture_quality", "excluded", "exclusion_reason",
]


def test_schema_has_every_required_column(arcs):
    missing = [c for c in REQUIRED_COLUMNS if c not in arcs.columns]
    assert missing == [], f"missing required columns: {missing}"


def test_arc_ids_are_unique(arcs):
    assert arcs["arc_id"].is_unique


def test_every_arc_has_min_passes_of_at_least_one(arcs):
    assert arcs["min_passes"].notna().all()
    assert (arcs["min_passes"] >= 1).all()


def test_every_excluded_arc_has_a_reason(arcs):
    excluded = arcs[arcs["excluded"]]
    assert excluded["exclusion_reason"].notna().all()
    assert (excluded["exclusion_reason"].astype(str).str.len() > 0).all()


def test_no_included_arc_carries_a_reason(arcs):
    included = arcs[~arcs["excluded"]]
    reasons = included["exclusion_reason"].fillna("")
    assert (reasons == "").all(), sorted(set(reasons[reasons != ""]))


def test_every_twoway_pair_id_maps_to_exactly_two_arcs(arcs):
    paired = arcs[arcs["pair_id"].fillna("") != ""]
    counts = paired.groupby("pair_id").size()
    assert (counts == 2).all(), counts[counts != 2].head(20).to_dict()


def test_oneway_arcs_carry_no_pair_id(arcs):
    oneway = arcs[arcs["oneway"] != "no"]
    assert (oneway["pair_id"].fillna("") == "").all()


def test_per_class_km_sums_to_total_km(arcs):
    total = arcs["length_m"].sum()
    per_class = arcs.groupby("highway_class")["length_m"].sum().sum()
    assert per_class == pytest.approx(total, rel=1e-12)


def test_every_geometry_has_at_least_two_coordinates_and_nonzero_length(arcs):
    coord_counts = arcs.geometry.apply(lambda g: len(g.coords))
    assert (coord_counts >= 2).all(), int((coord_counts < 2).sum())
    assert (arcs["length_m"] > 0).all(), int((arcs["length_m"] <= 0).sum())
    assert arcs.geometry.is_valid.all()


def test_capture_quality_matches_the_class(arcs):
    reduced = arcs[arcs["highway_class"].isin(C.REDUCED_QUALITY_CLASSES)]
    assert (reduced["capture_quality"] == "reduced").all()
    rest = arcs[~arcs["highway_class"].isin(C.REDUCED_QUALITY_CLASSES)]
    assert (rest["capture_quality"] == "full").all()


def test_narrow_pair_requirement_is_only_set_on_two_way_pairs(arcs):
    shared = arcs[arcs["pair_requirement"] > 0]
    assert (shared["oneway"] == "no").all()
    assert (shared["pair_id"].fillna("") != "").all()


def test_largest_scc_holds_at_least_95_percent_of_included_arc_km(stats):
    share = stats["scc"]["largest_share_of_included_km"]
    assert share >= 0.95, (
        f"largest SCC holds {share:.4%} of included arc km — below the 95% gate. "
        "Per the stage brief this means the drivability filter or the one-way "
        "data is wrong; stop and report."
    )


@pytest.mark.slow
def test_rebuilding_from_the_same_extract_is_byte_identical(tmp_path):
    """Determinism (CLAUDE.md rule 5). Rebuilds the arcs layer twice and compares bytes."""
    if not C.EXTRACT_PATH.exists():
        pytest.skip("extract cache missing — run `uv run efficientroute stage0`")
    from efficientroute import network, pipeline

    digests = []
    for i in range(2):
        out = tmp_path / f"run{i}.gpkg"
        network.write_gpkg(pipeline.rebuild_arc_table(), out)
        digests.append(hashlib.sha256(out.read_bytes()).hexdigest())
    assert digests[0] == digests[1], "two identical runs produced different bytes"


@pytest.mark.slow
def test_rebuild_matches_the_committed_artifact(tmp_path):
    if not C.EXTRACT_PATH.exists() or not C.NETWORK_GPKG.exists():
        pytest.skip("artifacts missing — run `uv run efficientroute stage0`")
    from efficientroute import network, pipeline

    out = tmp_path / "rebuild.gpkg"
    network.write_gpkg(pipeline.rebuild_arc_table(), out)
    assert (
        hashlib.sha256(out.read_bytes()).hexdigest()
        == hashlib.sha256(C.NETWORK_GPKG.read_bytes()).hexdigest()
    )


# ------------------------------------------------------- Stage 0b — service scope


def test_service_type_is_set_for_every_service_arc_and_null_elsewhere(arcs):
    service = arcs[arcs["highway_class"] == "service"]
    others = arcs[arcs["highway_class"] != "service"]
    assert service["service_type"].notna().all(), int(service["service_type"].isna().sum())
    assert others["service_type"].isna().all(), int(others["service_type"].notna().sum())


def test_service_subtag_breakdown_reconciles_to_the_service_total(stats):
    rows = stats["service"]["by_type"]
    assert sum(r["required_km"] for r in rows) == pytest.approx(
        stats["service"]["required_km"], abs=1e-6
    )
    assert sum(r["arc_count"] for r in rows) == stats["service"]["arc_count"]


def test_service_scope_variant_a_reconciles_to_the_headline():
    """Variant A must reproduce the pre-Stage-0b numbers exactly.

    A mismatch means the subtag join is wrong, not that the old number was.
    """
    import json

    if not C.SERVICE_SCENARIOS_JSON.exists():
        pytest.skip("scenarios not built — run `make stage0b`")
    payload = json.loads(C.SERVICE_SCENARIOS_JSON.read_text())
    variant_a = next(v for v in payload["variants"] if v["variant"] == "A")
    variant_c = next(v for v in payload["variants"] if v["variant"] == "C")

    assert variant_a["required_traversal_km"] == pytest.approx(5725.3, abs=0.05)
    assert variant_a["delta_required_km"] == pytest.approx(0.0, abs=1e-9)
    # dropping every service arc must remove exactly the measured service total
    assert -variant_c["delta_required_km"] == pytest.approx(2196.0, abs=0.05)


def test_service_scope_variants_are_nested_and_monotone():
    import json

    if not C.SERVICE_SCENARIOS_JSON.exists():
        pytest.skip("scenarios not built — run `make stage0b`")
    payload = json.loads(C.SERVICE_SCENARIOS_JSON.read_text())
    by_variant = {v["variant"]: v for v in payload["variants"]}
    assert (
        by_variant["C"]["required_traversal_km"]
        <= by_variant["B"]["required_traversal_km"]
        <= by_variant["A"]["required_traversal_km"]
    )
    assert by_variant["C"]["l_nodes"] <= by_variant["B"]["l_nodes"] <= by_variant["A"]["l_nodes"]
