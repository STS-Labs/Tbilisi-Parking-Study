"""Assemble the canonical directed-arc table and write it to GeoPackage.

This is the only module that decides what a row of `network.gpkg` contains.
Everything it needs is already decided elsewhere — tag parsing in `tags`, the
passes model in `passes`, the drivability filter in `filters`, splitting and
geometry in `arcs` — so that each rule is testable on its own.
"""

from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from . import arcs as A
from . import config as C
from . import connectivity as K
from . import dem as D
from . import extract as X
from . import filters as F
from . import passes as P
from . import tags as T

load_extract = X.load_extract
save_extract = X.save_extract

#: Column order of the `arcs` layer.  Fixed, because a stable column order is
#: part of byte-identical output.
COLUMNS: tuple[str, ...] = (
    "arc_id", "way_id", "seg_index", "direction", "from_node", "to_node",
    "length_m", "highway_class", "name", "service_type", "lanes", "dir_lanes", "width", "surface",
    "maxspeed", "oneway", "oneway_source", "incline", "gradient_pct",
    "gradient_source", "structure", "min_passes", "min_passes_basis", "pair_id",
    "pair_requirement", "narrow_basis", "capture_quality", "excluded",
    "exclusion_reason", "is_pair_representative", "scc_id", "in_largest_scc",
    "geometry",
)


def _columns() -> tuple[str, ...]:
    """The column order this run writes.

    `in_required_area` is appended **only** when a required-area boundary is
    configured. Adding it unconditionally would change the Tbilisi `arcs` layer and
    that plan is committed: its GeoPackage has to keep rebuilding byte for byte, and
    a column nobody asked for is still a different file. Where required is the whole
    clip the flag carries no information anyway.
    """
    if C.REQUIRED_BOUNDARY_PATH is None:
        return COLUMNS
    return COLUMNS[:-1] + ("in_required_area", "geometry")


def build_arc_table(
    extract: X.Extract, sampler: D.BilinearSampler | None = None
) -> gpd.GeoDataFrame:
    """Turn an `Extract` into the canonical directed-arc table."""
    way_nodes = {way_id: way.node_ids for way_id, way in extract.ways.items()}
    junctions = A.find_junction_nodes(way_nodes)
    coords = extract.node_lonlat
    blockers = extract.blocking_barrier_nodes

    rows: list[dict] = []
    for way_id in sorted(extract.ways):
        way = extract.ways[way_id]
        tags = way.tags
        highway_class = str(tags.get("highway", "")).strip().lower()
        oneway = T.parse_oneway(tags)
        oneway_source = "tag" if "oneway" in tags else "implied"

        total_lanes = T.parse_lanes(tags)
        total_width = T.parse_width(tags)
        maxspeed = T.parse_maxspeed(tags)
        surface = str(tags.get("surface", ""))
        name = str(tags.get("name", ""))
        service_type = T.parse_service_type(tags)
        # A DEM reads the terrain, not a bridge deck or a tunnel bore, so a
        # gradient on one of these is not evidence about the road (SPEC §6).
        structure = (
            "bridge"
            if str(tags.get("bridge", "")).lower() not in ("", "no")
            else "tunnel"
            if str(tags.get("tunnel", "")).lower() not in ("", "no")
            else ""
        )
        tagged_incline = T.parse_incline(tags)
        quality = P.capture_quality(highway_class)

        narrow, narrow_basis = (
            P.is_narrow_pair(total_lanes, total_width, highway_class)
            if oneway == "no"
            else (False, "")
        )
        pair_requirement = 1 if (oneway == "no" and narrow) else 0

        for seg_index, segment in enumerate(
            A.split_way_into_segments(way.node_ids, junctions)
        ):
            # A barrier only stops traffic where it sits *inside* a segment; on a
            # segment endpoint it is a junction problem, which is Stage 1's.
            blocked = any(node in blockers for node in segment[1:-1])
            reason = F.classify_exclusion(tags, highway_class, blocking_barrier=blocked)

            for arc in A.directed_arcs(way_id, seg_index, segment, oneway):
                direction = "forward" if arc.direction == "F" else "backward"
                geometry = LineString([coords[node] for node in arc.node_ids])
                length_m = A.geodesic_length_m(geometry)

                dir_lanes = T.directional_lanes(tags, direction)
                dir_width = T.directional_width(tags)
                min_passes, basis = P.min_passes_for(dir_lanes, dir_width, highway_class)

                incline = None
                if tagged_incline is not None:
                    incline = tagged_incline if arc.direction == "F" else -tagged_incline

                rows.append(
                    {
                        "arc_id": arc.arc_id,
                        "way_id": way_id,
                        "seg_index": seg_index,
                        "direction": arc.direction,
                        "from_node": arc.from_node,
                        "to_node": arc.to_node,
                        "length_m": length_m,
                        "highway_class": highway_class,
                        "name": name,
                        "service_type": service_type,
                        "structure": structure,
                        "lanes": _f(total_lanes),
                        "dir_lanes": _f(dir_lanes),
                        "width": _f(total_width),
                        "surface": surface,
                        "maxspeed": _f(maxspeed),
                        "oneway": oneway,
                        "oneway_source": oneway_source,
                        "incline": _f(incline),
                        "min_passes": int(min_passes),
                        "min_passes_basis": basis,
                        "pair_id": arc.pair_id,
                        "pair_requirement": pair_requirement,
                        "narrow_basis": narrow_basis,
                        "capture_quality": quality,
                        "excluded": reason is not None,
                        "exclusion_reason": reason or "",
                        "is_pair_representative": arc.direction == "F",
                        "_geometry": geometry,
                    }
                )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("no arcs were built — check the clip polygon and the PBF")
    frame = frame.sort_values("arc_id", kind="mergesort").reset_index(drop=True)

    frame = _attach_gradient(frame, sampler)
    frame = _attach_components(frame)
    frame = _attach_required_area(frame)

    gdf = gpd.GeoDataFrame(
        frame.drop(columns="_geometry"), geometry=frame["_geometry"].tolist(), crs="EPSG:4326"
    )
    return gdf[list(_columns())]


def _attach_required_area(frame: pd.DataFrame) -> pd.DataFrame:
    """Split *required* from *routable* — SPEC's Rural Postman case, finally used.

    With no required boundary configured every included arc is required, which is
    what Tbilisi did and what quietly reduced the problem to a Chinese Postman. Give
    it a polygon and an arc is required only if its **midpoint** falls inside; the
    rest of the clip stays perfectly legal to drive and simply never needs filming.

    The mechanism is `min_passes = 0`, not a new flag the solver has to learn.
    `lstar` gives each arc a capture edge with `lower = upper = min_passes` and a
    separate uncapped deadhead edge, so zeroing it pins the capture edge shut and
    leaves the deadhead edge alone — which is exactly the structure wanted, and it
    means orientation, the LP bound, the flow and the Euler tour all need no change.

    Midpoint rather than any-intersection because a rule has to be decidable and
    stable: an arc straddling the line belongs to exactly one side either way, and
    the length sitting close enough to the line for the choice to be arguable is
    measured and reported rather than argued about.
    """
    frame["in_required_area"] = True
    if C.REQUIRED_BOUNDARY_PATH is None:
        return frame
    if not Path(C.REQUIRED_BOUNDARY_PATH).exists():
        raise FileNotFoundError(
            f"{C.REQUIRED_BOUNDARY_PATH} missing — required-area boundary not built"
        )

    zone = gpd.read_file(C.REQUIRED_BOUNDARY_PATH).to_crs("EPSG:4326").union_all()
    midpoints = gpd.GeoSeries(
        [g.interpolate(0.5, normalized=True) for g in frame["_geometry"]],
        crs="EPSG:4326",
    )
    inside = midpoints.within(zone).to_numpy()
    frame["in_required_area"] = inside

    # Requirement is carried by `min_passes` and, for a narrow pair, by
    # `pair_requirement` on the representative. Both have to go, or the pair rule
    # re-introduces the arc through its twin.
    frame.loc[~inside, "min_passes"] = 0
    frame.loc[~inside, "pair_requirement"] = 0
    frame.loc[~inside, "min_passes_basis"] = "outside_required_area"
    return frame


def _f(value) -> float:
    return float("nan") if value is None else float(value)


def _attach_gradient(
    frame: pd.DataFrame, sampler: D.BilinearSampler | None
) -> pd.DataFrame:
    """`gradient_pct` = tagged incline where present, else DEM-derived."""
    gradient = np.full(len(frame), np.nan)
    source = np.array(["none"] * len(frame), dtype=object)

    if sampler is not None:
        geometries = frame["_geometry"].tolist()
        start = np.array([g.coords[0] for g in geometries], dtype="float64")
        end = np.array([g.coords[-1] for g in geometries], dtype="float64")
        elev_start = sampler.sample(start[:, 0], start[:, 1])
        elev_end = sampler.sample(end[:, 0], end[:, 1])
        length = frame["length_m"].to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            dem_gradient = np.where(length > 0, (elev_end - elev_start) / length * 100.0, 0.0)
        gradient = dem_gradient
        source = np.where(np.isnan(dem_gradient), "none", "dem").astype(object)

    tagged = frame["incline"].to_numpy(dtype="float64")
    has_tag = ~np.isnan(tagged)
    gradient = np.where(has_tag, tagged, gradient)
    source = np.where(has_tag, "tag", source)

    frame = frame.copy()
    frame["gradient_pct"] = gradient
    frame["gradient_source"] = source
    return frame


def _attach_components(frame: pd.DataFrame) -> pd.DataFrame:
    """SCC over the *included* arcs only — excluded arcs cannot carry a route."""
    included = frame[~frame["excluded"]]
    triples = list(
        zip(included["arc_id"], included["from_node"], included["to_node"])
    )
    labels = K.label_components(triples)

    frame = frame.copy()
    frame["scc_id"] = frame["arc_id"].map(labels).fillna(-1).astype("int64")
    frame["in_largest_scc"] = frame["scc_id"] == 0
    return frame


def required_traversal_km(frame: pd.DataFrame) -> float:
    """Σ (length × required passes), counting narrow two-way pairs once.

    The headline number of Stage 0: it is what the campaign length is computed
    from, so it is derived here once and reused by the report and the map.
    """
    if frame.empty:
        return 0.0
    shared = frame["pair_requirement"].to_numpy() > 0
    representative = frame["is_pair_representative"].to_numpy()
    passes = np.where(
        shared,
        np.where(representative, frame["pair_requirement"].to_numpy(), 0),
        frame["min_passes"].to_numpy(),
    )
    return float((frame["length_m"].to_numpy() * passes).sum() / 1000.0)


def write_gpkg(gdf: gpd.GeoDataFrame, path: Path, layer: str = C.NETWORK_LAYER) -> Path:
    """Write the arcs layer deterministically.

    GDAL stamps a wall-clock `last_change` into `gpkg_contents`, which alone is
    enough to make two identical runs differ in bytes; `OGR_CURRENT_DATE` pins
    it (CLAUDE.md rule 5).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    previous = os.environ.get("OGR_CURRENT_DATE")
    os.environ["OGR_CURRENT_DATE"] = C.OGR_CURRENT_DATE
    try:
        gdf.to_file(path, layer=layer, driver="GPKG", engine="pyogrio")
    finally:
        if previous is None:
            os.environ.pop("OGR_CURRENT_DATE", None)
        else:
            os.environ["OGR_CURRENT_DATE"] = previous
    return path
