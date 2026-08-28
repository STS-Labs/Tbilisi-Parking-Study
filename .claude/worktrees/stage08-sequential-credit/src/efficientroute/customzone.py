"""Turn a customer-supplied zone polygon into a clip boundary the pipeline accepts.

Stage 0 caches its boundary as a one-row GeoJSON and reads it back if it is already
there, so a customer zone does not need a new code path — it needs to be written in
that shape. This module does that, and records where it came from.

Two things about customer shapefiles that will bite:

**Z values.** A polygon exported from a KMZ is usually `PolygonZ`. Shapely carries
the Z through, GeoJSON writes it, and every downstream `contains` test then works
in 3D against 2D points. Dropped here, once.

**Coordinate systems.** The boundary and the street layer in the same folder can be
in different CRSs — they are in this one. Nothing reprojects implicitly, so a
silent mismatch puts the zone in the Gulf of Guinea. Everything written here is
EPSG:4326 because that is what `load_boundary` and the clip expect.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config as C

#: Not a real OSM relation. The boundary cache carries a relation id because the
#: Tbilisi boundary came from one; a customer polygon has no such thing, and a
#: negative number cannot collide with a real id.
CUSTOM_RELATION_ID = -1


def _drop_z(geometry):
    from shapely.ops import transform

    if not geometry.has_z:
        return geometry
    return transform(lambda x, y, z=None: (x, y), geometry)


def prepare(shapefile: Path, name: str | None = None,
            out_path: Path | None = None, layer_name: str = "Name") -> dict:
    """Write one named polygon from `shapefile` as a Stage 0 boundary."""
    import geopandas as gpd

    out_path = Path(out_path or C.DERIVED / "00-custom-boundary.geojson")
    frame = gpd.read_file(shapefile)
    if frame.crs is None:
        raise ValueError(f"{shapefile} has no CRS; refusing to guess")
    frame = frame.to_crs("EPSG:4326")

    if name is not None:
        if layer_name not in frame.columns:
            raise ValueError(f"{shapefile} has no {layer_name!r} column to select on")
        picked = frame[frame[layer_name].astype(str).str.strip() == name]
        if picked.empty:
            available = sorted(frame[layer_name].astype(str).unique())[:10]
            raise ValueError(f"no feature named {name!r}; found {available}")
    else:
        picked = frame
    if len(picked) != 1:
        raise ValueError(f"expected exactly one polygon, got {len(picked)}")

    row = picked.iloc[0]
    geometry = _drop_z(row.geometry)
    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    metric = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(C.METRIC_CRS).iloc[0]
    tags = {
        "name": name or str(row.get(layer_name, "custom zone")),
        "source": str(shapefile),
        "boundary": "customer-supplied",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(
        {"relation_id": [CUSTOM_RELATION_ID],
         "tags": [json.dumps(tags, ensure_ascii=False, sort_keys=True)]},
        geometry=[geometry], crs="EPSG:4326",
    ).to_file(out_path, driver="GeoJSON")

    return {
        "path": str(out_path),
        "name": tags["name"],
        "source": str(shapefile),
        "source_crs": str(frame.crs),
        "area_km2": round(metric.area / 1e6, 3),
        "perimeter_km": round(metric.length / 1000.0, 3),
        "vertices": len(geometry.exterior.coords),
        "had_z": bool(row.geometry.has_z),
    }


def depot_check(boundary_path: Path, buffer_m: float | None = None) -> dict:
    """Where the depot sits relative to the zone and the clip that will be built."""
    import geopandas as gpd
    from shapely.geometry import Point

    buffer_m = C.CLIP_BUFFER_M if buffer_m is None else buffer_m
    zone = gpd.read_file(boundary_path).to_crs(C.METRIC_CRS).geometry.iloc[0]
    depot = gpd.GeoSeries([Point(C.DEPOT_LON, C.DEPOT_LAT)],
                          crs="EPSG:4326").to_crs(C.METRIC_CRS).iloc[0]
    clip = zone.buffer(buffer_m)
    return {
        "inside_zone": bool(zone.contains(depot)),
        "distance_to_boundary_m": round(zone.exterior.distance(depot), 1),
        "distance_to_centroid_km": round(zone.centroid.distance(depot) / 1000.0, 3),
        "inside_clip": bool(clip.contains(depot)),
        "clip_margin_m": round(buffer_m - zone.exterior.distance(depot), 1),
        "clip_area_km2": round(clip.area / 1e6, 2),
        "buffer_m": buffer_m,
    }
