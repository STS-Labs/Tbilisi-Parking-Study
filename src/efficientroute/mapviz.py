"""Render `reports/00-network.html`.

Written as compact Leaflet polyline arrays rather than embedded GeoJSON: at
Tbilisi's scale a GeoJSON FeatureCollection with per-feature style objects runs
to hundreds of megabytes, while a nested coordinate array of the same network is
a few tens.  Rendering goes through the canvas renderer for the same reason —
tens of thousands of SVG paths will not pan.
"""

from __future__ import annotations

import json
from pathlib import Path

import folium
import pandas as pd
from branca.element import Element, MacroElement, Template

from . import config as C

#: ~1.1 m at this latitude — below the positional accuracy of the source data,
#: so simplification cannot move a street off its centreline in a visible way.
SIMPLIFY_TOLERANCE_DEG = 1e-5
COORD_PRECISION = 5

class _NetworkLayers(MacroElement):
    """Emit the polyline layers *after* folium has declared the map variable.

    Anything added straight to `Figure.script` is written out before the map
    exists, so every `addTo()` throws and the page renders as an empty canvas
    under a perfectly good legend.  A MacroElement appends its script during the
    parent's render pass instead, which is the order we need.  The JavaScript is
    carried as an attribute rather than inlined in the template so Jinja never
    parses the embedded JSON.
    """

    _template = Template("{% macro script(this, kwargs) %}{{ this.body }}{% endmacro %}")

    def __init__(self, body: str) -> None:
        super().__init__()
        self.body = body


STYLES: dict[str, dict] = {
    "passes1": {"label": "Required — 1 pass", "color": "#1f6feb", "weight": 1.6, "opacity": 0.85},
    "passes2": {"label": "Required — 2 passes", "color": "#d1242f", "weight": 2.4, "opacity": 0.95},
    "passes3": {"label": "Required — 3+ passes", "color": "#8250df", "weight": 3.0, "opacity": 0.95},
    "excluded": {"label": "Excluded (not drivable)", "color": "#8c959f", "weight": 1.2, "opacity": 0.55, "dashArray": "3,4"},
    "bridge": {"label": "Bridge arcs (span two components)", "color": "#bf8700", "weight": 2.6, "opacity": 0.95},
    "orphan": {"label": "Orphan fragments (outside largest SCC)", "color": "#e3008c", "weight": 3.2, "opacity": 1.0},
}


def _lines(frame: pd.DataFrame, dedupe: bool = True) -> list:
    """Leaflet-ready [[lat, lon], ...] arrays, simplified and rounded."""
    if dedupe:
        frame = frame.drop_duplicates(subset=["way_id", "seg_index"])
    out = []
    for geometry in frame.geometry:
        simplified = geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=False)
        coords = list(simplified.coords) or list(geometry.coords)
        out.append([[round(lat, COORD_PRECISION), round(lon, COORD_PRECISION)] for lon, lat in coords])
    return out


def write(table, extract, summary: dict, path: Path = C.REPORT_HTML) -> Path:
    included = table[~table["excluded"]]
    routable = included[included["in_largest_scc"]]

    data: dict[str, list] = {
        "passes1": _lines(routable[routable["min_passes"] == 1]),
        "passes2": _lines(routable[routable["min_passes"] == 2]),
        "passes3": _lines(routable[routable["min_passes"] >= 3]),
        "excluded": _lines(table[table["excluded"]]),
        "bridge": _lines(included[included["scc_id"] == -1]),
        "orphan": _lines(included[included["scc_id"] > 0]),
    }

    boundary = extract.boundary
    clip = extract.clip
    centre = boundary.centroid

    fmap = folium.Map(
        location=[centre.y, centre.x],
        zoom_start=12,
        tiles="cartodbpositron",
        prefer_canvas=True,
        control_scale=True,
    )

    folium.GeoJson(
        boundary.__geo_interface__,
        name="Municipality boundary",
        style_function=lambda _: {"color": "#24292f", "weight": 2, "fill": False},
    ).add_to(fmap)
    folium.GeoJson(
        clip.__geo_interface__,
        name=f"Clip = boundary + {C.CLIP_BUFFER_M:.0f} m",
        style_function=lambda _: {"color": "#57606a", "weight": 1, "dashArray": "6,6", "fill": False},
    ).add_to(fmap)
    folium.Marker(
        [C.DEPOT_LAT, C.DEPOT_LON],
        tooltip="Depot (SPEC §5)",
        icon=folium.Icon(color="darkblue", icon="home", prefix="fa"),
    ).add_to(fmap)

    map_var = fmap.get_name()
    payload = json.dumps(data, separators=(",", ":"))
    styles = json.dumps(
        {key: {k: v for k, v in style.items() if k != "label"} for key, style in STYLES.items()},
        separators=(",", ":"),
    )
    labels = json.dumps({key: style["label"] for key, style in STYLES.items()})
    counts = json.dumps({key: len(value) for key, value in data.items()})

    script = f"""
        (function() {{
          var lines = {payload};
          var styles = {styles};
          var labels = {labels};
          var counts = {counts};
          var overlays = {{}};
          var order = ["passes1","passes2","passes3","excluded","bridge","orphan"];
          order.forEach(function(key) {{
            if (!lines[key] || !lines[key].length) {{ return; }}
            var group = L.layerGroup();
            lines[key].forEach(function(coords) {{
              L.polyline(coords, styles[key]).addTo(group);
            }});
            group.addTo({map_var});
            overlays[labels[key] + " (" + counts[key].toLocaleString() + ")"] = group;
          }});
          L.control.layers(null, overlays, {{collapsed: false, position: "topright"}}).addTo({map_var});
        }})();
    """
    fmap.add_child(_NetworkLayers(script))
    fmap.get_root().html.add_child(Element(_legend(summary)))

    path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(path))
    return path


def _legend(summary: dict) -> str:
    headline = summary["headline"]
    scc = summary["scc"]
    rows = "".join(
        f'<div><span style="display:inline-block;width:22px;height:0;'
        f'border-top:3px {"dashed" if style.get("dashArray") else "solid"} {style["color"]};'
        f'vertical-align:middle;margin-right:6px"></span>{style["label"]}</div>'
        for style in STYLES.values()
    )
    return f"""
    <div style="position:fixed;bottom:18px;left:18px;z-index:9999;background:rgba(255,255,255,.94);
                border:1px solid #d0d7de;border-radius:6px;padding:10px 12px;font:12px/1.45 -apple-system,
                BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2328;max-width:330px;
                box-shadow:0 1px 3px rgba(0,0,0,.12)">
      <div style="font-weight:600;margin-bottom:4px">Stage 0 — Tbilisi network</div>
      <div style="margin-bottom:6px">Required traversal
        <b>{headline['required_traversal_km']:,.0f} km</b><br>
        Largest SCC holds <b>{scc['largest_share_of_included_km'] * 100:.1f}%</b>
        of included arc km</div>
      {rows}
      <div style="margin-top:6px;color:#57606a">One line per physical segment; two-way streets
      are drawn once. Colour is <code>min_passes</code>.</div>
    </div>
    """
