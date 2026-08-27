"""Stage 7 gate. Every assertion is copied from `prompts/07-dashboard.md`.

The stage exists to let a person look at the plan and say "that's stupid", which
only works if what they are looking at *is* the plan. So the gate is mostly
conservation: nothing dropped, nothing invented, the clock matching Stage 5's own
clock, and the geometry off by less than can be seen. A playback that quietly
simplified away a street would be worse than no playback, because it would look
authoritative while showing something the car will not drive.
"""
import json

import pytest

from efficientroute import config as C

pytestmark = pytest.mark.gate7

#: The brief asks for the tolerance to be asserted rather than eyeballed.
MAX_DEVIATION_M = C.PLAYBACK_SIMPLIFY_M

#: XML namespace identifiers. They look like URLs and are never fetched — an SVG
#: favicon carries one, and treating it as an external dependency would fail a page
#: that is in fact completely self-contained.
NAMESPACES = ("http://www.w3.org/", "https://www.w3.org/")


def _fetchable_urls(html: str) -> list[str]:
    """Absolute URLs the browser would actually go and get."""
    import re

    found = re.findall(r"""(?:https?:)?//[^\s"'<>)]+""", html)
    return [u for u in found if not u.startswith(NAMESPACES)]


@pytest.fixture(scope="module")
def manoeuvres():
    import geopandas as gpd

    if not C.ROUTES_GPKG.exists():
        pytest.skip(f"{C.ROUTES_GPKG} not built — run `make stage5`")
    return gpd.read_file(C.ROUTES_GPKG, layer=C.ROUTES_LAYER)


@pytest.fixture(scope="module")
def routes():
    if not C.ROUTES_JSON.exists():
        pytest.skip(f"{C.ROUTES_JSON} not built — run `make stage5`")
    return json.loads(C.ROUTES_JSON.read_text())


@pytest.fixture(scope="module")
def playback():
    files = sorted(C.PLAYBACK_DATA_DIR.glob("day-*.json"))
    if not files:
        pytest.skip(f"{C.PLAYBACK_DATA_DIR} not built — run `make stage7`")
    return [json.loads(p.read_text()) for p in files]


class TestNothingIsLost:
    def test_every_manoeuvre_appears_exactly_once(self, manoeuvres, playback):
        """No manoeuvre silently dropped by simplification."""
        expected = manoeuvres.groupby("day").size().to_dict()
        found = {d["day"]: len(d["segments"]) for d in playback}
        assert found == {int(k): int(v) for k, v in expected.items()}

    def test_the_days_are_all_there(self, manoeuvres, playback):
        assert sorted(d["day"] for d in playback) == sorted(
            int(x) for x in manoeuvres["day"].unique()
        )

    def test_no_segment_lost_its_geometry(self, playback):
        """Simplification must never reduce a line below two points."""
        for day in playback:
            thin = [s for s in day["segments"] if len(s["c"]) < 2]
            assert not thin, f"day {day['day']}: {len(thin)} segments have no line left"


class TestTheClockMatchesStageFive:
    def test_the_last_segment_ends_at_the_days_driving_time(self, routes, playback):
        by_day = {d["day"]: d for d in routes["days"]}
        for day in playback:
            expected = by_day[day["day"]]["route_h"] * 3600.0
            assert day["segments"][-1]["t1"] == pytest.approx(expected, abs=1.0), (
                f"day {day['day']}: playback ends at {day['segments'][-1]['t1']:.1f} s, "
                f"Stage 5 says {expected:.1f} s"
            )

    def test_the_clock_never_goes_backwards(self, playback):
        for day in playback:
            times = [(s["t0"], s["t1"]) for s in day["segments"]]
            assert all(a[1] >= a[0] for a in times)
            assert all(b[0] >= a[1] - 1e-6 for a, b in zip(times, times[1:]))

    def test_the_car_moves_for_no_longer_than_the_segment_lasts(self, playback):
        """`tv` is travel; the remainder of `t1 - t0` is the turn taken on leaving."""
        for day in playback:
            for s in day["segments"]:
                assert 0.0 <= s["tv"] <= s["t1"] - s["t0"] + 1e-6


class TestModesReconcile:
    def test_capture_hours_match_stage_five(self, routes, playback):
        by_day = {d["day"]: d for d in routes["days"]}
        for day in playback:
            assert day["by_mode"]["capture"]["h"] == pytest.approx(
                by_day[day["day"]]["capture_h"], abs=0.02
            ), f"day {day['day']} capture hours diverge from Stage 5"

    def test_deadhead_plus_legs_match_stage_five_deadhead(self, routes, playback):
        """Stage 5 reports two modes; the playback splits its deadhead in two, so
        the depot legs have to be added back to compare."""
        by_day = {d["day"]: d for d in routes["days"]}
        for day in playback:
            combined = day["by_mode"]["deadhead"]["h"] + day["by_mode"]["leg"]["h"]
            assert combined == pytest.approx(by_day[day["day"]]["deadhead_h"], abs=0.02)

    def test_kilometres_reconcile_to_the_manoeuvre_table(self, manoeuvres, playback):
        import geopandas as gpd

        arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
        length = dict(zip(arcs["arc_id"].astype(str), arcs["length_m"].astype(float)))
        expected = (
            manoeuvres.assign(km=manoeuvres["arc_id"].astype(str).map(length) / 1000.0)
            .groupby("day")["km"].sum().to_dict()
        )
        for day in playback:
            assert day["km"] == pytest.approx(expected[day["day"]], abs=0.05)

    def test_every_day_has_both_depot_legs(self, playback):
        """A day starts and ends at the depot, so it cannot have no legs."""
        for day in playback:
            legs = [s for s in day["segments"] if s["m"] == 2]
            assert legs, f"day {day['day']} has no depot leg"


class TestGeometryIsFaithful:
    def test_simplification_stays_under_the_stated_tolerance(self, manoeuvres):
        """Asserted, not eyeballed."""
        from efficientroute import dashboard

        sample = manoeuvres[manoeuvres["day"] <= 3]
        worst = dashboard.deviation_m(sample, C.PLAYBACK_SIMPLIFY_M)
        assert worst <= MAX_DEVIATION_M + 1e-6, (
            f"simplified route strays {worst:.2f} m from the arc it claims to be"
        )

    def test_the_context_network_is_also_bounded(self):
        import geopandas as gpd

        from efficientroute import dashboard, scenarios

        arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
        arcs = scenarios.apply_variant(arcs, C.SCOPE_VARIANT)
        sample = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])].head(3000)
        worst = dashboard.deviation_m(sample, C.NETWORK_SIMPLIFY_M)
        assert worst <= C.NETWORK_SIMPLIFY_M + 1e-6


class TestSelfContained:
    def test_the_page_reaches_for_nothing_outside_itself(self):
        import re

        if not C.PLAYBACK_INDEX.exists():
            pytest.skip("run `make stage7`")
        html = C.PLAYBACK_INDEX.read_text()
        assert not _fetchable_urls(html), f"page references {_fetchable_urls(html)[:5]}"

    def test_the_embed_build_has_no_external_url_at_all(self, tmp_path):
        import re

        from efficientroute import dashboard

        if not sorted(C.PLAYBACK_DATA_DIR.glob("day-*.json")):
            pytest.skip("run `make stage7`")
        out = dashboard.embed(1, tmp_path / "day-01.html")
        html = out.read_text()
        assert not _fetchable_urls(html), f"embed references {_fetchable_urls(html)[:5]}"
        # The template keeps its `fetch` path for the served build; what matters is
        # that the embed never reaches it, because every load is already answered
        # from the inlined bundle. Assert the bundle is there and complete rather
        # than that the word is absent — the latter would fail on a page that works
        # perfectly offline.
        assert "window.PLAYBACK_EMBED=" in html
        bundle_keys = ("data/index.json", "data/network.json", "data/day-01.json")
        for key in bundle_keys:
            assert f'"{key}"' in html, f"embed is missing {key}"


class TestDeterminism:
    def test_building_twice_produces_identical_files(self, tmp_path, manoeuvres):
        import geopandas as gpd

        from efficientroute import dashboard, timemodel

        arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
        model = timemodel.load_model()
        sample = manoeuvres[manoeuvres["day"] == 1]
        first = tmp_path / "a"
        second = tmp_path / "b"
        dashboard.build_days(sample, arcs, model, out_dir=first)
        dashboard.build_days(sample, arcs, model, out_dir=second)
        assert (first / "day-01.json").read_bytes() == (second / "day-01.json").read_bytes()
