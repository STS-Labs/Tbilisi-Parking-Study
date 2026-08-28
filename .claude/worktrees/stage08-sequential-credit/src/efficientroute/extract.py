"""PBF extraction: boundary, ways, node coordinates, barriers, restriction count.

One pass over the file collects everything Stage 0 needs.  The result is cached
to disk so that the arc table can be rebuilt — and its determinism checked —
without re-reading 101 MB of protobuf.
"""

from __future__ import annotations

import gzip
import hashlib
import pickle
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import osmium
from shapely import wkb as shapely_wkb
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from . import config as C
from . import filters as F


@dataclass
class WayRecord:
    way_id: int
    tags: dict[str, str]
    node_ids: list[int]


@dataclass
class Extract:
    """Everything Stage 0 reads out of the PBF, in one cacheable object."""

    ways: dict[int, WayRecord] = field(default_factory=dict)
    node_lonlat: dict[int, tuple[float, float]] = field(default_factory=dict)
    blocking_barrier_nodes: set[int] = field(default_factory=set)
    barrier_nodes_seen: int = 0
    restriction_relations_total: int = 0
    restriction_relations_in_clip: int = 0
    dropped_ways: list[dict] = field(default_factory=list)
    dropped_outside_clip: int = 0
    boundary_relation_id: int | None = None
    boundary_wkb: bytes | None = None
    clip_wkb: bytes | None = None
    source: dict = field(default_factory=dict)

    @property
    def boundary(self) -> BaseGeometry | None:
        return shapely_wkb.loads(self.boundary_wkb) if self.boundary_wkb else None

    @property
    def clip(self) -> BaseGeometry | None:
        return shapely_wkb.loads(self.clip_wkb) if self.clip_wkb else None


def find_admin_boundary(
    pbf_path: Path | str, name_candidates: tuple[str, ...] = ("tbilisi", "თბილისი"), admin_level: str = "4"
) -> tuple[int, BaseGeometry, dict[str, str]]:
    """Locate the municipality boundary relation in the PBF and assemble it.

    The relation is *found*, never hardcoded (stage brief), and its id is carried
    into the report.  Assembling the multipolygon from the file itself keeps the
    pipeline offline and deterministic — no Overpass call at build time.
    """
    matches: list[tuple[int, dict[str, str]]] = []
    for relation in osmium.FileProcessor(str(pbf_path), osmium.osm.RELATION):
        tags = relation.tags
        if tags.get("boundary") != "administrative" or tags.get("admin_level") != admin_level:
            continue
        names = " ".join(
            tags.get(key, "") for key in ("name", "name:en", "int_name", "official_name")
        ).lower()
        if any(candidate in names for candidate in name_candidates):
            matches.append((relation.id, dict(tags)))

    if not matches:
        raise LookupError(
            f"no admin_level={admin_level} boundary relation matching {name_candidates}"
        )
    matches.sort(key=lambda m: m[0])
    relation_id, relation_tags = matches[0]

    factory = osmium.geom.WKBFactory()
    processor = osmium.FileProcessor(str(pbf_path)).with_areas(
        osmium.filter.TagFilter(("boundary", "administrative"))
    )
    for obj in processor:
        if obj.type_str() != "a" or obj.from_way() or obj.orig_id() != relation_id:
            continue
        geometry = shapely_wkb.loads(bytes.fromhex(factory.create_multipolygon(obj)))
        return relation_id, geometry, relation_tags

    raise LookupError(f"relation {relation_id} found but its multipolygon would not assemble")


def buffer_polygon(geometry: BaseGeometry, buffer_m: float) -> BaseGeometry:
    """Buffer a lon/lat polygon by a distance in metres via a metric CRS."""
    import geopandas as gpd

    series = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(C.METRIC_CRS)
    return series.buffer(buffer_m).to_crs("EPSG:4326").iloc[0]


def extract_ways(pbf_path: Path | str, clip: BaseGeometry) -> Extract:
    """Read every highway way whose geometry touches the clip polygon.

    Ways are kept whole: a way that crosses the clip edge stays in the network
    rather than being cut, so no new endpoint geometry is invented (CLAUDE.md
    rule 1) and edge routes are not artificially trapped.
    """
    result = Extract()
    prepared = prep(clip)
    minx, miny, maxx, maxy = clip.bounds

    kept_way_ids: set[int] = set()
    processor = osmium.FileProcessor(str(pbf_path)).with_locations("flex_mem")

    for obj in processor:
        kind = obj.type_str()

        if kind == "n":
            tags = obj.tags
            if "barrier" in tags:
                result.barrier_nodes_seen += 1
                if F.is_blocking_barrier({k: v for k, v in tags}):
                    result.blocking_barrier_nodes.add(obj.id)
            continue

        if kind == "w":
            tags = obj.tags
            if "highway" not in tags:
                continue
            way_id = obj.id
            try:
                coords = [(n.lon, n.lat) for n in obj.nodes if n.location.valid()]
                node_ids = [n.ref for n in obj.nodes]
            except osmium.InvalidLocationError:
                result.dropped_ways.append(
                    {"way_id": way_id, "reason": "missing_node_location",
                     "highway": tags.get("highway", "")}
                )
                continue
            if len(coords) < len(node_ids):
                result.dropped_ways.append(
                    {"way_id": way_id, "reason": "missing_node_location",
                     "highway": tags.get("highway", "")}
                )
                continue
            if len(set(node_ids)) < 2:
                result.dropped_ways.append(
                    {"way_id": way_id, "reason": "degenerate_geometry",
                     "highway": tags.get("highway", "")}
                )
                continue

            if not _touches(coords, prepared, minx, miny, maxx, maxy):
                result.dropped_outside_clip += 1
                result.dropped_ways.append(
                    {"way_id": way_id, "reason": "outside_clip",
                     "highway": tags.get("highway", "")}
                )
                continue

            result.ways[way_id] = WayRecord(way_id, {k: v for k, v in tags}, node_ids)
            kept_way_ids.add(way_id)
            for node_id, (lon, lat) in zip(node_ids, coords):
                result.node_lonlat[node_id] = (lon, lat)
            continue

        if kind == "r":
            if obj.tags.get("type") != "restriction":
                continue
            result.restriction_relations_total += 1
            if any(
                m.type == "w" and m.ref in kept_way_ids for m in obj.members
            ):
                result.restriction_relations_in_clip += 1

    return result


def _touches(coords, prepared, minx, miny, maxx, maxy) -> bool:
    """Cheap bbox reject, then an exact test only for survivors."""
    from shapely.geometry import Point

    for lon, lat in coords:
        if minx <= lon <= maxx and miny <= lat <= maxy:
            if prepared.intersects(Point(lon, lat)):
                return True
    return False


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_extract(extract: Extract, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        pickle.dump(extract, handle, protocol=5)


def load_extract(path: Path) -> Extract:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)
