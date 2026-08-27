"""Render `reports/04-zones.html` — the zones, coloured by sequence position.

The colour ramp *is* the schedule: the first days driven are the far ones, so the
map should read as a wave moving inward from the edges of the city toward the
depot.  If it does not, the far-zones-first rule (SPEC §7.1 mitigation 2) has been
implemented backwards, and that is exactly the mistake the spec warns about.
"""

from __future__ import annotations

from pathlib import Path

import folium
import geopandas as gpd
from branca.element import Element

from . import config as C
from .mapviz import COORD_PRECISION

#: Coarser than the Stage 0 map on purpose.  This map answers "which day is this
#: street on", not "where exactly does it run", and one polyline per zone at a
#: metre or two of tolerance is the difference between a 3 MB file and a 38 MB one.
SIMPLIFY_TOLERANCE_DEG = 3e-5

#: Viridis, sampled. Dark at the start of the campaign, bright at the end.
RAMP = [
    "#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c",
    "#28ae80", "#5ec962", "#addc30", "#fde725",
]
UNREACHABLE = "#d1242f"


def _colour(position: int, total: int) -> str:
    if position < 0 or total <= 1:
        return UNREACHABLE
    index = int(round(position / (total - 1) * (len(RAMP) - 1)))
    return RAMP[min(max(index, 0), len(RAMP) - 1)]


def _lines_for(frame) -> list:
    out = []
    for geometry in frame.geometry:
        simplified = geometry.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=False)
        coords = list(simplified.coords) or list(geometry.coords)
        out.append(
            [[round(lat, COORD_PRECISION), round(lon, COORD_PRECISION)] for lon, lat in coords]
        )
    return out


def write(gpkg_path, payload: dict, path: Path = C.ZONING_REPORT_HTML) -> Path:
    arcs = gpd.read_file(gpkg_path, layer=C.ZONES_LAYER)
    window = payload["windows"][payload["default_window"]]
    days = window["campaign"]["day_table"]
    total = len(days)
    by_zone = {day["zone"]: day for day in days}

    centre = arcs.geometry.union_all().centroid
    fmap = folium.Map(
        location=[centre.y, centre.x], zoom_start=11, tiles="cartodbpositron",
        prefer_canvas=True,
    )

    # One physical piece per line: both directions of a street are the same day.
    pieces = arcs.drop_duplicates(subset=["way_id", "seg_index"])
    unreachable = pieces[~pieces["in_tour_scope"]]
    if len(unreachable):
        folium.PolyLine(
            _lines_for(unreachable), color=UNREACHABLE, weight=3.0, opacity=0.95,
            tooltip="Unreachable by any closed tour",
        ).add_to(folium.FeatureGroup(name=f"Unreachable ({len(unreachable):,} arcs)",
                                     show=True).add_to(fmap))

    reachable = pieces[pieces["in_tour_scope"]]
    for position in range(total):
        day = days[position]
        members = reachable[reachable["zone_id"] == day["zone"]]
        if not len(members):
            continue
        colour = _colour(position, total)
        tooltip = (
            f"Day {position + 1} of {total} — {day['date']}<br>"
            f"zone {day['zone']}<br>"
            f"capture {day['capture_h']:.2f} h, legs {day['leg_total_h']:.2f} h<br>"
            f"day total {day['total_h']:.2f} h of {day['available_h']:.2f} h"
        )
        # One multi-polyline per zone rather than one per street: same picture,
        # a tenth of the file, and a tooltip that describes the day rather than
        # repeating itself a thousand times.
        folium.PolyLine(
            _lines_for(members), color=colour, weight=2.6, opacity=0.9, tooltip=tooltip
        ).add_to(fmap)

    folium.CircleMarker(
        [C.DEPOT_LAT, C.DEPOT_LON], radius=7, color="#111", fill=True, fill_opacity=1.0,
        tooltip="Depot",
    ).add_to(fmap)

    fmap.get_root().html.add_child(Element(_legend(payload, window, total)))
    path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(path))
    return path


def _legend(payload: dict, window: dict, total: int) -> str:
    campaign = window["campaign"]
    swatches = "".join(
        f'<span style="display:inline-block;width:18px;height:10px;background:{c}"></span>'
        for c in RAMP
    )
    return f"""
<div style="position:fixed;bottom:18px;left:18px;z-index:9999;background:rgba(255,255,255,.95);
     padding:12px 14px;border:1px solid #ccc;border-radius:6px;font:12px/1.45 system-ui,sans-serif;
     max-width:330px">
  <div style="font-weight:600;margin-bottom:4px">Stage 4 — zones by sequence position</div>
  <div style="color:#555;margin-bottom:6px">
    Variant {payload['variant']} · {campaign['days']} days ·
    {campaign['start_date']} → {campaign['finish_date']} ·
    {payload['default_window']} window
  </div>
  <div style="margin-bottom:2px">{swatches}</div>
  <div style="display:flex;justify-content:space-between;color:#555">
    <span>day 1 (farthest)</span><span>day {total} (nearest)</span>
  </div>
  <div style="margin-top:8px;color:#555">
    <span style="display:inline-block;width:18px;height:3px;background:{UNREACHABLE};
          vertical-align:middle"></span>
    unreachable by any closed tour
  </div>
  <div style="margin-top:8px;color:#777">
    Colour is the campaign order, not a route. SPEC §7.1: distant zones go first,
    while the corridors to them are still uncovered.
  </div>
</div>
"""
