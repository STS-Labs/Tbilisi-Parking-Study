"""Every number that reaches `reports/00-network-stats.md`.

Computed once, serialised to `data/derived/00-network-stats.json`, and consumed
by both the report and the gate.  Keeping the arithmetic here rather than in the
markdown template means the gate asserts on the same values the reader sees.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import network as N

#: Tags whose presence the stage brief asks the report to measure.
TAG_COMPLETENESS_COLUMNS = ("lanes", "width", "maxspeed", "surface")


def _km(series: pd.Series) -> float:
    return float(series.sum() / 1000.0)


def _segments(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per physical street piece, regardless of how many arcs it carries."""
    return frame.drop_duplicates(subset=["way_id", "seg_index"])


def compute(table: pd.DataFrame, extract, meta: dict) -> dict:
    included = table[~table["excluded"]]
    routable = included[included["in_largest_scc"]]

    stats: dict = {
        "meta": dict(meta),
        "totals": _totals(table, included, routable),
        "headline": {
            "required_traversal_km": N.required_traversal_km(included),
            "required_traversal_km_routable": N.required_traversal_km(routable),
        },
        "by_class": _by_class(table, included),
        "by_min_passes": _by_min_passes(included),
        "oneway": _oneway(included),
        "tagging": _tagging(included),
        "exclusions": _exclusions(table),
        "scc": _scc(table, included),
        "service": _service(table),
        "restrictions": {
            "total_in_source": int(getattr(extract, "restriction_relations_total", 0)),
            "touching_clip": int(getattr(extract, "restriction_relations_in_clip", 0)),
        },
        "dropped_ways": _dropped(extract),
        "capture_quality": _capture_quality(included),
        "gradient": _gradient(included),
    }
    return stats


def _totals(table, included, routable) -> dict:
    return {
        "arc_count": int(len(table)),
        "included_arc_count": int(len(included)),
        "routable_arc_count": int(len(routable)),
        "arc_km": _km(table["length_m"]),
        "included_arc_km": _km(included["length_m"]),
        "routable_arc_km": _km(routable["length_m"]),
        "centerline_km": _km(_segments(table)["length_m"]),
        "included_centerline_km": _km(_segments(included)["length_m"]),
        "routable_centerline_km": _km(_segments(routable)["length_m"]),
        "segment_count": int(len(_segments(table))),
        "included_segment_count": int(len(_segments(included))),
    }


def _by_class(table, included) -> list[dict]:
    rows = []
    for highway_class, group in table.groupby("highway_class", sort=True):
        kept = included[included["highway_class"] == highway_class]
        rows.append(
            {
                "highway_class": str(highway_class),
                "arc_count": int(len(group)),
                "arc_km": _km(group["length_m"]),
                "centerline_km": _km(_segments(group)["length_m"]),
                "included_arc_count": int(len(kept)),
                "included_centerline_km": _km(_segments(kept)["length_m"]),
                "required_km": N.required_traversal_km(kept),
            }
        )
    rows.sort(key=lambda r: (-r["required_km"], r["highway_class"]))
    return rows


def _by_min_passes(included) -> list[dict]:
    rows = []
    for value, group in included.groupby("min_passes", sort=True):
        rows.append(
            {
                "min_passes": int(value),
                "arc_count": int(len(group)),
                "arc_km": _km(group["length_m"]),
                "required_km": N.required_traversal_km(group),
            }
        )
    return rows


def _oneway(included) -> dict:
    segments = _segments(included)
    oneway_segments = segments[segments["oneway"] != "no"]
    total_km = _km(segments["length_m"])
    return {
        "segment_count": int(len(segments)),
        "oneway_segment_count": int(len(oneway_segments)),
        "share_by_count": float(len(oneway_segments) / len(segments)) if len(segments) else 0.0,
        "centerline_km": total_km,
        "oneway_centerline_km": _km(oneway_segments["length_m"]),
        "share_by_length": float(_km(oneway_segments["length_m"]) / total_km) if total_km else 0.0,
        "implied_oneway_segment_count": int(
            len(oneway_segments[oneway_segments["oneway_source"] == "implied"])
        ),
        # Ramps are almost never two-way; a two-way link is either a tagging gap
        # or a genuine slip road, and either way it doubles that arc's cost.
        "two_way_link_segment_count": int(len(_two_way_links(segments))),
        "two_way_link_km": _km(_two_way_links(segments)["length_m"]),
    }


def _two_way_links(segments):
    return segments[
        segments["highway_class"].str.endswith("_link") & (segments["oneway"] == "no")
    ]


def _gradient(included) -> dict:
    """Gradient coverage, and how much of the network reads steeper than drivable.

    SPEC §3.1 lists "incline above a limit" as an exclusion, but §1.1 resolves
    ambiguity toward *more* coverage — and a 30 m DEM over a city of ridges,
    bridges and cuttings is ambiguous.  So a DEM gradient above the limit is
    reported here and never excluded; only a *tagged* incline removes an arc.
    """
    from . import config as C

    gradient = included["gradient_pct"].astype("float64")
    steep = included[gradient.abs() > C.MAX_INCLINE_PCT]
    on_structure = steep[steep["structure"] != ""]
    return {
        "limit_pct": C.MAX_INCLINE_PCT,
        "tag_count": int((included["gradient_source"] == "tag").sum()),
        "dem_count": int((included["gradient_source"] == "dem").sum()),
        "unknown_count": int((included["gradient_source"] == "none").sum()),
        "abs_p50": float(gradient.abs().quantile(0.50)) if len(included) else 0.0,
        "abs_p90": float(gradient.abs().quantile(0.90)) if len(included) else 0.0,
        "abs_p99": float(gradient.abs().quantile(0.99)) if len(included) else 0.0,
        "steep_arc_count": int(len(steep)),
        "steep_km": _km(steep["length_m"]),
        "steep_on_structure_arc_count": int(len(on_structure)),
        "steep_on_structure_km": _km(on_structure["length_m"]),
    }


def _tagging(included) -> dict:
    """Tagging completeness over the *included* network.

    Measuring over every arc would let the ~109k excluded footway, track and path
    arcs dominate: they carry no lane or width tags and no conclusive class, so
    they would both halve every completeness percentage and swamp the
    `min_passes = 2` fallback count that SPEC §2.1 uses to decide whether the
    lane threshold needs calibrating against imagery.
    """
    table = included
    total = len(table)
    out: dict = {"arc_count_basis": int(total)}
    for column in TAG_COMPLETENESS_COLUMNS:
        series = table[column]
        present = series.notna() & (series != "") if series.dtype == object else series.notna()
        out[f"{column}_count"] = int(present.sum())
        out[f"{column}_pct"] = float(present.sum() / total * 100.0) if total else 0.0

    fallback = table[table["min_passes_basis"] == "default"]
    out["default_fallback_arc_count"] = int(len(fallback))
    out["default_fallback_km"] = _km(fallback["length_m"])
    out["default_fallback_pct_of_arcs"] = float(len(fallback) / total * 100.0) if total else 0.0

    by_basis = []
    for basis, group in table.groupby("min_passes_basis", sort=True):
        by_basis.append(
            {"basis": str(basis), "arc_count": int(len(group)), "arc_km": _km(group["length_m"])}
        )
    out["min_passes_basis"] = by_basis

    narrow = table[table["pair_requirement"] > 0]
    out["narrow_pair_segment_count"] = int(len(_segments(narrow)))
    out["narrow_pair_centerline_km"] = _km(_segments(narrow)["length_m"])
    by_narrow_basis = []
    for basis, group in narrow.groupby("narrow_basis", sort=True):
        by_narrow_basis.append(
            {
                "basis": str(basis),
                "segment_count": int(len(_segments(group))),
                "centerline_km": _km(_segments(group)["length_m"]),
            }
        )
    out["narrow_pair_basis"] = by_narrow_basis
    return out


def _exclusions(table) -> list[dict]:
    excluded = table[table["excluded"]]
    rows = []
    for reason, group in excluded.groupby("exclusion_reason", sort=True):
        rows.append(
            {
                "reason": str(reason),
                "arc_count": int(len(group)),
                "arc_km": _km(group["length_m"]),
                "centerline_km": _km(_segments(group)["length_m"]),
                "top_classes": _top_classes(group),
            }
        )
    rows.sort(key=lambda r: (-r["arc_km"], r["reason"]))
    return rows


def _top_classes(group, limit: int = 4) -> list[dict]:
    counts = group.groupby("highway_class")["length_m"].agg(["size", "sum"])
    counts = counts.sort_values("sum", ascending=False).head(limit)
    return [
        {"highway_class": str(idx), "arc_count": int(row["size"]), "arc_km": float(row["sum"] / 1000.0)}
        for idx, row in counts.iterrows()
    ]


def _scc(table, included) -> dict:
    largest = included[included["scc_id"] == 0]
    bridges = included[included["scc_id"] == -1]
    included_km = _km(included["length_m"])

    fragments = []
    for scc_id, group in included[included["scc_id"] > 0].groupby("scc_id", sort=True):
        centroid = group.geometry.union_all().centroid
        names = [n for n in group["name"].tolist() if n]
        fragments.append(
            {
                "scc_id": int(scc_id),
                "arc_count": int(len(group)),
                "arc_km": _km(group["length_m"]),
                "centerline_km": _km(_segments(group)["length_m"]),
                "lon": round(float(centroid.x), 6),
                "lat": round(float(centroid.y), 6),
                "sample_names": sorted(set(names))[:3],
                "classes": sorted(set(group["highway_class"])),
            }
        )
    fragments.sort(key=lambda f: (-f["arc_km"], f["scc_id"]))

    return {
        "component_count": int(included[included["scc_id"] >= 0]["scc_id"].nunique()),
        "largest_arc_count": int(len(largest)),
        "largest_km": _km(largest["length_m"]),
        "largest_share_of_included_km": float(_km(largest["length_m"]) / included_km)
        if included_km
        else 0.0,
        "largest_share_of_included_arcs": float(len(largest) / len(included)) if len(included) else 0.0,
        "bridge_arc_count": int(len(bridges)),
        "bridge_km": _km(bridges["length_m"]),
        "fragment_count": len(fragments),
        "fragment_km": float(sum(f["arc_km"] for f in fragments)),
        "orphan_by_class": _orphan_by_class(included),
        "fragments": fragments,
    }


def _orphan_by_class(included) -> list[dict]:
    orphans = included[included["scc_id"] > 0]
    rows = [
        {"highway_class": str(cls), "arc_count": int(len(group)), "arc_km": _km(group["length_m"])}
        for cls, group in orphans.groupby("highway_class", sort=True)
    ]
    rows.sort(key=lambda r: (-r["arc_km"], r["highway_class"]))
    return rows


def _service_by_type(service: pd.DataFrame, service_required_km: float) -> list[dict]:
    """The `service=*` split. SPEC §2.1 asks a yes/no about a tag that covers
    alleys, driveways and parking aisles alike; the decision needs this table."""
    rows = []
    for subtype, group in service.groupby("service_type", dropna=False, sort=True):
        kept = group[~group["excluded"]]
        required = N.required_traversal_km(kept)
        rows.append(
            {
                "service_type": str(subtype) if subtype is not None else "untagged",
                "arc_count": int(len(group)),
                "included_arc_count": int(len(kept)),
                "centerline_km": _km(_segments(group)["length_m"]),
                "included_centerline_km": _km(_segments(kept)["length_m"]),
                "required_km": required,
                "share_of_service_required": (
                    required / service_required_km if service_required_km else 0.0
                ),
            }
        )
    rows.sort(key=lambda r: (-r["required_km"], r["service_type"]))
    return rows


def _service(table) -> dict:
    service = table[table["highway_class"] == "service"]
    included = service[~service["excluded"]]
    required_km = N.required_traversal_km(included)
    return {
        "by_type": _service_by_type(service, required_km),
        "highway_class": "service",
        "arc_count": int(len(service)),
        "arc_km": _km(service["length_m"]),
        "included_arc_count": int(len(included)),
        "included_centerline_km": _km(_segments(included)["length_m"]),
        "required_km": N.required_traversal_km(included),
    }


def _capture_quality(included) -> list[dict]:
    rows = []
    for quality, group in included.groupby("capture_quality", sort=True):
        rows.append(
            {
                "capture_quality": str(quality),
                "arc_count": int(len(group)),
                "centerline_km": _km(_segments(group)["length_m"]),
                "required_km": N.required_traversal_km(group),
            }
        )
    return rows


def _dropped(extract) -> list[dict]:
    dropped = getattr(extract, "dropped_ways", [])
    counts: dict[str, int] = {}
    for row in dropped:
        counts[row["reason"]] = counts.get(row["reason"], 0) + 1
    return [{"reason": k, "way_count": v} for k, v in sorted(counts.items())]
