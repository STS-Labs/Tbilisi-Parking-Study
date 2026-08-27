"""Stage 2 gate. Every assertion here is copied from prompts/02-time-model.md.

A failing assertion is a hard stop for Stage 3 (CLAUDE.md, "Stages are gated").
Where it can, the gate recomputes from the arc table rather than reading what the
stage said about itself: a check that asks `02-time-model.json` whether its own
numbers are right would pass even if the model never ran.
"""
import json

import numpy as np
import pytest

from efficientroute import config as C
from efficientroute import servicerole as SR
from efficientroute import timemodel as TM

pytestmark = pytest.mark.gate2


@pytest.fixture(scope="module")
def payload() -> dict:
    if not C.TIME_MODEL_JSON.exists():
        pytest.skip(f"{C.TIME_MODEL_JSON} not built — run `make stage2`")
    return json.loads(C.TIME_MODEL_JSON.read_text())


@pytest.fixture(scope="module")
def arcs():
    if not C.NETWORK_GPKG.exists():
        pytest.skip(f"{C.NETWORK_GPKG} not built — run `make stage0`")
    import geopandas as gpd

    frame = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    if not TM.has_stage2_columns(frame):
        pytest.skip("network.gpkg predates the Stage 2 columns — run `make stage2`")
    return frame


@pytest.fixture(scope="module")
def included(arcs):
    return arcs[~arcs["excluded"]]


# ------------------------------------------------------- schema and positivity


def test_the_three_stage_two_columns_are_present(arcs):
    missing = [c for c in TM.STAGE2_COLUMNS if c not in arcs.columns]
    assert missing == [], f"missing Stage 2 columns: {missing}"


def test_every_included_arc_has_a_non_null_positive_capture_time(included):
    times = included["capture_time_s"]
    assert times.notna().all(), int(times.isna().sum())
    assert (times > 0).all(), int((times <= 0).sum())


def test_every_included_arc_has_a_positive_capture_speed(included):
    speeds = included["capture_speed_kmh"]
    assert speeds.notna().all(), int(speeds.isna().sum())
    assert (speeds > 0).all(), int((speeds <= 0).sum())


def test_capture_time_is_consistent_with_capture_speed_and_length(included):
    expected = included["length_m"] / (included["capture_speed_kmh"] / 3.6)
    assert included["capture_time_s"].to_numpy() == pytest.approx(
        expected.to_numpy(), rel=1e-9
    )


# ---------------------------------------------------------------- invariant I7


def test_no_required_traversal_implies_a_speed_above_the_cap(included):
    """Invariant I7 / SPEC §3.2 — reduced-quality arcs are the only exemption."""
    traversals = TM.required_traversals(included)
    over_cap = included[
        (included["capture_speed_kmh"] > C.CAPTURE_SPEED_MAX_KMH + 1e-9) & (traversals > 0)
    ]
    offenders = over_cap[over_cap["capture_quality"] != "reduced"]
    assert offenders.empty, offenders[
        ["arc_id", "highway_class", "capture_speed_kmh"]
    ].head(20).to_dict("records")


def test_the_exemption_is_used_rather_than_vacuous(included):
    """If nothing ever exceeded the cap, the test above would prove nothing."""
    traversals = TM.required_traversals(included)
    exempt = included[
        (included["capture_speed_kmh"] > C.CAPTURE_SPEED_MAX_KMH + 1e-9) & (traversals > 0)
    ]
    assert len(exempt) > 0
    assert (exempt["capture_quality"] == "reduced").all()


def test_every_reduced_quality_arc_is_a_motorway_or_trunk_class(included):
    reduced = included[included["capture_quality"] == "reduced"]
    assert set(reduced["highway_class"]) <= set(C.REDUCED_QUALITY_CLASSES)


# ------------------------------------------------------------- `service_role`


def test_service_role_reconciles_to_the_reference_table(arcs):
    """Within 1 km per bucket, on both the all-service and untagged-service splits."""
    summary = SR.summarise(arcs)
    for label, reference in SR.REFERENCE_KM.items():
        block = summary[label]
        for row in block["rows"]:
            expected = reference[row["service_role"]]
            assert row["centerline_km"] == pytest.approx(expected, abs=1.0), (
                f"{label}/{row['service_role']}: {row['centerline_km']:.2f} km "
                f"vs reference {expected:.1f} km"
            )
        assert block["centerline_km"] == pytest.approx(reference["total"], abs=1.0)


def test_the_reported_reconciliation_matches_a_fresh_recomputation(arcs, payload):
    """The report must not be able to disagree with the artifact it describes."""
    fresh = SR.summarise(arcs)
    for label, block in fresh.items():
        stored = {r["service_role"]: r["centerline_km"] for r in payload["service_role"][label]["rows"]}
        for row in block["rows"]:
            assert stored[row["service_role"]] == pytest.approx(row["centerline_km"], abs=1e-6)


def test_every_included_service_arc_carries_a_role(arcs):
    service = arcs[(arcs["highway_class"] == "service") & (~arcs["excluded"])]
    assert set(service["service_role"]) <= set(SR.ROLES)
    assert service["service_role"].notna().all()


def test_no_non_service_arc_carries_a_role(arcs):
    others = arcs[arcs["highway_class"] != "service"]
    assert (others["service_role"].fillna("") == "").all(), sorted(
        set(others["service_role"].dropna()) - {""}
    )


def test_an_excluded_service_arc_is_labelled_rather_than_left_blank(arcs):
    """CLAUDE.md rule 4 — a silent blank would read as 'not a service road'."""
    excluded = arcs[(arcs["highway_class"] == "service") & (arcs["excluded"])]
    if len(excluded):
        assert (excluded["service_role"] == "excluded").all()


# ------------------------------------------------------------- hours reconcile


def test_capture_hours_equal_the_sum_over_required_traversals(included, payload):
    traversals = TM.required_traversals(included)
    total = float((included["capture_time_s"].to_numpy() * traversals).sum() / 3600.0)
    assert payload["capture_hours"] == pytest.approx(total, rel=1e-9)


def test_the_reported_required_traversal_count_is_the_one_on_disk(included, payload):
    assert payload["meta"]["required_traversals"] == int(
        TM.required_traversals(included).sum()
    )


def test_the_variant_a_capture_hours_are_the_free_flow_hours_plus_congestion(payload):
    """Variant A is the whole include set, so it can only be slower than free flow."""
    variant_a = payload["campaign"]["variants"][0]
    assert variant_a["variant"] == "A"
    assert variant_a["capture_hours"] >= payload["capture_hours"]


def test_band_hours_sum_to_the_variant_total(payload):
    for variant in payload["campaign"]["variants"]:
        for key in ("required_km", "capture_hours", "turn_hours", "work_hours"):
            assert sum(b[key] for b in variant["bands"]) == pytest.approx(
                variant[key], rel=1e-9
            )


def test_work_hours_are_capture_plus_turn_and_nothing_else(payload):
    """Deadhead is explicitly not in the estimate; this asserts it stayed out."""
    for variant in payload["campaign"]["variants"]:
        assert variant["work_hours"] == pytest.approx(
            variant["capture_hours"] + variant["turn_hours"], rel=1e-9
        )


# -------------------------------------------------------------- sensitivity


def test_the_sensitivity_table_is_present_and_spans_the_required_range(payload):
    rows = payload["campaign"]["sensitivity"]
    assert rows, "no sensitivity table"
    scales = sorted(r["scale"] for r in rows)
    assert min(scales) <= 0.75, f"sweep starts at {min(scales)}; the brief requires -25%"
    assert max(scales) >= 1.50, f"sweep ends at {max(scales)}; the brief requires +50%"
    assert 1.0 in scales, "the baseline must appear in the sweep"
    for row in rows:
        assert row["days"] > 0
        assert row["work_hours"] > 0


def test_the_sensitivity_table_is_monotone_in_congestion(payload):
    rows = sorted(payload["campaign"]["sensitivity"], key=lambda r: r["scale"])
    days = [r["days"] for r in rows]
    assert days == sorted(days), days


def test_the_congestion_model_is_declared_in_the_artifact(payload):
    congestion = payload["congestion_model"]
    assert congestion["bands"], "no time-of-day bands declared"
    assert congestion["index"], "no per-class indices declared"
    for values in congestion["index"].values():
        assert all(v >= 1.0 for v in values.values()), "an index below 1.0 is a speed-up"


# ------------------------------------------------------ scope variants A/D/C


def test_all_three_scope_variants_are_reported(payload):
    variants = [r["variant"] for r in payload["campaign"]["variants"]]
    assert variants == list(C.STAGE2_SCOPE_VARIANTS)


def test_the_variants_are_ordered_by_how_much_they_include(payload):
    by_variant = {r["variant"]: r for r in payload["campaign"]["variants"]}
    assert (
        by_variant["A"]["required_km"]
        > by_variant["D"]["required_km"]
        > by_variant["C"]["required_km"]
    )
    assert by_variant["A"]["days"] > by_variant["D"]["days"] > by_variant["C"]["days"]


def test_variant_d_drops_exactly_the_spur_and_orphan_kilometres(arcs, payload):
    """D is `through` only, so what it removes must be spur + orphan, not something else."""
    summary = SR.summarise(arcs)["all_service"]
    dropped = sum(
        r["centerline_km"] for r in summary["rows"] if r["service_role"] != "through"
    )
    by_variant = {r["variant"]: r for r in payload["campaign"]["variants"]}
    delta = by_variant["A"]["required_km"] - by_variant["D"]["required_km"]
    # Not exact: removing spurs also strands a little of the street network.
    assert delta == pytest.approx(dropped, rel=0.02)


# --------------------------------------------------- non-goals were honoured


def test_stage_two_excluded_nothing(arcs):
    """The brief is explicit: do not exclude service roads, do not choose a variant."""
    stats = json.loads(C.STATS_JSON.read_text())
    assert int((~arcs["excluded"]).sum()) == stats["totals"]["included_arc_count"]


def test_no_arc_was_dropped_by_a_scope_variant_in_the_committed_artifact(arcs):
    assert not (arcs["exclusion_reason"] == "service_scope_variant").any()


def test_the_required_traversal_total_is_unchanged_from_stage_zero(arcs):
    from efficientroute import network as N

    stats = json.loads(C.STATS_JSON.read_text())
    included = arcs[~arcs["excluded"]]
    assert N.required_traversal_km(included) == pytest.approx(
        stats["headline"]["required_traversal_km"], rel=1e-9
    )


# ---------------------------------------------------------------- determinism


def test_the_columns_on_disk_are_reproduced_by_the_persisted_model(arcs):
    """CLAUDE.md rule 5, and the reason `rebuild_arc_table` can stay honest."""
    rebuilt = TM.augment(arcs.drop(columns=list(TM.STAGE2_COLUMNS)), TM.load_model())
    assert rebuilt["service_role"].tolist() == arcs["service_role"].tolist()
    for column in ("capture_speed_kmh", "capture_time_s"):
        assert rebuilt[column].to_numpy() == pytest.approx(
            arcs[column].to_numpy(), rel=1e-12
        )


def test_augmenting_twice_gives_the_same_answer(arcs):
    first = TM.augment(arcs)
    second = TM.augment(first)
    assert second["capture_time_s"].to_numpy() == pytest.approx(
        first["capture_time_s"].to_numpy(), rel=1e-12
    )


def test_the_persisted_model_round_trips(payload):
    from efficientroute.speedmodel import SpeedModel

    model = SpeedModel.from_dict(payload["speed_model"])
    assert SpeedModel.from_dict(model.to_dict()) == model


def test_the_artifact_records_the_hash_of_the_layer_it_wrote(payload):
    from efficientroute import extract as X

    assert payload["meta"]["arcs_sha256"] == X.file_digest(C.NETWORK_GPKG)


# --------------------------------------------------------------------- report


def test_the_report_exists_and_carries_the_tables_the_brief_asks_for(payload):
    if not C.TIME_REPORT_MD.exists():
        pytest.skip("report not generated — run `make stage2`")
    text = C.TIME_REPORT_MD.read_text()
    for needle in ("service_role", "sensitivity", "Deadhead", "daylight"):
        assert needle.lower() in text.lower(), f"the report never mentions {needle!r}"
    for variant in C.STAGE2_SCOPE_VARIANTS:
        assert f"| **{variant}**" in text, f"variant {variant} missing from the A/D/C table"


def test_the_report_states_that_congestion_is_an_assumption(payload):
    if not C.TIME_REPORT_MD.exists():
        pytest.skip("report not generated — run `make stage2`")
    text = C.TIME_REPORT_MD.read_text().lower()
    assert "no traffic data" in text
    assert "assumption" in text
