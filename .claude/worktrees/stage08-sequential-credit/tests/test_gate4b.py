"""Stage 4b gate.

Stage 4b's job is to replace two estimates with measurements and to dispose of a
coverage gap. The assertions below are about whether it actually did that, not
about whether the answer came out a particular way — the numbers are inputs to a
decision this stage does not take.
"""
import json

import pytest

from efficientroute import config as C

pytestmark = pytest.mark.gate4b


@pytest.fixture(scope="module")
def payload() -> dict:
    if not C.RECHECK_JSON.exists():
        pytest.skip(f"{C.RECHECK_JSON} not built — run `make stage4b`")
    return json.loads(C.RECHECK_JSON.read_text())


# ------------------------------------------------- item 1: D was measured


def test_both_variants_were_run_through_the_full_pipeline(payload):
    """Not scaled from one another — scaling is the error that caused this stage."""
    recheck = payload["item1_variant_recheck"]
    assert set(recheck) == {"C", "D"}
    for variant, block in recheck.items():
        assert block["segments"] > 0, variant
        assert block["capture_hours"] > 0, variant
        for window in block["windows"].values():
            assert window["days"] > 0
            assert window["leg_hours"] > 0, "legs must be routed, not assumed"


def test_variant_d_has_its_own_measured_legs_and_overhead(payload):
    """If either were carried across from C they would be identical."""
    recheck = payload["item1_variant_recheck"]
    assert recheck["D"]["overhead"] != recheck["C"]["overhead"]
    assert (
        recheck["D"]["windows"]["10h"]["leg_hours"]
        != recheck["C"]["windows"]["10h"]["leg_hours"]
    )


def test_variant_d_carries_more_work_than_c(payload):
    recheck = payload["item1_variant_recheck"]
    assert recheck["D"]["capture_hours"] > recheck["C"]["capture_hours"]
    assert recheck["D"]["segments"] > recheck["C"]["segments"]
    assert recheck["D"]["windows"]["10h"]["days"] > recheck["C"]["windows"]["10h"]["days"]


def test_the_decision_table_states_a_margin_against_the_daylight_limit(payload):
    inputs = payload["decision_inputs"]
    assert inputs["daylight_limit"]
    for variant, rows in inputs["variants"].items():
        for window, row in rows.items():
            assert isinstance(row["fits"], bool), (variant, window)
            assert row["margin_days"] == row["margin_days"]  # not NaN


def test_a_plan_that_fits_finishes_on_or_before_the_limit(payload):
    import datetime as dt

    limit = dt.date.fromisoformat(payload["decision_inputs"]["daylight_limit"])
    for rows in payload["decision_inputs"]["variants"].values():
        for row in rows.values():
            finish = dt.date.fromisoformat(row["finish"])
            assert row["fits"] == (finish <= limit)


def test_no_plan_is_daylight_limited(payload):
    """Every campaign here finishes before the taper starts; if one did not, the
    zone plan would have been built against a window it does not have."""
    for block in payload["item1_variant_recheck"].values():
        for window in block["windows"].values():
            assert window["taper_hours"] == pytest.approx(0.0)


# --------------------------------------------- item 2: the trap disposition


def test_every_trapped_arc_is_attributed_to_a_cause(payload):
    disposition = payload["item2_trap_disposition"]["disposition"]
    total = sum(v["arcs"] for v in disposition["by_cause"].values())
    assert total == disposition["trapped_arcs"]
    assert "unknown" not in disposition["by_cause"]


def test_the_cause_split_sums_to_the_trapped_kilometres(payload):
    disposition = payload["item2_trap_disposition"]["disposition"]
    assert sum(v["km"] for v in disposition["by_cause"].values()) == pytest.approx(
        disposition["trapped_km"], rel=1e-9
    )
    assert sum(v["fast_km"] for v in disposition["by_cause"].values()) == pytest.approx(
        disposition["fast_trapped_km"], rel=1e-9
    )


def test_the_u_turn_policy_is_ruled_out_for_the_fast_network(payload):
    """The brief raised it as a candidate; SPEC §3.3 gives those classes no U-turn
    edges at all, so it cannot be stranding them."""
    causes = payload["item2_trap_disposition"]["disposition"]["by_cause"]
    assert causes.get("u_turn_policy", {}).get("fast_km", 0.0) == pytest.approx(0.0)


def test_the_fix_only_adds_manoeuvres(payload):
    fix = payload["item2_trap_disposition"]["fix"]
    assert fix["narrowed"]["edges"] > fix["as_built"]["edges"]
    assert fix["narrowed"]["edges"] - fix["as_built"]["edges"] == fix["edges_added"]
    assert fix["edges_added"] == len(fix["added_manoeuvres"])


def test_the_fix_recovers_reachability_and_never_loses_it(payload):
    fix = payload["item2_trap_disposition"]["fix"]
    assert fix["narrowed"]["tourable_nodes"] >= fix["as_built"]["tourable_nodes"]
    assert fix["narrowed"]["trapped_km"] <= fix["as_built"]["trapped_km"]
    assert fix["km_recovered"] == pytest.approx(
        fix["as_built"]["trapped_km"] - fix["narrowed"]["trapped_km"], rel=1e-9
    )


def test_every_added_manoeuvre_enters_a_mainline(payload):
    """The narrowing is about mainline entry; anything else would be a wider change."""
    for row in payload["item2_trap_disposition"]["fix"]["added_manoeuvres"]:
        assert row["to_class"] in C.MAINLINE_ENTRY_VIA_RAMPS_ONLY, row
        assert not row["from_class"].endswith("_link"), row


def test_invariant_u1_holds_after_the_fix(payload):
    u1 = payload["item2_trap_disposition"]["fix"]["u1"]
    assert u1["holds"], u1["violating"]
    assert u1["violations"] == 0
    assert u1["checked"] == payload["item2_trap_disposition"]["fix"]["edges_added"]
    assert u1["forbidden_pairs_in_source"] > 0, "the check must have something to check against"


def test_the_fix_was_proposed_here_and_adopted_by_decision(payload):
    """Stage 4b left it off — a proposal with a measurement attached, not a change
    made in passing. `DECISION-schedule.md` adopted it on 26 Aug under SPEC §1.1,
    before Stage 5, because it changes L(G) and therefore every route.

    The assertion moves with the decision: what Stage 4b owns is that the fix was
    measured and U1-checked, which the rest of this file still asserts.
    """
    assert C.MAINLINE_ENTRY_FALLBACK_WHERE_NO_RAMP is True
    assert payload["item2_trap_disposition"]["fix"]["u1"]["holds"]


# ----------------------------------------- item 3: the allowance profiles


def test_both_allowance_profiles_are_reported_for_both_variants(payload):
    profiles = payload["item3_allowance_profiles"]
    assert set(profiles) == {"C", "D"}
    for block in profiles.values():
        assert {"fewest_days", "reserved", "delta"} <= set(block)


def test_the_profiles_are_actually_different_settings(payload):
    for block in payload["item3_allowance_profiles"].values():
        assert block["reserved"]["allowance"] > block["fewest_days"]["allowance"]


def test_reserving_room_costs_days_and_saves_hours(payload):
    """The trade the brief asked to be priced, on each variant's own numbers."""
    for variant, block in payload["item3_allowance_profiles"].items():
        delta = block["delta"]
        assert delta["extra_days"] >= 1, variant
        assert delta["hours_saved"] > 0, variant
        assert delta["extra_commute_capture_h"] > 0, variant


def test_the_delta_matches_the_two_profiles(payload):
    for block in payload["item3_allowance_profiles"].values():
        assert block["delta"]["hours_saved"] == pytest.approx(
            block["fewest_days"]["total_hours"] - block["reserved"]["total_hours"], rel=1e-9
        )


def test_the_reserved_profile_was_measured_and_then_suspended(payload):
    """Stage 4b switched the default to reserve room for a productive depot leg,
    on the measurement in `item3_allowance_profiles`.

    **Stage 5 withdrew it.** Reserving room only pays if the leg is productive,
    and Stage 5's routes do not capture on the commute — see
    `CAPTURE_ON_COMMUTE_IN_SIZING`. The measurement below still stands; what
    changed is whether its premise holds, so the allowance is back to zero and
    this test asserts the reason rather than the old number.
    """
    profiles = payload["item3_allowance_profiles"]
    for block in profiles.values():
        assert block["delta"]["hours_saved"] > 0, "the measurement itself still stands"
    assert C.COMMUTE_ALLOWANCE == pytest.approx(0.0)
    assert C.CAPTURE_ON_COMMUTE_IN_SIZING is False
    assert C.ZONE_PREFER_FEWEST_DAYS is False


def test_the_committed_stage4_plan_uses_the_current_default(payload):
    if not C.ZONES_JSON.exists():
        pytest.skip("Stage 4 not built")
    stage4 = json.loads(C.ZONES_JSON.read_text())
    assert stage4["commute_allowance"] == pytest.approx(C.COMMUTE_ALLOWANCE)


# ------------------------------------------------------------- boundaries


def test_the_scope_variant_was_not_changed_by_this_stage(payload):
    """The numbers are here; the decision is not this stage's to take."""
    assert payload["current_scope_variant"] == C.SCOPE_VARIANT


def test_alternatives_wrote_beside_the_committed_plan_not_over_it(payload):
    canonical = C.stage4_paths(C.SCOPE_VARIANT)
    for variant in ("C", "D"):
        for tag in ("-fewestdays", "-reserved"):
            paths = C.stage4_paths(variant, tag)
            assert paths["json"] != canonical["json"]
            assert paths["gpkg"] != canonical["gpkg"]


def test_the_artifact_records_the_network_it_was_built_from(payload):
    from efficientroute import extract as X

    assert payload["meta"]["arcs_sha256"] == X.file_digest(C.NETWORK_GPKG)
