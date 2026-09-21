"""Render `reports/01-turn-graph.html` — traps, restricted junctions, U-turns."""

from __future__ import annotations

import json
from pathlib import Path

import folium
import numpy as np
from branca.element import Element

from . import config as C
from .mapviz import COORD_PRECISION, SIMPLIFY_TOLERANCE_DEG, _NetworkLayers

LINE_STYLES: dict[str, dict] = {
    "context": {"label": "Routable network (context)", "color": "#c9d1d9", "weight": 1.0, "opacity": 0.7, "on": False},
    "lost": {"label": "Lost from L's largest SCC", "color": "#e3008c", "weight": 3.4, "opacity": 1.0, "on": True},
    "trap_out": {"label": "Trap — no legal exit", "color": "#d1242f", "weight": 3.8, "opacity": 1.0, "on": True},
    "trap_in": {"label": "Trap — no legal entry", "color": "#bf8700", "weight": 3.8, "opacity": 1.0, "on": True},
}
POINT_STYLES: dict[str, dict] = {
    "restricted": {"label": "Restricted junction", "color": "#8250df", "radius": 4, "on": True},
    "uturn_tip": {"label": "U-turn — dead-end tip", "color": "#1a7f37", "radius": 2, "on": False},
    "uturn_width": {"label": "U-turn — width permitted", "color": "#1f6feb", "radius": 3, "on": True},
}


def _lines_for(frame) -> list:
    out = []
    for geometry in frame.geometry:
        simplified = geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=False)
        coords = list(simplified.coords) or list(geometry.coords)
        out.append([[round(lat, COORD_PRECISION), round(lon, COORD_PRECISION)] for lon, lat in coords])
    return out


def write(arcs, graph, audit: dict, restricted_nodes, node_lonlat, path: Path = C.TURN_REPORT_HTML) -> Path:
    indexed = arcs.set_index("arc_id")
    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]

    lost_ids = [row["arc_id"] for row in audit["scc"]["lost_rows"]]
    trap_out = [r["arc_id"] for r in audit["traps"]["rows"] if r["kind"] == "no_legal_exit"]
    trap_in = [r["arc_id"] for r in audit["traps"]["rows"] if r["kind"] == "no_legal_entry"]

    lines = {
        "context": _lines_for(routable.drop_duplicates(subset=["way_id", "seg_index"])),
        "lost": _lines_for(indexed.loc[sorted(set(lost_ids))]) if lost_ids else [],
        "trap_out": _lines_for(indexed.loc[sorted(set(trap_out))]) if trap_out else [],
        "trap_in": _lines_for(indexed.loc[sorted(set(trap_in))]) if trap_in else [],
    }

    uturn_tip: list[list[float]] = []
    uturn_width: list[list[float]] = []
    for row in graph.u_turn_log:
        point = node_lonlat.get(row["osm_node"])
        if point is None:
            continue
        target = uturn_tip if row["reason"] == "dead_end_tip" else uturn_width
        target.append([round(point[1], COORD_PRECISION), round(point[0], COORD_PRECISION)])
    points = {
        "restricted": [
            [round(node_lonlat[n][1], COORD_PRECISION), round(node_lonlat[n][0], COORD_PRECISION)]
            for n in sorted(restricted_nodes)
            if n in node_lonlat
        ],
        "uturn_tip": uturn_tip,
        "uturn_width": uturn_width,
    }

    centre = routable.geometry.iloc[0].coords[0]
    fmap = folium.Map(
        location=[C.DEPOT_LAT, C.DEPOT_LON] if centre else [41.72, 44.8],
        zoom_start=12,
        tiles="cartodbpositron",
        prefer_canvas=True,
        control_scale=True,
    )
    folium.Marker(
        [C.DEPOT_LAT, C.DEPOT_LON],
        tooltip="Depot (SPEC §5)",
        icon=folium.Icon(color="darkblue", icon="home", prefix="fa"),
    ).add_to(fmap)

    map_var = fmap.get_name()
    script = f"""
        (function() {{
          var lines = {json.dumps(lines, separators=(",", ":"))};
          var lineStyles = {json.dumps({k: {a: b for a, b in v.items() if a not in ("label", "on")} for k, v in LINE_STYLES.items()}, separators=(",", ":"))};
          var lineOn = {json.dumps({k: v["on"] for k, v in LINE_STYLES.items()})};
          var lineLabels = {json.dumps({k: v["label"] for k, v in LINE_STYLES.items()})};
          var points = {json.dumps(points, separators=(",", ":"))};
          var pointStyles = {json.dumps({k: {"color": v["color"], "radius": v["radius"]} for k, v in POINT_STYLES.items()}, separators=(",", ":"))};
          var pointOn = {json.dumps({k: v["on"] for k, v in POINT_STYLES.items()})};
          var pointLabels = {json.dumps({k: v["label"] for k, v in POINT_STYLES.items()})};
          var overlays = {{}};
          ["context","lost","trap_out","trap_in"].forEach(function(key) {{
            var group = L.layerGroup();
            (lines[key] || []).forEach(function(coords) {{
              L.polyline(coords, lineStyles[key]).addTo(group);
            }});
            if (lineOn[key]) {{ group.addTo({map_var}); }}
            overlays[lineLabels[key] + " (" + (lines[key] || []).length.toLocaleString() + ")"] = group;
          }});
          ["restricted","uturn_width","uturn_tip"].forEach(function(key) {{
            var group = L.layerGroup();
            var st = pointStyles[key];
            (points[key] || []).forEach(function(p) {{
              L.circleMarker(p, {{radius: st.radius, color: st.color, weight: 1,
                                  fillColor: st.color, fillOpacity: 0.75}}).addTo(group);
            }});
            if (pointOn[key]) {{ group.addTo({map_var}); }}
            overlays[pointLabels[key] + " (" + (points[key] || []).length.toLocaleString() + ")"] = group;
          }});
          L.control.layers(null, overlays, {{collapsed: false, position: "topright"}}).addTo({map_var});
        }})();
    """
    fmap.add_child(_NetworkLayers(script))
    fmap.get_root().html.add_child(Element(_legend(audit)))
    path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(path))
    return path


def _legend(audit: dict) -> str:
    scc = audit["scc"]
    traps = audit["traps"]
    rows = "".join(
        f'<div><span style="display:inline-block;width:20px;height:0;border-top:3px solid {s["color"]};'
        f'vertical-align:middle;margin-right:6px"></span>{s["label"]}</div>'
        for s in LINE_STYLES.values()
    ) + "".join(
        f'<div><span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
        f'background:{s["color"]};margin-right:10px;margin-left:6px"></span>{s["label"]}</div>'
        for s in POINT_STYLES.values()
    )
    return f"""
    <div style="position:fixed;bottom:18px;left:18px;z-index:9999;background:rgba(255,255,255,.94);
                border:1px solid #d0d7de;border-radius:6px;padding:10px 12px;font:12px/1.45 -apple-system,
                BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2328;max-width:340px;
                box-shadow:0 1px 3px rgba(0,0,0,.12)">
      <div style="font-weight:600;margin-bottom:4px">Stage 1 — turn-expanded graph L(G)</div>
      <div style="margin-bottom:6px">
        {audit['graph']['nodes']:,} nodes, {audit['graph']['edges']:,} legal manoeuvres<br>
        Largest SCC of L holds <b>{scc['share_of_required_km'] * 100:.2f}%</b> of required km<br>
        Traps: <b>{traps['no_legal_exit']}</b> with no exit, <b>{traps['no_legal_entry']}</b> with no entry
      </div>
      {rows}
      <div style="margin-top:6px;color:#57606a">Context layer is off by default — switch it on to
      place the traps against the network.</div>
    </div>
    """
