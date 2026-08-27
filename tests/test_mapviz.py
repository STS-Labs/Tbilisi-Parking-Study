"""The interactive map. Folium renders children in order, and getting that order
wrong produces a page that looks fine (legend, tiles) with an empty map and a
single console error — so the ordering is worth an assertion."""
import json
import re
from pathlib import Path

import pytest
from shapely.geometry import box

from efficientroute import extract as E
from efficientroute import mapviz
from efficientroute import network as N
from efficientroute import stats as S

FIXTURE = Path(__file__).parent / "fixtures" / "mini.osm"
CLIP = box(44.79, 41.71, 44.81, 41.73)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    ex = E.extract_ways(FIXTURE, CLIP)
    ex.boundary_wkb = CLIP.buffer(-0.002).wkb
    ex.clip_wkb = CLIP.wkb
    table = N.build_arc_table(ex, sampler=None)
    summary = S.compute(table, ex, meta={})
    out = tmp_path_factory.mktemp("map") / "map.html"
    mapviz.write(table, ex, summary, out)
    return out.read_text()


def test_layer_script_runs_after_the_map_is_created(rendered):
    map_decl = re.search(r"var (map_\w+) = L\.map\(", rendered)
    assert map_decl, "folium did not emit a map variable"
    assert rendered.index(map_decl.group(0)) < rendered.index("var lines ="), (
        "the layer script is emitted before the map variable exists — every "
        "addTo() will throw 'Cannot read properties of undefined'"
    )


def test_layer_script_references_the_real_map_variable(rendered):
    map_name = re.search(r"var (map_\w+) = L\.map\(", rendered).group(1)
    tail = rendered[rendered.index("var lines =") :]
    assert f"addTo({map_name})" in tail


def test_every_polyline_is_inside_the_clip(rendered):
    lines = json.loads(re.search(r"var lines = (\{.*?\});", rendered, re.S).group(1))
    minx, miny, maxx, maxy = CLIP.bounds
    for group in lines.values():
        for coords in group:
            assert len(coords) >= 2
            for lat, lon in coords:
                assert miny - 1e-6 <= lat <= maxy + 1e-6
                assert minx - 1e-6 <= lon <= maxx + 1e-6


def test_excluded_and_orphan_layers_are_present_and_distinct(rendered):
    styles = json.loads(re.search(r"var styles = (\{.*?\});", rendered, re.S).group(1))
    assert styles["excluded"]["dashArray"]
    assert styles["orphan"]["color"] != styles["passes1"]["color"]
    assert styles["passes2"]["color"] != styles["passes1"]["color"]
