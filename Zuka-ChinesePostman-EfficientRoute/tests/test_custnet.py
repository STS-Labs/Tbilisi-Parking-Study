"""The customer street layer as a required set, on geometry small enough to check.

Everything here is asserted against a hand-built layer where the right answer is
known by inspection, not against Zone B — a test that reads a 347 km shapefile and
compares the result to what the code produced last time is a fixture, not a test.
"""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from efficientroute import config as C
from efficientroute import custnet
from efficientroute import extract as E
from efficientroute import network as N
from efficientroute import routeio

FIXTURE = Path(__file__).parent / "fixtures" / "mini.osm"
CLIP = box(44.79, 41.71, 44.81, 41.73)


def _layer(lines, tmp_path, crs=C.METRIC_CRS):
    path = tmp_path / "streets.shp"
    gpd.GeoDataFrame(geometry=[LineString(c) for c in lines], crs=crs).to_file(path)
    return path


class TestNoding:
    """A display layer's topology is a claim, not a fact. Measure it."""

    def test_a_t_junction_with_no_shared_vertex_is_noded(self, tmp_path):
        # The stem ends exactly on the interior of the crossbar. Visually a
        # junction; in the shapefile, two unrelated lines.
        path = _layer(
            [[(0, 0), (100, 0)], [(50, 0), (50, 80)]], tmp_path
        )
        out = custnet.node_layer(path)
        assert out["report"]["endpoints"]["attached_on_interior"] == 1
        # The crossbar is split at the touch point, so the stem's end is a node.
        assert out["report"]["pieces_out"] == 3

    def test_a_near_miss_inside_the_tolerance_is_snapped_shut(self, tmp_path):
        path = _layer(
            [[(0, 0), (100, 0)], [(50, 1.0), (50, 80)]], tmp_path
        )
        out = custnet.node_layer(path, snap_tolerance_m=2.0)
        assert out["report"]["endpoints"]["snapped"] == 1
        assert out["report"]["endpoints"]["unattached"] == 3
        assert out["report"]["pieces_out"] == 3

    def test_a_gap_wider_than_the_tolerance_stays_a_dead_end(self, tmp_path):
        path = _layer(
            [[(0, 0), (100, 0)], [(50, 9.0), (50, 80)]], tmp_path
        )
        out = custnet.node_layer(path, snap_tolerance_m=2.0)
        assert out["report"]["endpoints"]["snapped"] == 0
        # Both ends of the crossbar, both ends of the stem: nothing coincides.
        assert out["report"]["endpoints"]["unattached"] == 4
        assert out["report"]["pieces_out"] == 2

    def test_noding_does_not_lose_length(self, tmp_path):
        path = _layer(
            [[(0, 0), (100, 0)], [(50, 0), (50, 80)], [(0, 40), (100, 40)]], tmp_path
        )
        out = custnet.node_layer(path)
        assert out["report"]["length_out_km"] == pytest.approx(
            out["report"]["length_in_km"], abs=1e-6
        )


class TestCoverage:
    def test_tree_local_coverage_equals_the_dissolved_union(self):
        rng = np.random.default_rng(20260828)
        buffers = [
            Point(rng.uniform(0, 500), rng.uniform(0, 500)).buffer(20.0)
            for _ in range(60)
        ]
        lines = [
            LineString([(rng.uniform(0, 500), rng.uniform(0, 500)),
                        (rng.uniform(0, 500), rng.uniform(0, 500))])
            for _ in range(80)
        ]
        fast = custnet._covered_length(lines, buffers, C.METRIC_CRS)
        dissolved = unary_union(buffers)
        slow = np.array([line.intersection(dissolved).length for line in lines])
        assert np.abs(fast - slow).max() < 1e-6

    def test_an_arc_the_layer_does_not_cover_is_not_required(self, tmp_path):
        """The whole mechanism: requirement is `min_passes`, nothing else."""
        table = N.build_arc_table(E.extract_ways(FIXTURE, CLIP), sampler=None)
        one = table.iloc[[0]]
        network_path = tmp_path / "net.geojson"
        one[["geometry"]].to_file(network_path, driver="GeoJSON")

        required, fraction = custnet.required_arc_mask(
            table["geometry"].tolist(), network_path
        )
        assert required[0]
        assert fraction[0] == pytest.approx(1.0, abs=1e-6)
        # Its reverse twin shares the centreline, so it is required too; nothing
        # else in the fixture is.
        assert 1 <= required.sum() <= 2
        marked = N.build_arc_table(
            E.extract_ways(FIXTURE, CLIP), sampler=None, required_network=network_path
        )
        assert (marked.loc[~marked["in_required_area"], "min_passes"] == 0).all()
        assert (marked.loc[~marked["in_required_area"], "pair_requirement"] == 0).all()
        assert marked.loc[marked["in_required_area"], "min_passes"].max() >= 1

    def test_matching_ignores_arcs_the_car_may_not_drive(self):
        """A footway under a customer street is not OSM carrying that street."""
        table = N.build_arc_table(E.extract_ways(FIXTURE, CLIP), sampler=None)
        excluded = table[table["excluded"]]
        if excluded.empty:
            pytest.skip("the fixture has no excluded arcs to test against")
        pieces = gpd.GeoDataFrame(
            geometry=[excluded.geometry.iloc[0]], crs="EPSG:4326"
        )
        drivable, _, _ = custnet.coverage_fractions(pieces, table, drivable_only=True)
        everything, _, _ = custnet.coverage_fractions(pieces, table, drivable_only=False)
        assert everything[0] > drivable[0]


class TestStitching:
    def test_endpoints_shared_between_pieces_share_a_node_id(self):
        extract = E.extract_ways(FIXTURE, CLIP)
        # Two pieces meeting at a point far from anything OSM knows about.
        pieces = gpd.GeoDataFrame(
            geometry=[LineString([(0, 0), (0, 50)]), LineString([(0, 50), (60, 50)])],
            crs=C.METRIC_CRS,
        )
        out = custnet.synthesise_ways(pieces, extract, snap_m=15.0)
        ways = list(out["ways"].values())
        assert len(ways) == 2
        shared = set(ways[0].node_ids) & set(ways[1].node_ids)
        assert len(shared) == 1, "the meeting point must be one node, not two"
        assert all(way_id < 0 for way_id in out["ways"]), "synthetic ids are negative"

    def test_an_endpoint_near_an_osm_node_adopts_it(self):
        extract = E.extract_ways(FIXTURE, CLIP)
        node_id, lonlat = sorted(extract.node_lonlat.items())[0]
        anchor = gpd.GeoSeries([Point(*lonlat)], crs="EPSG:4326").to_crs(
            C.METRIC_CRS).iloc[0]
        pieces = gpd.GeoDataFrame(
            geometry=[LineString([(anchor.x, anchor.y),
                                  (anchor.x + 80.0, anchor.y + 80.0)])],
            crs=C.METRIC_CRS,
        )
        out = custnet.synthesise_ways(pieces, extract, snap_m=15.0)
        way = next(iter(out["ways"].values()))
        assert way.node_ids[0] in extract.node_lonlat, "the OSM node must be adopted"
        assert out["report"]["endpoints_snapped_to_osm"] >= 1

    def test_an_endpoint_far_from_osm_is_reported_not_dragged(self):
        extract = E.extract_ways(FIXTURE, CLIP)
        pieces = gpd.GeoDataFrame(
            geometry=[LineString([(0, 0), (0, 90)])], crs=C.METRIC_CRS
        )
        out = custnet.synthesise_ways(pieces, extract, snap_m=15.0)
        assert out["report"]["endpoints_not_snapped"] == 2
        assert out["report"]["endpoints_snapped_to_osm"] == 0

    def test_injection_is_logged_rather_than_silent(self):
        """CLAUDE.md rule 4 — nothing enters or leaves the network unexplained."""
        extract = E.extract_ways(FIXTURE, CLIP)
        pieces = gpd.GeoDataFrame(
            geometry=[LineString([(0, 0), (0, 90)])], crs=C.METRIC_CRS
        )
        out = custnet.synthesise_ways(pieces, extract, snap_m=15.0)
        before = len(extract.dropped_ways)
        custnet.augment(extract, out)
        added = extract.dropped_ways[before:]
        assert added and all(r["reason"] == "injected_customer_street" for r in added)

    def test_a_synthetic_id_collision_is_an_error_not_an_overwrite(self):
        extract = E.extract_ways(FIXTURE, CLIP)
        pieces = gpd.GeoDataFrame(
            geometry=[LineString([(0, 0), (0, 90)])], crs=C.METRIC_CRS
        )
        out = custnet.synthesise_ways(pieces, extract, snap_m=15.0)
        custnet.augment(extract, out)
        with pytest.raises(ValueError, match="collides"):
            custnet.augment(extract, out)

    def test_injected_arcs_are_two_way_residential_and_flagged(self, tmp_path):
        extract = E.extract_ways(FIXTURE, CLIP)
        _, lonlat = sorted(extract.node_lonlat.items())[0]
        anchor = gpd.GeoSeries([Point(*lonlat)], crs="EPSG:4326").to_crs(
            C.METRIC_CRS).iloc[0]
        pieces = gpd.GeoDataFrame(
            geometry=[LineString([(anchor.x, anchor.y),
                                  (anchor.x + 120.0, anchor.y)])],
            crs=C.METRIC_CRS,
        )
        synthesised = custnet.synthesise_ways(pieces, extract, snap_m=15.0)
        custnet.augment(extract, synthesised)

        # The flag column only exists where a required network is configured, which
        # is the only situation that can produce an injected arc in the first place.
        network_path = tmp_path / "net.geojson"
        synthesised["geometry"][["geometry"]].to_file(network_path, driver="GeoJSON")
        table = N.build_arc_table(extract, sampler=None,
                                  required_network=network_path)

        injected = table[table["way_id"] < 0]
        assert len(injected) == 2, "two-way means two directed arcs"
        assert set(injected["highway_class"]) == {"residential"}
        assert set(injected["oneway"]) == {"no"}
        assert injected["attributes_unverified"].all()
        assert not table.loc[table["way_id"] > 0, "attributes_unverified"].any()
        # And the customer's own line is what makes them required.
        assert injected["in_required_area"].all()

    def test_the_flag_column_appears_only_with_a_required_network(self):
        """Tbilisi's committed `arcs` layer must not grow a column it never had."""
        plain = N.build_arc_table(E.extract_ways(FIXTURE, CLIP), sampler=None)
        assert "attributes_unverified" not in plain.columns
        assert "required_coverage" not in plain.columns
        assert "in_required_area" not in plain.columns


class TestTurnSheet:
    """The flag has to reach the windscreen, and must not disturb a sheet without one."""

    @staticmethod
    def _day():
        return {"day": 1, "date": "2026-08-29", "zone": 0, "arc_traversals": 2,
                "route_h": 1.0, "break_h": 0.75, "day_h": 1.75,
                "capture_h": 0.5, "deadhead_h": 0.3, "turn_h": 0.2}

    @staticmethod
    def _steps():
        return [
            {"step": 0, "arc_id": "1:0:F", "is_capture": True, "turn": "straight",
             "lane_instruction": ""},
            {"step": 1, "arc_id": "-1:0:F", "is_capture": True, "turn": "left",
             "lane_instruction": ""},
        ]

    def _write(self, tmp_path, unverified):
        names = {"1:0:F": "Rustaveli", "-1:0:F": "New Street"}
        lengths = {"1:0:F": 120.0, "-1:0:F": 80.0}
        speeds = {"1:0:F": 30.0, "-1:0:F": 30.0}
        path = tmp_path / "day-01.md"
        routeio.write_day_sheet(path, self._day(), self._steps(), names, lengths,
                                speeds, unverified=unverified)
        return path.read_text()

    def test_no_unverified_arc_leaves_the_sheet_exactly_as_it_was(self, tmp_path):
        """A campaign with no customer geometry has a committed sheet to preserve."""
        text = self._write(tmp_path, None)
        assert "UNVERIFIED" not in text
        head, _ = text.split("| # | Street |", 1)
        # Exactly the spacing the sheet had before the flag existed: one blank line
        # between the preamble and the table, and no room made for a notice that is
        # not there.
        assert head.endswith("the camera is not counted.\n\n\n")
        assert "\n\n\n\n" not in text

    def test_an_unverified_arc_is_named_in_the_row_and_at_the_head(self, tmp_path):
        text = self._write(tmp_path, {"-1:0:F"})
        assert "1 arcs on this route are marked [UNVERIFIED]" in text
        assert "| New Street **[UNVERIFIED]** |" in text
        assert "| Rustaveli |" in text

    def test_an_unverified_run_is_never_folded_into_a_verified_one(self, tmp_path):
        """Folding hides the flag; a driver told nothing checks nothing."""
        names = {"a": "Same Street", "b": "Same Street"}
        steps = [
            {"step": 0, "arc_id": "a", "is_capture": True, "turn": "straight",
             "lane_instruction": ""},
            {"step": 1, "arc_id": "b", "is_capture": True, "turn": "straight",
             "lane_instruction": ""},
        ]
        path = tmp_path / "day-02.md"
        routeio.write_day_sheet(path, self._day(), steps, names,
                                {"a": 50.0, "b": 50.0}, {"a": 30.0, "b": 30.0},
                                unverified={"b"})
        rows = [line for line in path.read_text().splitlines()
                if line.startswith("| 1 |") or line.startswith("| 2 |")]
        assert len(rows) == 2, "the two arcs must stay separate rows"
        assert "UNVERIFIED" in rows[1] and "UNVERIFIED" not in rows[0]
