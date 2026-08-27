"""Compare the plan's OSM network against a customer's own street layer.

The customer will not check the optimality gap. They will check whether the streets
they gave us are in the plan, and the answer has to be a number with a method
behind it.

**Matched by geometry, not by attributes.** The customer layer here carries an `Id`
of zero and a stale `Length`; there is nothing to join on. So a street counts as
present when it lies within a stated tolerance of one on the other side, and the
tolerance is reported rather than tuned until the answer looks good.

**Measured as length, not as features.** Feature counts are meaningless across two
layers that split their geometry differently — 3,368 customer parts against a
directed arc table is not a comparison. Length inside a buffer is, and it degrades
gracefully: a street half-present comes out half-matched instead of being forced
into a yes or a no.

**Directed arcs are collapsed first.** OSM carries a two-way street as two arcs
over the same centreline; counting both would double its length and make the
network look 40% bigger than the customer's. One geometry per `pair_id`, or per
`way_id:seg_index` where there is no pair.
"""

from __future__ import annotations

from pathlib import Path

from . import config as C

#: How far apart two representations of the same street may sit and still be the
#: same street. Fifteen metres covers a centreline drawn down the middle against one
#: drawn along a kerb, plus ordinary digitising error, without bridging to the next
#: street over — Tbilisi blocks are rarely under 40 m.
MATCH_TOLERANCE_M = 15.0


def _undirected(arcs):
    """One centreline per physical street piece, not one per direction."""
    frame = arcs.copy()
    pair = frame["pair_id"].astype(str)
    key = frame["way_id"].astype(str) + ":" + frame["seg_index"].astype(str)
    frame["_key"] = pair.where(pair.str.len() > 0, key)
    return frame.drop_duplicates("_key", keep="first")


def compare(osm, customer, tolerance_m: float = MATCH_TOLERANCE_M) -> dict:
    """Length agreeing, and length on each side with nothing to agree with."""
    import geopandas as gpd

    osm = _undirected(osm).to_crs(C.METRIC_CRS)
    customer = customer.to_crs(C.METRIC_CRS)

    osm_zone = gpd.GeoSeries(osm.geometry.buffer(tolerance_m), crs=C.METRIC_CRS).union_all()
    cust_zone = gpd.GeoSeries(customer.geometry.buffer(tolerance_m), crs=C.METRIC_CRS).union_all()

    cust_len = customer.geometry.length.to_numpy()
    cust_hit = customer.geometry.intersection(osm_zone).length.to_numpy()
    osm_len = osm.geometry.length.to_numpy()
    osm_hit = osm.geometry.intersection(cust_zone).length.to_numpy()

    missing = customer.assign(
        total_m=cust_len, matched_m=cust_hit, missing_m=cust_len - cust_hit
    )
    missing = missing[missing["missing_m"] > tolerance_m].copy()
    centroids = missing.geometry.centroid.to_crs("EPSG:4326") if len(missing) else None
    rows = []
    for i, (_, row) in enumerate(missing.sort_values("missing_m", ascending=False).iterrows()):
        point = missing.to_crs("EPSG:4326").geometry.iloc[
            list(missing.index).index(row.name)
        ].centroid
        rows.append({
            "missing_m": round(float(row.missing_m), 1),
            "total_m": round(float(row.total_m), 1),
            "lon": round(point.x, 6),
            "lat": round(point.y, 6),
        })

    extra = osm.assign(total_m=osm_len, matched_m=osm_hit, extra_m=osm_len - osm_hit)
    extra = extra[extra["extra_m"] > tolerance_m]

    return {
        "tolerance_m": tolerance_m,
        "customer": {
            "features": int(len(customer)),
            "total_km": round(float(cust_len.sum()) / 1000.0, 3),
            "matched_km": round(float(cust_hit.sum()) / 1000.0, 3),
            "unmatched_km": round(float((cust_len - cust_hit).sum()) / 1000.0, 3),
            "matched_pct": round(100.0 * cust_hit.sum() / max(cust_len.sum(), 1e-9), 2),
            "unmatched_features": int(len(missing)),
        },
        "osm": {
            "pieces": int(len(osm)),
            "total_km": round(float(osm_len.sum()) / 1000.0, 3),
            "matched_km": round(float(osm_hit.sum()) / 1000.0, 3),
            "extra_km": round(float((osm_len - osm_hit).sum()) / 1000.0, 3),
            "matched_pct": round(100.0 * osm_hit.sum() / max(osm_len.sum(), 1e-9), 2),
            "extra_pieces": int(len(extra)),
        },
        "worst_missing": rows[:40],
        "extra_by_class": (
            extra.groupby("highway_class")["extra_m"].sum().div(1000).round(3)
            .sort_values(ascending=False).head(15).to_dict()
        ),
        "missing_by_class_note": (
            "The customer layer has no class attribute, so missing length cannot be "
            "broken down by road type — only located."
        ),
    }


def load_customer(shapefile: Path):
    import geopandas as gpd

    frame = gpd.read_file(shapefile)
    if frame.crs is None:
        raise ValueError(f"{shapefile} has no CRS; refusing to guess")
    return frame.explode(index_parts=False).reset_index(drop=True)
