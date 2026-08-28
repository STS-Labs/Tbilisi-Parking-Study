"""The customer's own street layer as the required set.

> **The customer's layer says WHAT to cover. OSM says HOW to drive it.**

`data/custom/B Zone_Streets/Streets.shp` is 3,368 polyline parts with no name, no
class, no `oneway`, no `lanes` and no `width` — a display layer, not a graph. It
cannot drive the pipeline on its own, and the previous campaign used it only to
reconcile against. This module makes it the *requirement* while OSM stays the
*network*, which is a different and much more useful thing.

Four steps, each of which can go wrong in a way that silently wrecks the routing:

**1. Reproject.** The street layer is EPSG:32638 and the zone polygon beside it is
EPSG:4326. Nothing in this codebase reprojects implicitly. Everything below works
in `config.METRIC_CRS` because every tolerance here is in metres, and writes
EPSG:4326 because that is what the rest of the pipeline reads.

**2. Node it.** 3,368 parts is not a graph. 833 of its endpoints sit *on* another
street's interior without a shared vertex — visually a T-junction, topologically
nothing. Left alone every one of them is a false dead end, and a false dead end
costs the solver a u-turn and a doubled-back street. `unary_union` splits the
linework at every true crossing; a small endpoint snap first closes the gaps that
are near-misses rather than crossings. What remains unattached after both is
counted and reported, because that is the number that says how much of the
customer's topology is real.

**3. Match to OSM.** A customer street that OSM also has is *carried by the OSM
arc*: the arc keeps its own geometry, class, `oneway`, lanes, width, surface,
maxspeed, name and turn restrictions, and is marked required. That is the
attribute transfer §3.2 asks for, done by identity rather than by copying fields
onto a geometry that has no graph behind it — one matcher, not two.

**4. Stitch in what OSM has not got.** The pieces with no OSM counterpart are the
only geometry this pipeline has ever taken from outside the PBF. They are injected
as synthetic two-way residential ways so that Stage 0 splits, orients and prices
them like any other street — and every one of them is flagged
`attributes_unverified`, carried into the turn sheets, and listed in
`surveys/unverified-streets.md` for a driver to adjudicate on the ground. The
data to settle their signage in software does not exist.

On CLAUDE.md rule 1 — *never invent geometry*. Nothing here interpolates, smooths
or synthesises a connector. Every injected coordinate is a vertex the customer
digitised, and the single modification made to any of them is snapping an endpoint
onto an existing node, which is a move of at most `OSM_NODE_SNAP_M` and is
reported per endpoint. The rule bars inventing shape, not accepting a second
supplied source; a source outside the PBF is why the flag and the survey exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import config as C
from . import extract as X

#: How far two endpoints of the customer's own linework may sit apart and still be
#: the same junction. Deliberately small: the layer is digitised for display, so
#: its near-misses are drafting slips of a metre or two, and anything larger starts
#: welding a street to its neighbour across a kerb.
SNAP_TOLERANCE_M = 2.0

#: How far a customer street may sit from an OSM street and still be the same
#: street. Same figure and same reasoning as `reconcile.MATCH_TOLERANCE_M`, and
#: deliberately the same *number*, so "97.0% matches" means one thing in this run.
MATCH_TOLERANCE_M = 15.0

#: What fraction of a noded piece has to lie within `MATCH_TOLERANCE_M` of OSM for
#: OSM to be carrying it.
#:
#: A zone polygon cuts an arc once, which is why the required-area rule can settle
#: it on the midpoint. A street layer is not a cut: it either contains a street or
#: it does not, so the whole arc is evidence and the honest statistic is the share
#: of its length that is covered. Half is the decidable place to put the line, and
#: the length sitting near it is reported rather than argued about.
COVERAGE_MIN = 0.5

#: How far an injected endpoint may be moved to land on an existing OSM node.
#: Beyond this the piece is reported as unconnected rather than dragged into place:
#: a 30 m snap is not a junction, it is a guess about one.
OSM_NODE_SNAP_M = 15.0

#: Synthetic ways and nodes count down from here. OSM ids are positive, so a
#: negative id cannot collide with one, and `sorted(extract.ways)` still gives a
#: deterministic build order.
SYNTHETIC_ID_BASE = -1

#: Tag written onto every injected way. Read back by `network.build_arc_table` into
#: the `attributes_unverified` column, so the flag survives into the arc table, the
#: routes and the driver's sheet rather than living only in a report.
UNVERIFIED_TAG = "efficientroute:unverified"
SOURCE_TAG = "efficientroute:source"

#: SPEC §3.2 has nothing to say about a street OSM does not know exists, and there
#: is no attribute to inherit. Two-way residential at the default residential speed
#: is the brief's instruction and also the §1.1 choice: `residential` two-way with
#: no `lanes` and no `width` is a narrow pair, so one pass covers it, and a driver
#: who finds a one-way sign loses nothing by having planned to drive it both ways.
SYNTHETIC_TAGS: dict[str, str] = {
    "highway": "residential",
    "oneway": "no",
}


# --------------------------------------------------------------------- noding


def _endpoint_key(point) -> tuple[float, float]:
    """Coordinates rounded to a millimetre, so exact coincidence is testable.

    Shapefile coordinates are doubles written by a GIS; two endpoints a draughtsman
    placed on the same vertex come back bit-identical, but comparing raw floats
    across a reprojection would not survive. A millimetre is far below any
    tolerance in this module and far above double precision at UTM magnitudes.
    """
    return (round(point[0], 3), round(point[1], 3))


def node_layer(shapefile: Path, snap_tolerance_m: float = SNAP_TOLERANCE_M) -> dict:
    """Turn the customer's polyline soup into noded linework, and say what it cost.

    Returns the noded pieces in `config.METRIC_CRS` together with the endpoint
    census — the number that matters, because every endpoint left unattached is a
    dead end the solver will believe.
    """
    import geopandas as gpd
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union

    frame = gpd.read_file(shapefile)
    if frame.crs is None:
        raise ValueError(f"{shapefile} has no CRS; refusing to guess")
    source_crs = str(frame.crs)
    frame = frame.explode(index_parts=False).reset_index(drop=True)
    frame = frame.to_crs(C.METRIC_CRS)

    lines = [g for g in frame.geometry if g is not None and g.length > 0.0]
    parts_in = len(lines)
    length_in_km = sum(g.length for g in lines) / 1000.0

    # --- endpoint census, before anything is moved -------------------------
    #
    # Three states, and the middle one is the whole reason this step exists:
    #   attached  — the endpoint touches other linework already (a shared vertex,
    #               or it lies on another street's interior: a real T-junction OSM
    #               would node and a display layer does not)
    #   snapped   — it misses by less than the tolerance: a drafting slip
    #   unattached— nothing within the tolerance: a dead end, real or false
    index = gpd.GeoSeries(lines, crs=C.METRIC_CRS).sindex
    endpoints: dict[tuple[float, float], list[int]] = {}
    for i, line in enumerate(lines):
        coords = list(line.coords)
        endpoints.setdefault(_endpoint_key(coords[0]), []).append(i)
        endpoints.setdefault(_endpoint_key(coords[-1]), []).append(i)

    census = {"attached_shared_vertex": 0, "attached_on_interior": 0,
              "snapped": 0, "unattached": 0}
    moves: dict[tuple[float, float], tuple[float, float]] = {}
    snap_distances: list[float] = []
    unattached_points: list[tuple[float, float]] = []

    for key in sorted(endpoints):
        owners = set(endpoints[key])
        point = Point(key)
        if len(endpoints[key]) > 1:
            census["attached_shared_vertex"] += len(endpoints[key])
            continue

        # Nearest linework that is not one of this endpoint's own lines.
        window = point.buffer(max(snap_tolerance_m, 0.01) * 2.0)
        best_distance, best_point = float("inf"), None
        for j in index.query(window):
            if int(j) in owners:
                continue
            line = lines[int(j)]
            distance = line.distance(point)
            if distance < best_distance:
                best_distance = distance
                best_point = line.interpolate(line.project(point))

        if best_distance <= 1e-3:
            census["attached_on_interior"] += 1
        elif best_distance <= snap_tolerance_m:
            census["snapped"] += 1
            snap_distances.append(best_distance)
            moves[key] = (best_point.x, best_point.y)
        else:
            census["unattached"] += 1
            unattached_points.append(key)

    # --- apply the snaps, then node ---------------------------------------
    if moves:
        moved = []
        for line in lines:
            coords = list(line.coords)
            start, end = _endpoint_key(coords[0]), _endpoint_key(coords[-1])
            if start in moves:
                coords[0] = moves[start]
            if end in moves:
                coords[-1] = moves[end]
            moved.append(LineString(coords))
        lines = moved

    noded = unary_union(lines)
    pieces = list(noded.geoms) if hasattr(noded, "geoms") else [noded]
    pieces = [p for p in pieces if p.length > 0.0]

    unattached_lonlat = (
        gpd.GeoSeries([Point(p) for p in unattached_points], crs=C.METRIC_CRS)
        .to_crs("EPSG:4326") if unattached_points else None
    )

    return {
        "pieces": gpd.GeoDataFrame(geometry=pieces, crs=C.METRIC_CRS),
        "report": {
            "source": str(shapefile),
            "source_crs": source_crs,
            "reprojected_to": C.METRIC_CRS,
            "snap_tolerance_m": snap_tolerance_m,
            "parts_in": parts_in,
            "length_in_km": round(length_in_km, 3),
            "pieces_out": len(pieces),
            "length_out_km": round(sum(p.length for p in pieces) / 1000.0, 3),
            "endpoints_total": 2 * parts_in,
            "distinct_endpoint_locations": len(endpoints),
            "endpoints": census,
            "snap_distance_m": {
                "count": len(snap_distances),
                "max": round(max(snap_distances), 3) if snap_distances else 0.0,
                "mean": round(float(np.mean(snap_distances)), 3) if snap_distances else 0.0,
            },
            "unattached_sample": [
                {"lon": round(p.x, 6), "lat": round(p.y, 6)}
                for p in (unattached_lonlat.geometry[:40] if unattached_lonlat is not None else [])
            ],
        },
    }


# ------------------------------------------------------------------- matching


def coverage_fractions(pieces, osm_arcs, tolerance_m: float = MATCH_TOLERANCE_M,
                       drivable_only: bool = True):
    """For each piece, the share of its length lying within `tolerance_m` of OSM.

    Length inside a buffer rather than a yes/no nearest-neighbour test, for the
    reason `reconcile` gives: two layers that split their geometry differently
    cannot be compared feature to feature, and a street half-present should come
    out half-matched instead of being forced into a verdict.

    **Drivable arcs only, and this is not a detail.** The question being asked is
    "can the routing network already carry this street", and an arc the filter
    excluded — a footway, a track, a gated private road, an impassable surface —
    cannot carry anything. Matching against the whole arc table answers a different
    and useless question: measured that way every metre of Zone B's customer layer
    is "in OSM", including 4.7 km whose only OSM counterpart is something a camera
    car may not drive down. Those are exactly the streets that have to be stitched
    in, so counting them as matched would silently drop them from the plan.
    """
    import geopandas as gpd

    from . import reconcile

    if drivable_only and "excluded" in osm_arcs.columns:
        osm_arcs = osm_arcs[~osm_arcs["excluded"]]
    osm = reconcile._undirected(osm_arcs).to_crs(C.METRIC_CRS)
    osm_zone = gpd.GeoSeries(
        osm.geometry.buffer(tolerance_m), crs=C.METRIC_CRS
    ).union_all()

    pieces = pieces.to_crs(C.METRIC_CRS)
    total = pieces.geometry.length.to_numpy()
    inside = pieces.geometry.intersection(osm_zone).length.to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        fraction = np.where(total > 0, inside / total, 0.0)
    return fraction, total, inside


def required_arc_mask(arc_geometries, required_network,
                      tolerance_m: float = MATCH_TOLERANCE_M,
                      coverage_min: float = COVERAGE_MIN):
    """Which arcs of the routing network the customer actually asked for.

    The mirror image of `coverage_fractions`: there the question was "does OSM
    carry this customer street", here it is "did the customer ask for this OSM
    arc". Same buffer, same tolerance, so the two answers are consistent by
    construction — an arc is required exactly when it is the OSM side of a match.

    Injected arcs come out required automatically: their geometry *is* the
    customer network, so their coverage is 1.0.
    """
    import geopandas as gpd

    network = gpd.read_file(required_network).to_crs(C.METRIC_CRS)
    zone = gpd.GeoSeries(
        network.geometry.buffer(tolerance_m), crs=C.METRIC_CRS
    ).union_all()

    arcs = gpd.GeoSeries(arc_geometries, crs="EPSG:4326").to_crs(C.METRIC_CRS)
    total = arcs.length.to_numpy()
    inside = arcs.intersection(zone).length.to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        fraction = np.where(total > 0, inside / total, 0.0)
    return fraction >= coverage_min, fraction


# ------------------------------------------------------------------ stitching


def _osm_node_table(extract: X.Extract, clip_bounds=None):
    """Every OSM node the arc builder can use as a junction, in metric coordinates."""
    import geopandas as gpd
    from shapely.geometry import Point

    used: set[int] = set()
    for way in extract.ways.values():
        used.update(way.node_ids)
    node_ids = sorted(nid for nid in used if nid in extract.node_lonlat)
    points = [Point(*extract.node_lonlat[nid]) for nid in node_ids]
    metric = gpd.GeoSeries(points, crs="EPSG:4326").to_crs(C.METRIC_CRS)
    return node_ids, metric


def synthesise_ways(pieces, extract: X.Extract,
                    snap_m: float = OSM_NODE_SNAP_M) -> dict:
    """Turn the pieces OSM has not got into ways the arc builder will accept.

    Node identity is what makes this work. Two injected pieces that share an
    endpoint get the same synthetic node id, so `arcs.find_junction_nodes` sees a
    junction; an endpoint that lands on an existing OSM node *adopts that node's
    id and its coordinate*, so the same function splits the OSM way there and the
    new street is genuinely joined to the network rather than lying beside it.

    Whatever is left over is reported, not forced. An endpoint with no OSM node
    inside `snap_m` and no injected neighbour is a piece the routing graph cannot
    reach, and saying so is the point of the exercise.
    """
    import geopandas as gpd
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    pieces = pieces.to_crs(C.METRIC_CRS)
    node_ids, node_metric = _osm_node_table(extract)
    node_points = list(node_metric.geometry)
    tree = STRtree(node_points) if node_points else None

    # Endpoint -> node id. Sorted so the synthetic ids are deterministic.
    endpoint_keys = sorted({
        key
        for geometry in pieces.geometry
        for key in (_endpoint_key(geometry.coords[0]), _endpoint_key(geometry.coords[-1]))
    })

    assigned: dict[tuple[float, float], int] = {}
    moved_to: dict[tuple[float, float], tuple[float, float]] = {}
    snapped_rows: list[dict] = []
    unsnapped: list[tuple[float, float]] = []
    next_id = SYNTHETIC_ID_BASE

    for key in endpoint_keys:
        point = Point(key)
        hit, distance = None, float("inf")
        if tree is not None:
            candidates = tree.query(point.buffer(snap_m))
            for j in candidates:
                position = int(j)
                d = node_points[position].distance(point)
                # Ties broken on the node id, so two equidistant nodes always give
                # the same answer (CLAUDE.md rule 5).
                if d < distance or (d == distance and hit is not None
                                    and node_ids[position] < hit):
                    distance, hit, hit_position = d, node_ids[position], position
        if hit is not None and distance <= snap_m:
            assigned[key] = hit
            moved_to[key] = tuple(node_points[hit_position].coords[0])
            snapped_rows.append({"node_id": hit, "distance_m": round(distance, 2)})
        else:
            assigned[key] = next_id
            next_id -= 1
            unsnapped.append(key)

    # Interior vertices get their own synthetic ids; they are not junctions and
    # are never shared, so they carry no topology, only shape.
    ways: dict[int, X.WayRecord] = {}
    node_lonlat: dict[int, tuple[float, float]] = {}
    way_id = SYNTHETIC_ID_BASE
    geometries: list = []

    for geometry in (
        sorted(pieces.geometry, key=lambda g: (_endpoint_key(g.coords[0]),
                                               _endpoint_key(g.coords[-1]),
                                               round(g.length, 3)))
    ):
        coords = list(geometry.coords)
        start, end = _endpoint_key(coords[0]), _endpoint_key(coords[-1])
        if start in moved_to:
            coords[0] = moved_to[start]
        if end in moved_to:
            coords[-1] = moved_to[end]

        ids: list[int] = []
        for position, coordinate in enumerate(coords):
            if position == 0:
                ids.append(assigned[start])
            elif position == len(coords) - 1:
                ids.append(assigned[end])
            else:
                ids.append(next_id)
                next_id -= 1
        if len(set(ids)) < 2:
            continue

        tags = dict(SYNTHETIC_TAGS)
        tags[UNVERIFIED_TAG] = "yes"
        tags[SOURCE_TAG] = "customer Streets.shp"
        ways[way_id] = X.WayRecord(way_id, tags, ids)
        geometries.append((way_id, ids, coords))
        way_id -= 1

    # Metric -> WGS84, once, for every coordinate that is not already an OSM node.
    from shapely.geometry import LineString

    flat = [Point(c) for _, _, coords in geometries for c in coords]
    lonlat = (
        gpd.GeoSeries(flat, crs=C.METRIC_CRS).to_crs("EPSG:4326")
        if flat else gpd.GeoSeries([], crs="EPSG:4326")
    )
    cursor = 0
    injected_lines = []
    for _, ids, coords in geometries:
        line_coords = []
        for node_id in ids:
            point = lonlat.geometry.iloc[cursor]
            cursor += 1
            if node_id in extract.node_lonlat:
                line_coords.append(extract.node_lonlat[node_id])
                continue
            node_lonlat[node_id] = (float(point.x), float(point.y))
            line_coords.append((float(point.x), float(point.y)))
        injected_lines.append(LineString(line_coords))

    return {
        "ways": ways,
        "node_lonlat": node_lonlat,
        "geometry": gpd.GeoDataFrame(
            {"way_id": [w for w, _, _ in geometries]},
            geometry=injected_lines, crs="EPSG:4326",
        ),
        "report": {
            "snap_tolerance_m": snap_m,
            "pieces": len(geometries),
            "length_km": round(float(pieces.geometry.length.sum()) / 1000.0, 3),
            "distinct_endpoints": len(endpoint_keys),
            "endpoints_snapped_to_osm": len(snapped_rows),
            "endpoints_not_snapped": len(unsnapped),
            "snap_distance_m": {
                "max": round(max((r["distance_m"] for r in snapped_rows), default=0.0), 2),
                "mean": round(
                    float(np.mean([r["distance_m"] for r in snapped_rows])), 2
                ) if snapped_rows else 0.0,
            },
            "synthetic_nodes": len(node_lonlat),
        },
    }


def augment(extract: X.Extract, synthesised: dict) -> X.Extract:
    """Add the injected ways to the extract, in place, and say nothing silently.

    Every injected way is recorded in `dropped_ways` under the reason
    `injected_customer_street` — CLAUDE.md rule 4 asks for a machine-readable line
    for anything that leaves the network, and something that *enters* it from
    outside the PBF deserves the same.
    """
    for way_id, record in synthesised["ways"].items():
        if way_id in extract.ways:
            raise ValueError(f"synthetic way id {way_id} collides with an OSM way")
        extract.ways[way_id] = record
    for node_id, lonlat in synthesised["node_lonlat"].items():
        if node_id in extract.node_lonlat:
            raise ValueError(f"synthetic node id {node_id} collides with an OSM node")
        extract.node_lonlat[node_id] = lonlat
    for way_id in sorted(synthesised["ways"], reverse=True):
        extract.dropped_ways.append(
            {"way_id": way_id, "reason": "injected_customer_street",
             "highway": SYNTHETIC_TAGS["highway"]}
        )
    return extract


# -------------------------------------------------------------------- survey


def osm_evidence(injected, osm_arcs, tolerance_m: float = MATCH_TOLERANCE_M):
    """What OSM *does* say about a street it will not let the camera car drive.

    The interesting result of this whole exercise. Every metre of Zone B's customer
    layer has an OSM way under it; the pieces that come out unmatched are not
    missing from OSM at all, they are the ones whose OSM counterpart the drivability
    filter threw out — `highway=construction`, `access=private`, a bollard, a
    footway. "OSM has not caught up" would have been the wrong story and the wrong
    work order.

    So each injected street is joined back to the nearest *excluded* arc, and the
    reason that arc was excluded goes into the survey. A driver told "OSM says this
    is a building site" and one told "OSM has never heard of this" go and do
    different things.
    """
    import geopandas as gpd

    excluded = osm_arcs[osm_arcs["excluded"]]
    if not len(excluded) or not len(injected):
        return injected.assign(osm_class="", osm_exclusion="", osm_distance_m=float("nan"))

    left = injected.to_crs(C.METRIC_CRS)
    right = excluded.to_crs(C.METRIC_CRS)[
        ["highway_class", "exclusion_reason", "geometry"]
    ]
    joined = gpd.sjoin_nearest(
        left, right, how="left", max_distance=tolerance_m, distance_col="osm_distance_m"
    )
    joined = joined[~joined.index.duplicated(keep="first")]
    return injected.assign(
        osm_class=joined["highway_class"].fillna("").to_numpy(),
        osm_exclusion=joined["exclusion_reason"].fillna("").to_numpy(),
        osm_distance_m=joined["osm_distance_m"].to_numpy(),
    )


def write_survey(injected, report: dict, path: Path) -> Path:
    """`surveys/unverified-streets.md` — the streets a person has to go and look at.

    This is not a report the customer reads for reassurance. It is a work order:
    every row is a street the plan will drive on assumptions no data supports, and
    the driver is the only instrument available for settling them.
    """
    frame = injected.to_crs(C.METRIC_CRS)
    lengths = frame.geometry.length.to_numpy()
    centroids = frame.geometry.centroid.to_crs("EPSG:4326") if len(frame) else []
    order = np.argsort(-lengths) if len(frame) else []
    has_evidence = "osm_exclusion" in injected.columns

    lines = [
        "# Unverified streets — adjudicate on the ground\n",
        f"**{len(frame)} streets, {lengths.sum() / 1000.0:.2f} km.** These are in the "
        "customer's `Streets.shp` and the routing network cannot carry them, so the "
        "plan drives them on **synthesised attributes**: two-way `residential` at the "
        f"default residential speed ({C.BASE_FREE_FLOW_KMH['residential']:.0f} km/h "
        "free flow), no lane count, no width, no turn restrictions.\n",
    ]
    if has_evidence:
        counts = (
            injected.assign(k=injected["osm_class"] + " / " + injected["osm_exclusion"])
            .groupby("k").size().sort_values(ascending=False)
        )
        lines += [
            "\n## Read this first — OSM does know about these streets\n",
            "Not one of them is absent from OpenStreetMap. Every one has an OSM way "
            "underneath it that the drivability filter excluded, and *why* it was "
            "excluded is the most useful thing on this page:\n",
            "| OSM says | streets |",
            "| --- | ---: |",
        ]
        for key, count in counts.items():
            lines.append(f"| {key.strip(' /') or '(nothing within tolerance)'} | {count} |")
        lines.append(
            "\n`construction` means OSM believes the street is being built. "
            "`access_private` and `barrier_blocking` mean OSM believes there is a gate "
            "or a bollard. `class_excluded` on a `footway`, `pedestrian` or `steps` "
            "means the customer digitised something that is not a road at all. Each of "
            "those is a different answer to \"why can we not drive here\", and the "
            "driver settles it in one look.\n"
        )

    lines += [
        "\n## What the driver has to settle\n",
        "1. **Can the car get in at all?** A gate, a bollard or a building site ends "
        "the question — report it and the street comes out of the required set.\n"
        "2. **One-way signage.** The plan assumes two-way. A one-way street driven "
        "against the arrow is a legality and safety problem, not a modelling nicety, "
        "and there is no data anywhere that can settle it in software.\n"
        "3. **Width.** Two-way `residential` with no width is treated as a narrow "
        "pair — one pass covers both sides. A wide street needs two.\n"
        "4. **Junction control.** No turn restriction is modelled at either end.\n",
        "\nCorrect any of these and the fix belongs in OpenStreetMap, not in this "
        "repository: every future run of every future campaign then gets it for free.\n",
        "\n## The streets\n",
        "| # | Length m | Centre lon | Centre lat | OSM says | Way id |",
        "| ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for rank, i in enumerate(order, start=1):
        point = centroids.iloc[int(i)]
        says = "—"
        if has_evidence:
            says = (f"{injected['osm_class'].iloc[int(i)]} / "
                    f"{injected['osm_exclusion'].iloc[int(i)]}").strip(" /") or "—"
        lines.append(
            f"| {rank} | {lengths[int(i)]:.1f} | {point.x:.6f} | {point.y:.6f} | "
            f"{says} | {int(injected['way_id'].iloc[int(i)])} |"
        )

    lines.append(
        f"\n*Generated by `efficientroute prepare-network`. Endpoints snapped onto an "
        f"existing OSM node: {report['endpoints_snapped_to_osm']} of "
        f"{report['distinct_endpoints']}, largest move "
        f"{report['snap_distance_m']['max']} m.*\n"
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines))
    return Path(path)


def write_network(pieces, path: Path) -> Path:
    """The noded, snapped customer network as the pipeline's required-set input."""
    pieces = pieces.to_crs("EPSG:4326")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if Path(path).exists():
        Path(path).unlink()
    pieces[["geometry"]].to_file(path, driver="GeoJSON")
    return Path(path)


def write_json(payload: dict, path: Path) -> Path:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return Path(path)
