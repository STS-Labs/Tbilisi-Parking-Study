"""Stage 4 items 3–5 — sequencing, commute capture, daylight taper."""
import datetime as dt

import numpy as np
import pytest
import toygraph

from efficientroute import config as C
from efficientroute import depotlegs, schedule, zoning


class TestSequence:
    def test_far_zones_come_first(self):
        """SPEC §7.1 mitigation 2 — counter-intuitive, and easy to get backwards."""
        zones = np.array([0, 1, 2, 3])
        legs = np.array([100.0, 900.0, 400.0, 50.0])
        assert schedule.sequence_far_first(zones, legs).tolist() == [1, 2, 0, 3]

    def test_the_order_is_strictly_descending_in_leg_cost(self):
        rng = np.random.default_rng(20260825)
        zones = np.arange(20)
        legs = rng.uniform(0, 1000, 20)
        order = schedule.sequence_far_first(zones, legs)
        ordered = legs[order]
        assert (np.diff(ordered) <= 0).all()

    def test_ties_break_on_zone_id_so_the_order_is_reproducible(self):
        zones = np.array([7, 2, 5])
        legs = np.array([100.0, 100.0, 100.0])
        assert schedule.sequence_far_first(zones, legs).tolist() == [2, 5, 7]

    def test_it_is_not_ascending(self):
        """The mistake this rule exists to prevent."""
        zones = np.array([0, 1])
        legs = np.array([10.0, 1000.0])
        assert schedule.sequence_far_first(zones, legs)[0] == 1


def toy_campaign(window="10h", start=dt.date(2026, 8, 25), n=6, capture=1200.0, **kw):
    """A ring of six streets split into three zones, all reachable from arc 0."""
    graph, zg = toygraph.zone_ring(n, capture_s=capture)
    deadhead = np.full(n, 60.0)
    capture_s = np.full(n, capture)
    field = depotlegs.leg_field(graph, deadhead, 0, "0:0:F", 0.0)
    labels = np.array([0, 0, 1, 1, 2, 2])
    traversals = np.ones(n, dtype="int64")
    required = np.ones(n, dtype=bool)
    return schedule.build(
        graph, zg, labels, field, capture_s, deadhead, required, traversals,
        overhead=1.0, window_name=window, start_date=start, **kw
    )


class TestCampaign:
    def test_one_day_per_zone(self):
        campaign = toy_campaign()
        assert len(campaign.days) == 3
        assert sorted(d.zone for d in campaign.days) == [0, 1, 2]

    def test_days_run_on_consecutive_dates(self):
        campaign = toy_campaign(start=dt.date(2026, 9, 1))
        assert [d.date for d in campaign.days] == [
            dt.date(2026, 9, 1), dt.date(2026, 9, 2), dt.date(2026, 9, 3)
        ]

    def test_the_sequence_is_descending_in_baseline_leg_cost(self):
        campaign = toy_campaign()
        legs = [d.leg_baseline_h for d in campaign.days]
        assert legs == sorted(legs, reverse=True)

    def test_a_day_is_capture_times_overhead_plus_legs_plus_break(self):
        campaign = toy_campaign(capture_on_commute=False)
        day = campaign.days[0]
        assert day.total_h == pytest.approx(
            day.work_h + day.leg_out_h + day.leg_back_h + day.break_h
        )

    def test_every_required_arc_is_captured_exactly_once_across_the_campaign(self):
        campaign = toy_campaign(capture_on_commute=False)
        total = sum(d.capture_h for d in campaign.days)
        assert total == pytest.approx(6 * 1200.0 / 3600.0)

    def test_commute_capture_does_not_create_work_out_of_nothing(self):
        """Whatever the legs pick up must come out of a zone, not be added twice."""
        plain = toy_campaign(capture_on_commute=False)
        routed = toy_campaign(capture_on_commute=True)
        plain_total = sum(d.capture_h for d in plain.days)
        routed_total = sum(d.capture_h for d in routed.days) + routed.commute_capture_h
        assert routed_total == pytest.approx(plain_total)

    def test_slack_is_the_window_minus_the_day(self):
        campaign = toy_campaign()
        for day in campaign.days:
            assert day.slack_h == pytest.approx(day.available_h - day.total_h)

    def test_a_day_that_fits_reports_that_it_fits(self):
        campaign = toy_campaign()
        assert all(d.fits for d in campaign.days)

    def test_the_summary_matches_the_day_table(self):
        campaign = toy_campaign()
        payload = campaign.to_dict()
        assert payload["days"] == len(payload["day_table"])
        assert payload["total_hours"] == pytest.approx(
            sum(r["total_h"] for r in payload["day_table"])
        )


class TestTaper:
    def test_a_summer_campaign_loses_nothing(self):
        campaign = toy_campaign(start=dt.date(2026, 8, 25))
        assert campaign.taper_hours == pytest.approx(0.0)
        assert campaign.first_tapered_day is None

    def test_a_november_campaign_loses_the_tail_of_each_day(self):
        campaign = toy_campaign(start=dt.date(2026, 11, 10))
        assert campaign.taper_hours > 0.0
        assert campaign.first_tapered_day is not None

    def test_the_available_window_is_capped_by_sunset(self):
        campaign = toy_campaign(start=dt.date(2026, 12, 1))
        for day in campaign.days:
            assert day.available_h <= 10.0
            assert day.usable_end_h <= 18.0

    def test_taper_is_reported_per_day_not_just_in_total(self):
        campaign = toy_campaign(start=dt.date(2026, 11, 10))
        assert sum(d.taper_h for d in campaign.days) == pytest.approx(campaign.taper_hours)


class TestWindows:
    def test_the_nine_hour_window_starts_an_hour_later(self):
        nine = toy_campaign(window="9h")
        ten = toy_campaign(window="10h")
        assert nine.days[0].window_start_h == 9.0
        assert ten.days[0].window_start_h == 8.0
        assert nine.days[0].available_h < ten.days[0].available_h

    def test_both_windows_end_at_the_same_hour(self):
        assert C.SHIFT_WINDOWS["9h"][1] == C.SHIFT_WINDOWS["10h"][1] == 18.0


class TestDeterminism:
    def test_two_builds_agree(self):
        a = toy_campaign().to_dict()
        b = toy_campaign().to_dict()
        assert a == b
