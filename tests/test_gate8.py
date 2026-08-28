"""Stage 8 gate. Every assertion is copied from `prompts/08-sequential-credit-and-joint-solve.md`.

The stage claims a saving, so the gate's job is to make the saving impossible to
fake. Three ways it could be fake, and one check for each:

  the streets were not actually filmed   -> I1, campaign-wide
  they were filmed too fast to count     -> I9, against the Stage 6 rule
  the slowdown was never paid for        -> I10

Plus I4, because a plan that saves an hour by running a ten-hour day has not saved
anything, and determinism, because a search that cannot be reproduced is not a plan.
"""
import json

import pytest

from efficientroute import config as C

pytestmark = pytest.mark.gate8

ARTIFACT = C.DERIVED / "08-sequential.json"


@pytest.fixture(scope="module")
def payload() -> dict:
    if not ARTIFACT.exists():
        pytest.skip(f"{ARTIFACT} not built — run `efficientroute stage8`")
    return json.loads(ARTIFACT.read_text())


@pytest.fixture(scope="module")
def adopted(payload) -> dict:
    tier = payload["adopted"]
    if tier == "0":
        pytest.skip("no tier beat the incumbent; nothing new to gate")
    return payload["tiers"][tier]


class TestCoverageIsReal:
    def test_i1_every_requirement_is_discharged_somewhere_in_the_campaign(self, adopted):
        """I1, restated campaign-wide.

        The per-day form is now wrong: a street filmed on day 3 that Stage 4 assigned
        to day 7 is covered, and asserting it was covered *on day 7* would fail a
        correct plan. What may never happen is a requirement nobody discharged at all.
        """
        assert adopted["undischarged_passes"] == 0

    def test_i9_every_credited_pass_would_count_as_a_driven_pass(self, adopted):
        """I9 — checked against `coverage.qualifies`, the rule Stage 6 applies to a
        real trace. If a planned pass would be rejected off a GPS log, crediting it
        here means the plan is banking coverage the campaign will not have."""
        assert adopted["i9_failures"] == []

    def test_the_credit_rule_is_the_stage_six_rule(self, payload):
        rule = payload["credit_rule"]
        assert rule["shared_with"].startswith("coverage.qualifies")
        assert rule["speed_max_kmh"] == C.COVERAGE_SPEED_MAX_KMH

    def test_the_shared_rule_really_is_one_function(self):
        """§1 asks for one implementation and two callers, so assert the caller."""
        import inspect

        from efficientroute import coverage, sequential

        assert "qualifies(" in inspect.getsource(coverage.ingest)
        assert "coverage.qualifies(" in inspect.getsource(sequential.check_i9)


class TestTheSavingWasPaidFor:
    def test_i10_credited_deadhead_passes_are_costed_at_capture_time(self, adopted):
        assert adopted["i10_ok"] is True

    def test_slowing_time_is_reported_not_hidden(self, adopted):
        assert adopted["slowing_h"] >= 0.0
        if adopted["bonus_passes"] > 0:
            assert "bonus_km" in adopted


class TestTheDayStillFits:
    def test_i4_no_day_exceeds_its_window(self, payload, adopted):
        assert adopted["days_over_window"] == 0
        window = C.SHIFT_WINDOWS[C.DEFAULT_SHIFT_WINDOW]
        window_h = window[1] - window[0]
        for day in payload["days"]:
            assert day["day_h"] <= window_h + 1e-6, day

    def test_every_day_has_a_date_and_they_run_consecutively(self, payload):
        import datetime as dt

        dates = [dt.date.fromisoformat(d["date"]) for d in payload["days"]]
        assert dates == sorted(dates)
        for earlier, later in zip(dates, dates[1:]):
            assert (later - earlier).days == 1


class TestItNeverShipsAWorsePlan:
    def test_the_adopted_tier_beats_the_incumbent(self, payload, adopted):
        """§3's ratchet: adopt only on a strict win, fewer days first."""
        from efficientroute import sequential

        assert sequential.better(adopted, payload["baseline"])

    def test_tier_one_cannot_lose(self, payload):
        """Tier 1 gives each day a subset of the work Stage 5 gave it and refuses any
        credit that would break the window, so it cannot come out worse."""
        if "1" not in payload["tiers"]:
            pytest.skip("tier 1 not run")
        tier1, base = payload["tiers"]["1"], payload["baseline"]
        assert tier1["days"] <= base["days"]
        assert tier1["route_h"] <= base["route_h"] + 1e-6

    def test_the_artifact_records_the_network_it_was_built_from(self, payload):
        from efficientroute import extract as X

        assert payload["meta"]["arcs_sha256"] == X.file_digest(C.NETWORK_GPKG)
