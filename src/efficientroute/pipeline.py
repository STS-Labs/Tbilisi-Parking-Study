"""Stage 0 orchestration: raw inputs -> network.gpkg -> report -> map.

Each step persists its output, and every step after the extract reads from disk
rather than rebuilding upstream state (CLAUDE.md working style).  That is also
what makes the determinism gate cheap: the arc table can be rebuilt from the
cached extract in seconds.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import time
import urllib.request
from pathlib import Path

import geopandas as gpd

from . import config as C
from . import dem as D
from . import extract as X
from . import campaign, mapviz, mapviz01, network, report, report01, report02, report03
from . import restrictions, scenarios, servicerole, stats, timemodel, turnaudit, turngraph
from . import zoning
from .congestion import CongestionModel, sensitivity_levels
from .speedmodel import FLAT_STRUCTURES, SpeedModel


def _log(message: str) -> None:
    print(f"[efficientroute] {message}", flush=True)


def ensure_pbf(path: Path = C.PBF_PATH) -> Path:
    if path.exists():
        return path
    _log(f"downloading {C.PBF_URL}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with urllib.request.urlopen(C.PBF_URL) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(path)
    return path


def save_boundary(path: Path, relation_id: int, geometry, tags: dict) -> Path:
    """Cache the municipality boundary alongside the relation id it came from."""
    keep = {
        k: v
        for k, v in tags.items()
        if k in {"name", "name:en", "int_name", "admin_level", "boundary", "ISO3166-2", "wikidata"}
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(
        {
            "relation_id": [int(relation_id)],
            "tags": [json.dumps(keep, ensure_ascii=False, sort_keys=True)],
        },
        geometry=[geometry],
        crs="EPSG:4326",
    ).to_file(path, driver="GeoJSON")
    return path


def load_boundary(path: Path) -> tuple[int, object, dict]:
    """Read the cached boundary back.

    The GeoJSON driver infers field types, so a property written as a JSON string
    can come back already parsed into a dict.  Accept both rather than assuming.
    """
    row = gpd.read_file(path).iloc[0]
    raw = row["tags"]
    tags = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else dict(raw or {})
    return int(row["relation_id"]), row.geometry, tags


def ensure_boundary(pbf_path: Path, path: Path = C.BOUNDARY_PATH) -> tuple[int, object, dict]:
    """Locate and cache the municipality boundary, recording the relation id."""
    if path.exists():
        return load_boundary(path)

    _log("locating the Tbilisi administrative boundary relation in the PBF")
    relation_id, geometry, tags = X.find_admin_boundary(pbf_path)
    save_boundary(path, relation_id, geometry, tags)
    _log(f"boundary = OSM relation {relation_id}")
    return load_boundary(path)


def ensure_dem(bounds: tuple[float, float, float, float]) -> tuple[D.BilinearSampler, list[str]]:
    tiles = D.srtm_tiles_for_bbox(*bounds)
    for tile in tiles:
        if not D.tile_path(tile).exists():
            _log(f"downloading DEM tile {tile}")
            D.download_tile(tile)
    return D.mosaic(tiles), tiles


def build_extract(pbf_path: Path, force: bool = False) -> X.Extract:
    if C.EXTRACT_PATH.exists() and not force:
        _log(f"reusing cached extract {C.EXTRACT_PATH}")
        return X.load_extract(C.EXTRACT_PATH)

    relation_id, boundary, boundary_tags = ensure_boundary(pbf_path)
    _log(f"buffering the boundary by {C.CLIP_BUFFER_M:.0f} m")
    clip = X.buffer_polygon(boundary, C.CLIP_BUFFER_M)

    _log("reading ways, node locations, barriers and restriction relations")
    started = time.time()
    extract = X.extract_ways(pbf_path, clip)
    _log(
        f"kept {len(extract.ways):,} highway ways "
        f"({extract.dropped_outside_clip:,} outside the clip) in {time.time() - started:.0f}s"
    )

    extract.boundary_relation_id = relation_id
    extract.boundary_wkb = boundary.wkb
    extract.clip_wkb = clip.wkb
    extract.source = {
        "pbf_url": C.PBF_URL,
        "pbf_sha256": X.file_digest(pbf_path),
        "pbf_bytes": pbf_path.stat().st_size,
        "boundary_relation_id": relation_id,
        "boundary_tags": boundary_tags,
        "clip_buffer_m": C.CLIP_BUFFER_M,
    }
    X.save_extract(extract, C.EXTRACT_PATH)
    return extract


def rebuild_arc_table():
    """Rebuild the arc table from cached inputs, exactly as the pipeline would.

    The determinism gate uses this: rebuilding through the same DEM sampling and
    component labelling is the only rebuild that proves anything.

    Stage 2 writes three more columns into the same layer, so once it has run,
    "the artifact the pipeline produces" includes them and the rebuild has to as
    well.  That is sound rather than circular: the Stage 2 columns are a pure
    function of the Stage 0 table and of the *persisted model coefficients*, and
    neither this function nor `timemodel.augment` reads the GeoPackage it is
    being checked against.  It also means a Stage 6 refit propagates by rerunning
    Stage 2, not by editing code.
    """
    extract = X.load_extract(C.EXTRACT_PATH)
    sampler, _ = ensure_dem(extract.clip.bounds)
    table = network.build_arc_table(extract, sampler=sampler)
    if C.TIME_MODEL_JSON.exists():
        table = timemodel.augment(table, timemodel.load_model())
    return table


def run(force_extract: bool = False) -> dict:
    started = time.time()
    pbf_path = ensure_pbf()
    extract = build_extract(pbf_path, force=force_extract)

    clip = extract.clip
    sampler, tiles = ensure_dem(clip.bounds)

    _log("building the directed arc table")
    table = network.build_arc_table(extract, sampler=sampler)
    _log(f"{len(table):,} directed arcs")

    network.write_gpkg(table, C.NETWORK_GPKG)
    _log(f"wrote {C.NETWORK_GPKG}")
    _invalidate_stage2()

    _write_dropped_ways(extract)

    meta = dict(extract.source)
    meta.update(
        {
            "dem_source": "SRTM 1-arcsec (elevation-tiles-prod skadi)",
            "dem_tiles": tiles,
            "dem_note": (
                "Copernicus GLO-30 has no tiles over N41/E044 and N41/E045; SRTM "
                "1-arcsec is the stage brief's alternative at the same 30 m resolution."
            ),
            "clip_bounds": [round(v, 6) for v in clip.bounds],
            "boundary_area_km2": _area_km2(extract.boundary),
            "clip_area_km2": _area_km2(clip),
            "arcs_sha256": X.file_digest(C.NETWORK_GPKG),
            "runtime_s": round(time.time() - started, 1),
        }
    )

    summary = stats.compute(table, extract, meta)
    if C.SERVICE_SCENARIOS_JSON.exists():
        summary["service_scenarios"] = json.loads(C.SERVICE_SCENARIOS_JSON.read_text())
    C.STATS_JSON.parent.mkdir(parents=True, exist_ok=True)
    C.STATS_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    C.MANIFEST_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False))

    report.write(summary, C.REPORT_MD)
    _log(f"wrote {C.REPORT_MD}")
    mapviz.write(table, extract, summary, C.REPORT_HTML)
    _log(f"wrote {C.REPORT_HTML}")

    _log(f"done in {time.time() - started:.0f}s")
    return summary


def _invalidate_stage2() -> None:
    """Stage 2 writes three columns into Stage 0's own layer, so rebuilding that
    layer removes them.  Leaving `02-time-model.json` behind would then describe
    an artifact that no longer exists — and `rebuild_arc_table` would re-apply
    coefficients to a table the committed GeoPackage does not carry, failing the
    determinism gate for a reason that has nothing to do with determinism.

    So Stage 0 drops the stale Stage 2 artifact and says it did.  `data/derived`
    is regenerable by design (CLAUDE.md); `make stage2` puts it back.
    """
    if C.TIME_MODEL_JSON.exists():
        C.TIME_MODEL_JSON.unlink()
        _log(
            f"removed the now-stale {C.TIME_MODEL_JSON.name} — the Stage 2 columns "
            "were rebuilt away; re-run `make stage2`"
        )


def _write_dropped_ways(extract: X.Extract) -> None:
    """Machine-readable drop log (CLAUDE.md rule 4).

    `outside_clip` rows are the clip definition rather than a data-quality
    finding, so they are counted in the report and omitted from the CSV, which
    would otherwise be dominated by every road in Georgia.
    """
    import csv

    rows = [r for r in extract.dropped_ways if r["reason"] != "outside_clip"]
    C.DROPPED_WAYS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with C.DROPPED_WAYS_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["way_id", "reason", "highway"])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["reason"], r["way_id"])))


def _area_km2(geometry) -> float:
    series = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(C.METRIC_CRS)
    return round(float(series.area.iloc[0] / 1e6), 2)


# ============================================================ Stage 1 — L(G)


def run_stage1() -> dict:
    """Build L(G), prove it legal, and report what is broken."""
    started = time.time()
    if not C.NETWORK_GPKG.exists():
        raise FileNotFoundError(
            f"{C.NETWORK_GPKG} missing — Stage 1 depends on the Stage 0 gate having passed"
        )

    _log("loading the Stage 0 arc table")
    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    network_ways = set(routable["way_id"].astype(int))
    _log(f"{len(routable):,} routable arcs over {len(network_ways):,} ways")

    _log("parsing type=restriction relations")
    parsed = restrictions.parse_restrictions(C.PBF_PATH, network_ways)
    _log(
        f"{parsed.found:,} touch the network; {len(parsed.applicable):,} bind a car "
        f"({parsed.via_way_count} via-way), {len(parsed.skipped):,} skipped"
    )

    _log("building L(G)")
    graph = turngraph.build_turn_graph(arcs, parsed)
    _log(f"|V(L)| = {graph.n_nodes:,}   |E(L)| = {graph.n_edges:,}")

    extract = X.load_extract(C.EXTRACT_PATH)
    boundary = extract.boundary

    _log("auditing strong components of L")
    audit = turnaudit.audit(graph, node_lonlat=extract.node_lonlat, clip=extract.clip)
    lost_ids = [row["arc_id"] for row in audit["scc"]["lost_rows"]]
    _log(f"attributing {len(lost_ids)} unreachable arcs to a cause")
    causes = turnaudit.attribute_losses(arcs, parsed, lost_ids, boundary=boundary)
    audit["lost_detail"] = [
        dict(row, cause=causes.get(row["arc_id"], "unknown")) for row in audit["scc"]["lost_rows"]
    ]
    audit["loss_causes"] = _cause_summary(audit["lost_detail"])

    _log("measuring the SPEC-literal mainline-entry rule")
    audit["mainline_variants"] = _mainline_variants(arcs, parsed)

    audit["meta"] = {
        "routable_arcs": int(len(routable)),
        "restrictions_found": parsed.found,
        "restrictions_applicable": len(parsed.applicable),
        "restrictions_skipped": len(parsed.skipped),
        "restrictions_skipped_by_reason": parsed.skipped_by_reason,
        "mainline_entry_via_ramps_only": graph.meta["mainline_entry_via_ramps_only"],
        "pbf_path": str(C.PBF_PATH.name),
        "runtime_s": 0.0,
    }
    audit["spotchecks"] = report01.load_spotchecks()

    graph.save(C.TURN_GRAPH_PATH)
    _log(f"wrote {C.TURN_GRAPH_PATH}")
    _write_stage1_csvs(graph, parsed, audit)

    audit["meta"]["runtime_s"] = round(time.time() - started, 1)
    C.TURN_STATS_JSON.write_text(json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False))
    report01.write(audit, C.TURN_REPORT_MD)
    _log(f"wrote {C.TURN_REPORT_MD}")

    restricted_nodes = {
        r["osm_node"] for r in graph.restriction_log if r["status"] == "applied" and r["osm_node"] > 0
    }
    mapviz01.write(arcs, graph, audit, restricted_nodes, extract.node_lonlat, C.TURN_REPORT_HTML)
    _log(f"wrote {C.TURN_REPORT_HTML}")
    _log(f"done in {time.time() - started:.0f}s")
    return audit


def _cause_summary(rows: list[dict]) -> list[dict]:
    totals: dict[str, list] = {}
    for row in rows:
        entry = totals.setdefault(row["cause"], [0, 0.0])
        entry[0] += 1
        entry[1] += row["length_m"] / 1000.0
    return sorted(
        ({"cause": k, "arc_count": v[0], "arc_km": round(v[1], 3)} for k, v in totals.items()),
        key=lambda r: -r["arc_km"],
    )


def _mainline_variants(arcs, parsed) -> list[dict]:
    """SPEC §3.3 names motorway *and* trunk; measure what each choice costs."""
    out = []
    for classes in (frozenset(), frozenset({"motorway"}), frozenset({"motorway", "trunk"})):
        graph = turngraph.build_turn_graph(arcs, parsed, mainline_entry_classes=classes)
        summary = turnaudit.audit(graph)["scc"]
        out.append(
            {
                "classes": sorted(classes),
                "edges": graph.n_edges,
                "share_of_required_km": summary["share_of_required_km"],
                "required_km_lost": summary["required_km_lost"],
                "lost_arc_count": summary["lost_arc_count"],
            }
        )
    return out


def _write_stage1_csvs(graph, parsed, audit) -> None:
    import csv

    with C.TURN_RESTRICTIONS_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["relation_id", "kind", "manoeuvre", "via", "status", "osm_node",
                        "edges_removed", "edges_already_absent", "clones_created", "detail"],
        )
        writer.writeheader()
        writer.writerows(sorted(graph.restriction_log, key=lambda r: r["relation_id"]))

    with C.TURN_UNPARSED_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["relation_id", "reason", "detail"])
        writer.writeheader()
        writer.writerows(sorted(parsed.skipped, key=lambda r: (r["reason"], r["relation_id"])))

    with C.TURN_TRAPS_CSV.open("w", newline="") as handle:
        rows = audit["traps"]["rows"]
        writer = csv.DictWriter(
            handle,
            fieldnames=["kind", "arc_id", "variant", "way_id", "highway_class", "name",
                        "length_m", "from_node", "to_node", "trap_cause",
                        "trap_cause_rule", "dangling_node", "clip_edge_distance_m"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


# ================================================== Stage 0b — service scope


def run_stage0b() -> dict:
    """Measure the `highway=service` subtag split and the A/B/C scope scenarios.

    A patch to Stages 0 and 1, not a new stage: it changes no classification and
    no default.  Variant A is what the pipeline builds and stays that way.
    """
    started = time.time()
    for required in (C.NETWORK_GPKG, C.EXTRACT_PATH):
        if not required.exists():
            raise FileNotFoundError(f"{required} missing — run `make stage0` first")

    _log("loading the arc table")
    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    if "service_type" not in arcs.columns:
        raise RuntimeError(
            "network.gpkg predates the service_type column — re-run `make stage0`"
        )

    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    _log("parsing restrictions so each variant gets a real L(G) node count")
    parsed = restrictions.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))

    _log("evaluating service scope variants A / B / C")
    rows = scenarios.compare(arcs, parsed)
    for row in rows:
        _log(
            f"  {row['variant']}: {row['required_traversal_km']:,.1f} km required, "
            f"{row['included_arc_count']:,} arcs, |V(L)| {row.get('l_nodes', 0):,}"
        )

    payload = {"variants": rows, "runtime_s": round(time.time() - started, 1)}
    C.SERVICE_SCENARIOS_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True))
    _log(f"wrote {C.SERVICE_SCENARIOS_JSON}")

    _log("regenerating the Stage 0 report with the subtag breakdown")
    summary = json.loads(C.STATS_JSON.read_text())
    summary["service"] = stats.compute(arcs, X.load_extract(C.EXTRACT_PATH), summary["meta"])["service"]
    summary["service_scenarios"] = payload
    C.STATS_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    report.write(summary, C.REPORT_MD)
    _log(f"wrote {C.REPORT_MD}")
    return payload


# ============================================== Stage 2 — time & capture model


def run_stage2() -> dict:
    """Turn kilometres into hours, and build the model so Stage 6 can refit it."""
    started = time.time()
    for required in (C.NETWORK_GPKG, C.TURN_GRAPH_PATH):
        if not required.exists():
            raise FileNotFoundError(
                f"{required} missing — Stage 2 depends on the Stage 0 and Stage 1 gates"
            )

    _log("loading the arc table and L(G)")
    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    graph = turngraph.load(C.TURN_GRAPH_PATH)

    model = SpeedModel.from_config()
    congestion = CongestionModel.from_config()

    _log("item 0 — classifying service roads by connectivity")
    arcs = timemodel.augment(arcs, model)
    role_summary = servicerole.summarise(arcs)
    for label, block in role_summary.items():
        reference = servicerole.REFERENCE_KM[label]
        deltas = {
            row["service_role"]: row["centerline_km"] - reference[row["service_role"]]
            for row in block["rows"]
        }
        _log(f"  {label}: {block['centerline_km']:,.1f} km, vs reference " +
             ", ".join(f"{k} {v:+.1f}" for k, v in deltas.items()))

    _log("item 1 — writing capture_speed_kmh and capture_time_s back to network.gpkg")
    network.write_gpkg(arcs, C.NETWORK_GPKG)

    included = arcs[~arcs["excluded"]]
    _log(f"  {len(included):,} included arcs, {timemodel.capture_hours(included):,.1f} capture hours at free flow")

    _log("item 3 — preparing turn time and depot distance")
    prepared = campaign.prepare(arcs, graph)

    _log("evaluating scope variants " + "/".join(C.STAGE2_SCOPE_VARIANTS))
    variants = campaign.scope_variants(prepared, model, congestion)
    for row in variants:
        _log(
            f"  {row['variant']}: {row['required_km']:,.1f} km  "
            f"{row['work_hours']:,.1f} h  {row['days']:.1f} days"
        )

    baseline_frame = prepared[~prepared["excluded"]]
    _log("item 2 — sweeping the congestion assumption and the turn-time range")
    sweep = campaign.sensitivity(model, baseline_frame)

    payload = {
        "speed_model": model.to_dict(),
        "congestion_model": congestion.to_dict(),
        "service_role": role_summary,
        "service_role_reference": servicerole.REFERENCE_KM,
        "speed": _speed_diagnostics(included, model),
        "gradient": _gradient_diagnostics(included, model),
        "surface": _surface_diagnostics(included, model),
        "width": _width_diagnostics(included, model),
        "turn": _turn_diagnostics(prepared, graph),
        "day": {
            "shift_hours": C.SHIFT_HOURS,
            "break_hours": C.BREAK_HOURS,
            "depot_lat": C.DEPOT_LAT,
            "depot_lon": C.DEPOT_LON,
            "detour_factor": C.DEPOT_DETOUR_FACTOR,
            "leg_speed_kmh_baseline": campaign.leg_speed_kmh(congestion),
            "distance_bands_km": list(C.DEPOT_DISTANCE_BANDS_KM),
        },
        "campaign": {
            "variants": variants,
            "sensitivity": sweep,
            "sensitivity_levels": sensitivity_levels(),
            "deadhead_illustration": campaign.deadhead_illustration(variants[0]["days"]),
            "turn_sensitivity": campaign.turn_sensitivity(baseline_frame, model, congestion),
            "daylight": _daylight_check(variants),
        },
        "capture_hours": timemodel.capture_hours(included),
        "meta": {
            "arcs_sha256": X.file_digest(C.NETWORK_GPKG),
            "included_arc_count": int(len(included)),
            "required_traversals": int(timemodel.required_traversals(included).sum()),
            "runtime_s": round(time.time() - started, 1),
        },
    }
    C.TIME_MODEL_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    _log(f"wrote {C.TIME_MODEL_JSON}")

    report02.write(payload, C.TIME_REPORT_MD)
    _log(f"wrote {C.TIME_REPORT_MD}")
    _log(f"done in {time.time() - started:.0f}s")
    return payload


def _weighted_speed(frame, speed) -> float:
    """Harmonic mean — the speed that reproduces the hours, not the arithmetic one."""
    import numpy as np

    traversals = timemodel.required_traversals(frame)
    km = frame["length_m"].to_numpy(dtype="float64") / 1000.0 * traversals
    hours = (km / speed).sum()
    return float(km.sum() / hours) if hours else 0.0


def _speed_diagnostics(included, model) -> dict:
    import numpy as np

    speed = included["capture_speed_kmh"].to_numpy(dtype="float64")
    traversals = timemodel.required_traversals(included)
    required = traversals > 0
    uncapped = model.unconstrained_kmh(included)
    binds = required & (uncapped > model.capture_speed_max_kmh) & (
        included["capture_quality"].to_numpy() != "reduced"
    )
    km = included["length_m"].to_numpy(dtype="float64") / 1000.0

    rows = []
    for highway_class, group in included.groupby("highway_class", sort=True):
        group_required = timemodel.required_traversals(group)
        group_km = float((group["length_m"].to_numpy() / 1000.0 * group_required).sum())
        if group_km <= 0:
            continue
        hours = float(
            (group["capture_time_s"].to_numpy(dtype="float64") * group_required).sum() / 3600.0
        )
        rows.append(
            {
                "highway_class": str(highway_class),
                "required_km": group_km,
                "capture_hours": hours,
                "mean_capture_kmh": group_km / hours if hours else 0.0,
                "base_free_flow_kmh": model.base_free_flow_kmh.get(
                    str(highway_class), model.default_free_flow_kmh
                ),
            }
        )
    rows.sort(key=lambda r: -r["capture_hours"])
    return {
        "by_class": rows,
        "mean_capture_kmh": _weighted_speed(included, speed),
        "p10_kmh": float(np.percentile(speed[required], 10)),
        "p50_kmh": float(np.percentile(speed[required], 50)),
        "p90_kmh": float(np.percentile(speed[required], 90)),
        "cap_binds_required_km": float((km[binds] * traversals[binds]).sum()),
        "cap_binds_arc_count": int(binds.sum()),
        "maxspeed_tagged_arc_count": int(included["maxspeed"].notna().sum()),
        "maxspeed_tagged_share": float(included["maxspeed"].notna().mean()),
    }


def _gradient_diagnostics(included, model) -> dict:
    import numpy as np

    raw = np.abs(included["gradient_pct"].to_numpy(dtype="float64"))
    effective = np.abs(model.effective_gradient_pct(included))
    traversals = timemodel.required_traversals(included)

    def hours(candidate) -> float:
        seconds = candidate.capture_time_s(included)
        return float((seconds * traversals).sum() / 3600.0)

    baseline = hours(model)
    return {
        "raw_abs_p50": float(np.nanpercentile(raw, 50)),
        "raw_abs_p90": float(np.nanpercentile(raw, 90)),
        "effective_abs_p50": float(np.percentile(effective, 50)),
        "effective_abs_p90": float(np.percentile(effective, 90)),
        "share_zeroed_by_deadband": float(np.mean(effective == 0.0)),
        "share_at_cap": float(np.mean(effective >= model.gradient_cap_pct - 1e-9)),
        "hours_baseline": baseline,
        "hours_without_deadband": hours(model.replace(gradient_dem_noise_m=0.0)),
        "hours_without_gradient_term": hours(
            model.replace(
                gradient_uphill_decay_per_pct=0.0, gradient_downhill_decay_per_pct=0.0
            )
        ),
        "dem_noise_m": model.gradient_dem_noise_m,
        "structure_arc_count": int(included["structure"].isin(list(FLAT_STRUCTURES)).sum()),
    }


def _surface_diagnostics(included, model) -> dict:
    import numpy as np

    traversals = timemodel.required_traversals(included)
    km = included["length_m"].to_numpy(dtype="float64") / 1000.0 * traversals
    surface = included["surface"].fillna("").to_numpy()
    tagged = np.array([s in model.surface_factor for s in surface])

    factors = np.array(
        [model.surface_factor.get(s, np.nan) for s in surface], dtype="float64"
    )
    tagged_km = float(km[tagged].sum())
    tagged_mean = float((factors[tagged] * km[tagged]).sum() / tagged_km) if tagged_km else 1.0

    def hours(candidate) -> float:
        return float((candidate.capture_time_s(included) * traversals).sum() / 3600.0)

    rows = []
    for value in sorted(set(surface)):
        mask = surface == value
        rows.append(
            {
                "surface": value or "(untagged)",
                "required_km": float(km[mask].sum()),
                "factor": model.surface_factor.get(value, model.default_surface_factor),
                "tagged": bool(value in model.surface_factor),
            }
        )
    rows = [r for r in rows if r["required_km"] > 0]
    rows.sort(key=lambda r: -r["required_km"])

    return {
        "by_surface": rows,
        "untagged_required_km": float(km[~tagged].sum()),
        "untagged_share_of_required_km": float(km[~tagged].sum() / km.sum()) if km.sum() else 0.0,
        "tagged_weighted_mean_factor": tagged_mean,
        "hours_baseline": hours(model),
        "hours_if_untagged_matched_tagged": hours(
            model.replace(default_surface_factor=tagged_mean)
        ),
    }


def _width_diagnostics(included, model) -> dict:
    traversals = timemodel.required_traversals(included)
    narrow = model.is_narrow(included)
    km = included["length_m"].to_numpy(dtype="float64") / 1000.0 * traversals

    def hours(candidate) -> float:
        return float((candidate.capture_time_s(included) * traversals).sum() / 3600.0)

    return {
        "narrow_arc_count": int(narrow.sum()),
        "narrow_required_km": float(km[narrow].sum()),
        "width_tagged_share": float(included["width"].notna().mean()),
        "hours_baseline": hours(model),
        "hours_without_width_term": hours(model.replace(narrow_width_factor=1.0)),
    }


def _turn_diagnostics(prepared, graph) -> dict:
    import numpy as np

    included = prepared[~prepared["excluded"]]
    traversals = timemodel.required_traversals(included)
    mean_s = included["turn_mean_s"].to_numpy(dtype="float64")
    min_s = included["turn_min_s"].to_numpy(dtype="float64")
    in_l = set(arc_id for arc_id, _ in graph.node_ids)
    missing = ~included["arc_id"].isin(in_l).to_numpy()

    counts: dict[str, int] = {}
    for row in graph.adjacency:
        for code, _penalty in row.values():
            name = turngraph.TURN_CLASSES[code]
            counts[name] = counts.get(name, 0) + 1

    return {
        "penalties_s": dict(C.TURN_PENALTY_S),
        "manoeuvres_by_class": dict(sorted(counts.items())),
        "mean_exit_s": float(np.average(mean_s, weights=traversals)) if traversals.sum() else 0.0,
        "min_exit_s": float(np.average(min_s, weights=traversals)) if traversals.sum() else 0.0,
        "hours_mean": float((mean_s * traversals).sum() / 3600.0),
        "hours_floor": float((min_s * traversals).sum() / 3600.0),
        "arcs_absent_from_l": int(missing.sum()),
        "arcs_absent_from_l_required_km": float(
            (included["length_m"].to_numpy()[missing] / 1000.0 * traversals[missing]).sum()
        ),
    }


def _daylight_check(variants: list[dict]) -> dict:
    """SPEC §7.3 asks Stage 2 whether its estimate pushes the finish past October."""
    import datetime as _dt

    start = _dt.date.fromisoformat(C.CAMPAIGN_START_DATE)
    binding = _dt.date.fromisoformat(C.DAYLIGHT_BINDING_DATE)
    window = (binding - start).days
    rows = []
    for row in variants:
        days = row["days_rounded"]
        rows.append(
            {
                "variant": row["variant"],
                "days_rounded": days,
                "finish_date": (start + _dt.timedelta(days=days - 1)).isoformat()
                if days else None,
                "slack_days": window - days if days else None,
                "inside_window": bool(days is not None and days <= window),
                # The campaign estimate counts capture and turn time only.  This
                # is the deadhead the variant can absorb before the finish
                # crosses the date at which sunset stops covering the shift.
                "deadhead_headroom": (window / row["days"] - 1.0) if row["days"] else None,
            }
        )
    return {
        "campaign_start": C.CAMPAIGN_START_DATE,
        "daylight_binding_date": C.DAYLIGHT_BINDING_DATE,
        "window_days": window,
        "working_days_per_week": C.WORKING_DAYS_PER_WEEK,
        "variants": rows,
    }


# ================================================== Stage 3 — bounds & tour


def rewrite_stage3_report() -> dict:
    """Re-render the Stage 3 report from the artifact, without re-solving.

    Stage 3 takes twelve minutes, almost all of it in two exact solvers whose
    answers do not change.  Re-running them to reword a paragraph would be a good
    way to end up not rewording the paragraph.  The artifact is the source of
    every number either way, so this changes nothing about what is reported.
    """
    if not C.BOUNDS_JSON.exists():
        raise FileNotFoundError(f"{C.BOUNDS_JSON} missing — run `make stage3` first")
    payload = json.loads(C.BOUNDS_JSON.read_text())
    report03.write(payload, C.BOUNDS_REPORT_MD)
    _log(f"wrote {C.BOUNDS_REPORT_MD}")
    return payload


def run_stage3(variants: tuple[str, ...] = C.STAGE2_SCOPE_VARIANTS) -> dict:
    """Bound the problem from both sides, and build one real tour of the city."""
    started = time.time()
    for required in (C.NETWORK_GPKG, C.TIME_MODEL_JSON):
        if not required.exists():
            raise FileNotFoundError(
                f"{required} missing — Stage 3 depends on the Stage 2 gate having passed"
            )

    _log("loading the arc table")
    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    if not timemodel.has_stage2_columns(arcs):
        raise RuntimeError("network.gpkg predates the Stage 2 columns — run `make stage2`")
    model = timemodel.load_model()

    _log("parsing type=restriction relations once for every variant")
    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    parsed = restrictions.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))

    results = []
    for variant in variants:
        _log(f"=== variant {variant} — {scenarios.VARIANT_LABELS[variant]}")
        results.append(_solve_variant(arcs, parsed, model, variant))

    payload = {
        "variants": results,
        "stage2": _stage2_comparison(),
        "day": {
            "productive_hours": C.STAGE3_PRODUCTIVE_HOURS,
            "shift_hours": C.SHIFT_HOURS,
            "break_hours": C.BREAK_HOURS,
            "extended_shift_hours": C.STAGE3_EXTENDED_SHIFT_HOURS,
            "extended_productive_hours": C.STAGE3_EXTENDED_PRODUCTIVE_HOURS,
        },
        "spec_note": (
            "SPEC v0.3 §4 labelled the fixed-orientation DCPP result 'Stage A — "
            "Lower bound' and I5 asserted total driving was at or above it. Fixing "
            "an orientation adds a constraint, so that result can only bound the "
            "optimum from ABOVE. SPEC v0.4 corrects both: §4 Stage A now brackets "
            "the optimum with a constructive upper bound and an LP lower bound, and "
            "I5 asserts total driving lies within that bracket. Stage 3 implements "
            "the corrected form; the bracket below is what I5 refers to."
        ),
        "meta": {
            "arcs_sha256": X.file_digest(C.NETWORK_GPKG),
            "runtime_s": round(time.time() - started, 1),
        },
    }
    C.BOUNDS_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    _log(f"wrote {C.BOUNDS_JSON}")

    report03.write(payload, C.BOUNDS_REPORT_MD)
    _log(f"wrote {C.BOUNDS_REPORT_MD}")
    _log(f"done in {time.time() - started:.0f}s")
    return payload


def _stage2_comparison() -> dict:
    """The Stage 2 figures Stage 3 is answerable to.

    Stage 2's campaign estimate counted capture and turn time and called itself a
    floor.  Stage 3 supplies the term it was missing, so the two have to be laid
    side by side — including the daylight window, which Stage 2 could only express
    as "how much deadhead would fit".
    """
    if not C.TIME_MODEL_JSON.exists():
        return {}
    stage2 = json.loads(C.TIME_MODEL_JSON.read_text())
    campaign = stage2["campaign"]
    daylight = campaign["daylight"]
    return {
        "capture_hours_free_flow": stage2["capture_hours"],
        "turn_hours_estimate": stage2["turn"]["hours_mean"],
        "turn_hours_floor": stage2["turn"]["hours_floor"],
        "variants": {
            row["variant"]: {
                "capture_hours": row["capture_hours"],
                "turn_hours": row["turn_hours"],
                "work_hours": row["work_hours"],
                "days": row["days"],
            }
            for row in campaign["variants"]
        },
        "daylight_window_days": daylight["window_days"],
        "campaign_start": daylight["campaign_start"],
        "daylight_binding_date": daylight["daylight_binding_date"],
        "deadhead_headroom": {
            row["variant"]: row["deadhead_headroom"] for row in daylight["variants"]
        },
    }


def _solve_variant(arcs, parsed, model, variant: str) -> dict:
    """Orientation → node split → min-cost flow → Euler circuit → bounds."""
    import numpy as np

    from . import dcpp, euler, lowerbound, lstar, orientation, tourcheck, tourio

    started = time.time()
    frame = scenarios.apply_variant(arcs, variant)
    included = frame[~frame["excluded"]]
    required_km_total = network.required_traversal_km(included)

    _log("  building L(G) for this scope")
    graph = turngraph.build_turn_graph(frame, parsed)

    by_arc = frame.set_index("arc_id")
    rows = by_arc.loc[graph.arc_index["arc_id"].to_numpy()]
    capture_s = rows["capture_time_s"].to_numpy(dtype="float64")
    deadhead_s = model.deadhead_time_s(rows)
    length_m = rows["length_m"].to_numpy(dtype="float64")

    _log("  finding the strongly connected component a closed tour lives in")
    keep = lstar.largest_strong_component(graph)
    _log(f"  {int(keep.sum()):,} of {graph.n_nodes:,} L-nodes are tourable")

    _log("  orienting narrow pairs")
    oriented = orientation.orient(graph.arc_index, keep=keep)

    star = lstar.build(graph, capture_s, deadhead_s, oriented.lower, keep=keep)
    _log(f"  L*: {star.n_nodes:,} nodes, {star.n_edges:,} edges")

    _log("  solving the min-cost flow with lower bounds")
    flow = dcpp.solve(star)
    _log(
        f"  balance {flow.balance_cost_ms / 3.6e6:,.1f} h + connectivity "
        f"{flow.connectivity_cost_ms / 3.6e6:,.1f} h over {flow.rounds} rounds "
        f"({flow.components_initial:,} components initially)"
    )

    _log("  extracting the Euler circuit")
    tour = euler.tour(star, flow.x)
    _log(f"  {len(tour):,} arc traversals")

    _log("  auditing the tour against I1, I2, I6 and closure")
    audit = tourcheck.audit(tour, star, graph)
    audit.raise_if_failed()
    match = tourcheck.check_matches_flow(audit.visit_counts, flow.x, star)
    if not match.passed:
        raise AssertionError(f"the tour does not match the flow it was built from: {match.detail}")

    _log("  computing the lower bound")
    lp, fallback = lowerbound.compute(star, graph, C.LP_TIME_LIMIT_S)
    lower_s = lp.value_s if lp.status == "optimal" else fallback.value_s
    method = lp.method if lp.status == "optimal" else fallback.method
    _log(f"  lower bound {lower_s / 3600:,.1f} h by {method}")

    upper_s = audit.total_s
    driven_km = float((audit.visit_counts * length_m).sum() / 1000.0)
    required_km_in_scope = _required_km_in_scope(star, length_m, star.in_scope)
    # Two different losses, with two different causes and two different owners.
    required_km_in_l = _required_km_in_scope(star, length_m, np.ones(graph.n_nodes, dtype=bool))

    result: dict = {
        "variant": variant,
        "label": scenarios.VARIANT_LABELS[variant],
        "capture_h": audit.capture_s / 3600.0,
        "turn_h": audit.turn_s / 3600.0,
        "deadhead_h": audit.deadhead_s / 3600.0,
        "total_h": upper_s / 3600.0,
        "deadhead_pct_of_capture": audit.deadhead_s / audit.capture_s * 100.0,
        "deadhead_pct_of_total": audit.deadhead_s / upper_s * 100.0,
        "lower_bound_h": lower_s / 3600.0,
        "lower_bound_method": method,
        "optimality_gap": lowerbound.optimality_gap(upper_s, lower_s),
        "days": upper_s / 3600.0 / C.STAGE3_PRODUCTIVE_HOURS,
        "days_extended_shift": upper_s / 3600.0 / C.STAGE3_EXTENDED_PRODUCTIVE_HOURS,
        "arc_traversals": int(len(tour)),
        "driven_km": driven_km,
        "required_km_total": required_km_total,
        "required_km_in_scope": required_km_in_scope,
        "required_km_out_of_scope": required_km_total - required_km_in_scope,
        # Never entered L at all: outside the *base network's* largest strongly
        # connected component, which is a Stage 0 finding.
        "required_km_absent_from_l": required_km_total - required_km_in_l,
        # In L, but outside L's own largest strong component: a legal trap,
        # enterable but not leavable or the reverse. Stage 1 attributed these.
        "required_km_trapped_in_l": required_km_in_l - required_km_in_scope,
        "km_deadhead_ratio": (driven_km - required_km_in_scope) / required_km_in_scope,
        "l_nodes": int(graph.n_nodes),
        "l_nodes_tourable": int(keep.sum()),
        "l_star_nodes": int(star.n_nodes),
        "l_star_edges": int(star.n_edges),
        "l_star_manoeuvres": int(star.n_manoeuvres),
        "orientation": oriented.to_dict(),
        "flow": flow.to_dict(),
        "lower_bound_lp": lp.to_dict(),
        "lower_bound_fallback": fallback.to_dict(),
        "invariants": [
            {"name": check.name, "passed": bool(check.passed), "detail": check.detail}
            for check in (*audit.checks, match)
        ],
        "runtime_s": round(time.time() - started, 1),
    }

    tour_path = Path(str(C.TOUR_NPZ).format(variant=variant))
    np.savez_compressed(
        tour_path,
        tour=tour.astype("int32"),
        lower=star.lower.astype("int32"),
        keep=keep,
        flow=flow.x.astype("int32"),
    )
    result["tour_path"] = str(tour_path.relative_to(C.ROOT))
    # Hashed from the array, not the file: `savez_compressed` writes a zip, and a
    # zip stamps the wall clock into every member header, so the file digest
    # would differ between two identical runs (CLAUDE.md rule 5).
    result["tour_sha256"] = hashlib.sha256(tour.astype("int32").tobytes()).hexdigest()
    _log(f"  wrote {tour_path}")

    if variant == C.TOUR_GPX_VARIANT:
        path = Path(str(C.TOUR_GPX).format(variant=variant))
        points = tourio.tour_coordinates(tour, star, tourio.geometry_lookup(frame))
        tourio.write_gpx(
            path,
            points,
            name=f"EfficientRoute Stage 3 constructive tour — variant {variant}",
            description=(
                f"{len(tour):,} arc traversals, {upper_s / 3600.0:,.1f} h. A single "
                "closed circuit of the whole network: a bound and a sanity check, "
                "NOT a day plan. No depot legs, no breaks, no day boundaries."
            ),
        )
        result["gpx_path"] = str(path.relative_to(C.ROOT))
        result["gpx_points"] = len(points)
        _log(f"  wrote {path} ({len(points):,} points)")

    return result


def _required_km_in_scope(star, length_m, mask) -> float:
    """Required traversal km a closed tour can actually reach.

    The rest is not a shortfall of the tour: Stage 1 found those arcs to be legal
    traps, enterable but not leavable or the reverse, and no closed circuit can
    contain one.  It is reported rather than quietly absorbed (CLAUDE.md rule 4).
    """
    import numpy as np

    scope = np.asarray(mask, dtype=bool)
    solo = (star.pair_requirement == 0) & scope
    total = float((star.min_passes[solo] * length_m[solo]).sum())

    shared = (star.pair_requirement > 0) & scope
    seen: set[tuple[int, int]] = set()
    for node in np.flatnonzero(shared):
        twin = star.partner[node]
        key = (int(star.arc_group[node]), int(star.arc_group[twin]) if twin >= 0 else -1)
        key = key if key[0] <= key[1] else (key[1], key[0])
        if key in seen:
            continue
        seen.add(key)
        total += float(length_m[node])
    return total / 1000.0


# ================================================== Stage 4 — zoning


def rewrite_stage4_report() -> dict:
    """Re-render the Stage 4 report and map from the artifact, without re-solving."""
    from . import mapviz04, report04

    if not C.ZONES_JSON.exists():
        raise FileNotFoundError(f"{C.ZONES_JSON} missing — run `make stage4` first")
    payload = json.loads(C.ZONES_JSON.read_text())
    report04.write(payload, C.ZONING_REPORT_MD)
    _log(f"wrote {C.ZONING_REPORT_MD}")
    mapviz04.write(C.ZONES_GPKG, payload, C.ZONING_REPORT_HTML)
    _log(f"wrote {C.ZONING_REPORT_HTML}")
    return payload


def run_stage4(
    variant: str | None = None,
    allowances: tuple[float, ...] | None = None,
    allowance_tag: str = "",
) -> dict:
    """Partition the chosen scope into shift-sized days, sequence them, date them."""
    import datetime as dt

    import numpy as np

    from . import depotlegs, lstar, report04, schedule, zoning
    from . import daylight as D

    started = time.time()
    variant = C.SCOPE_VARIANT if variant is None else variant
    paths = C.stage4_paths(variant, allowance_tag)
    for required_file in (C.NETWORK_GPKG, C.TIME_MODEL_JSON, C.BOUNDS_JSON):
        if not required_file.exists():
            raise FileNotFoundError(
                f"{required_file} missing — Stage 4 depends on the Stage 3 gate having passed"
            )

    _log(f"scope variant {variant} — {scenarios.VARIANT_LABELS[variant]}")
    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    frame = scenarios.apply_variant(arcs, variant)
    model = timemodel.load_model()

    _log("building L(G) for the chosen scope")
    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    parsed = restrictions.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))
    graph = turngraph.build_turn_graph(frame, parsed)
    keep = lstar.largest_strong_component(graph)
    _log(f"  |V(L)| {graph.n_nodes:,}, tourable {int(keep.sum()):,}")

    rows = frame.set_index("arc_id").loc[graph.arc_index["arc_id"].to_numpy()]
    capture_s = rows["capture_time_s"].to_numpy(dtype="float64")
    deadhead_s = model.deadhead_time_s(rows)
    length_m = rows["length_m"].to_numpy(dtype="float64")
    traversals = zoning.required_traversals(graph.arc_index)
    required = (traversals > 0) & keep

    overhead, overhead_source = _zone_overhead(variant)
    _log(f"  overhead factor {overhead:.4f} ({overhead_source})")

    _log("routing depot legs over L(G)")
    depot_node, depot_arc, depot_offset = depotlegs.find_depot_node(frame, graph)
    arrays = depotlegs.manoeuvre_arrays(graph)
    field = depotlegs.leg_field(graph, deadhead_s, depot_node, depot_arc, depot_offset, arrays)
    _log(f"  depot maps to arc {depot_arc} at {depot_offset:.0f} m")

    zone_graph = zoning.build(graph, keep, capture_s, length_m)
    _log(f"  {zone_graph.n_segments:,} segments, {zone_graph.total_weight_s / 3600:,.1f} capture h")
    leg_out_s, leg_back_s = _segment_legs(zone_graph, field)

    start_date = dt.date.fromisoformat(C.CAMPAIGN_START_DATE)
    windows = {}
    for name, (shift_start, shift_end) in C.SHIFT_WINDOWS.items():
        _log(f"=== window {name} ({D.hhmm(shift_start)}–{D.hhmm(shift_end)})")
        plan = zoning.choose_zone_count(
            zone_graph, leg_out_s, leg_back_s, overhead, C.BREAK_HOURS,
            shift_end - shift_start, allowances=allowances,
        )
        _log(f"  {plan.n_zones} zones via {plan.weighting}")
        campaign = schedule.build(
            graph, zone_graph, plan.labels, field, capture_s, deadhead_s, required,
            traversals, overhead, name, start_date, arrays=arrays,
            capture_on_commute=C.CAPTURE_ON_COMMUTE_IN_SIZING,
        )
        _log(
            f"  {len(campaign.days)} days {campaign.start_date} → {campaign.finish_date}; "
            f"reclaimed {campaign.commute_capture_h:.2f} h on the commute"
        )
        windows[name] = {
            "plan": plan,
            "campaign": campaign,
            "labels": plan.labels,
            "shift": [shift_start, shift_end],
        }

    default = windows[C.DEFAULT_SHIFT_WINDOW]
    _log("writing the zone assignment")
    _write_zone_gpkg(frame, graph, zone_graph, default["labels"], default["campaign"],
                     paths["gpkg"])

    payload = {
        "variant": variant,
        "variant_label": scenarios.VARIANT_LABELS[variant],
        "default_window": C.DEFAULT_SHIFT_WINDOW,
        "overhead": {"factor": overhead, "source": overhead_source},
        "depot": {
            "lat": C.DEPOT_LAT,
            "lon": C.DEPOT_LON,
            "arc_id": depot_arc,
            "offset_m": depot_offset,
        },
        "network": {
            "l_nodes": int(graph.n_nodes),
            "l_nodes_tourable": int(keep.sum()),
            "segments": int(zone_graph.n_segments),
            "capture_hours": zone_graph.total_weight_s / 3600.0,
        },
        "unreachable": _unreachable_for_variant(frame, graph, keep, traversals, length_m),
        "leg_comparison": _leg_comparison(zone_graph, default["labels"], field, frame, graph),
        "windows": {
            name: {
                "shift": block["shift"],
                "zoning": block["plan"].to_dict(),
                "campaign": block["campaign"].to_dict(),
                "zones": _zone_rows(zone_graph, block["labels"], block["campaign"]),
            }
            for name, block in windows.items()
        },
        "commute_allowance": C.COMMUTE_ALLOWANCE if allowances is None else max(allowances),
        "commute_allowances_tried": list(allowances) if allowances else None,
        "daylight": _daylight_analysis(windows, start_date),
        "meta": {
            "arcs_sha256": X.file_digest(C.NETWORK_GPKG),
            "runtime_s": round(time.time() - started, 1),
        },
    }
    paths["json"].write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    _log(f"wrote {paths['json']}")

    report04.write(payload, paths["report"])
    _log(f"wrote {paths['report']}")
    from . import mapviz04

    mapviz04.write(paths["gpkg"], payload, paths["html"])
    _log(f"wrote {paths['html']}")
    _log(f"done in {time.time() - started:.0f}s")
    return payload


def run_stage4c() -> dict:
    """Stage 4c — compare the re-zoned plan against the committed one.

    Pure comparison: it solves nothing and writes no plan.  Both sides are read
    from disk, so the verdict can be re-derived at any time without re-running a
    twelve-minute pipeline.
    """
    from . import report04c

    payload = report04c.load()
    report04c.write(payload)
    _log(f"wrote {C.REZONE_REPORT_MD}")
    return payload


def _zone_overhead(variant: str) -> tuple[float, str]:
    """Intra-zone deadhead and turn time per hour of capture.

    SPEC §4 Stage B sizes zones by capture time, but a day costs capture *plus*
    the driving between it.  `zoning.zone_durations` adds the depot legs as their
    own term, so the ratio wanted here is the one with the legs taken out.

    Preference order: an explicit config pin, then Stage 5's measurement over
    solved days — the closest thing to ground truth, since it is the same solver
    the zones will be handed to — then Stage 3's whole-city tour, which has no
    depot legs at all and so is already leg-free.

    Stage 4c: this used to return a hand-typed constant taken from
    `route_h / capture_h`, which *includes* the depot legs.  The cost model then
    added them again, over-predicting every day by about one leg pair and sizing
    every zone too small.
    """
    if C.ZONE_OVERHEAD_MEASURED is not None:
        # An unexplained pin stays "config pin", which the Stage 4 gate rejects.
        return float(C.ZONE_OVERHEAD_MEASURED), (
            getattr(C, "ZONE_OVERHEAD_PIN_SOURCE", "") or "config pin"
        )
    if C.ROUTES_JSON.exists():
        measured = json.loads(C.ROUTES_JSON.read_text()).get("overhead_measured") or {}
        value = measured.get(C.ZONE_OVERHEAD_QUANTILE)
        if value:
            return (
                float(value),
                f"Stage 5 measurement, intra-zone {C.ZONE_OVERHEAD_QUANTILE} "
                f"of {measured['n']} solved days",
            )
    if C.BOUNDS_JSON.exists():
        bounds = json.loads(C.BOUNDS_JSON.read_text())
        for row in bounds["variants"]:
            if row["variant"] == variant and row["capture_h"] > 0:
                return row["total_h"] / row["capture_h"], f"Stage 3 tour, variant {variant}"
    return C.ZONE_OVERHEAD_FALLBACK, "config fallback — Stage 3 bounds not available"


def _segment_legs(zone_graph, field):
    """Cheapest depot leg into and out of each segment."""
    import numpy as np

    out = np.full(zone_graph.n_segments, np.inf)
    back = np.full(zone_graph.n_segments, np.inf)
    for index, nodes in enumerate(zone_graph.nodes_of_segment):
        forward = field.out_s[nodes]
        backward = field.back_s[nodes]
        forward = forward[np.isfinite(forward)]
        backward = backward[np.isfinite(backward)]
        if forward.size:
            out[index] = forward.min()
        if backward.size:
            back[index] = backward.min()
    return out, back


def _day_legs(zone_graph, labels, zone, leg_out_s, leg_back_s) -> dict:
    """The depot legs Stage 4 charged this zone, in hours.

    A minimum over the zone's segments, matching `zoning.zone_durations`: the leg
    is the cheapest way in and out, not the average one.
    """
    import numpy as np

    segments = np.flatnonzero(labels == zone)
    out = leg_out_s[segments]
    back = leg_back_s[segments]
    out = out[np.isfinite(out)]
    back = back[np.isfinite(back)]
    leg_out_h = float(out.min()) / 3600.0 if out.size else 0.0
    leg_back_h = float(back.min()) / 3600.0 if back.size else 0.0
    return {
        "leg_out_h": leg_out_h,
        "leg_back_h": leg_back_h,
        "leg_total_h": leg_out_h + leg_back_h,
    }


def _overhead_distribution(day_rows: list[dict]) -> dict:
    """Intra-zone driving per hour of capture, over every day actually solved.

    This is the number Stage 4 sizes on, and the reason it is emitted here rather
    than retyped into `config` is Stage 4c: the constant was set by hand from
    `route_h / capture_h`, which includes the depot legs that the cost model then
    adds a second time.  Measuring it where the routes are solved keeps the
    definition and the measurement in one place.
    """
    import math

    values = sorted(
        d["overhead_intra_zone"] for d in day_rows
        if d.get("capture_h", 0) > 0 and math.isfinite(d["overhead_intra_zone"])
    )
    if not values:
        return {}

    def q(p: float) -> float:
        index = (len(values) - 1) * p
        low, high = math.floor(index), math.ceil(index)
        if low == high:
            return values[low]
        return values[low] + (values[high] - values[low]) * (index - low)

    return {
        "basis": "(route_h - depot legs) / capture_h, per solved day",
        "n": len(values),
        "min": values[0],
        "p50": q(0.50),
        "p75": q(0.75),
        "p90": q(0.90),
        "p95": q(0.95),
        "max": values[-1],
    }


def _zone_rows(zone_graph, labels, campaign) -> list[dict]:
    """One row per zone, joined to the day that drives it."""
    import numpy as np

    by_zone = {day.zone: day for day in campaign.days}
    rows = []
    for zone in np.unique(labels):
        members = np.flatnonzero(labels == zone)
        day = by_zone[int(zone)]
        rows.append(
            {
                "zone": int(zone),
                "segments": int(len(members)),
                "centerline_km": float(zone_graph.length_m[members].sum() / 1000.0),
                "capture_h_assigned": float(zone_graph.weight_s[members].sum() / 3600.0),
                **day.to_dict(),
            }
        )
    return sorted(rows, key=lambda r: r["position"])


def _unreachable_for_variant(frame, graph, keep, traversals, length_m) -> dict:
    """Required km no closed tour can reach, recomputed for **this** scope.

    Stage 3 reported 129.9 km for variant A.  Most of Stage 0's orphan fragments
    were `service`, so carrying that figure forward would overstate what variant C
    actually loses; the split below is recomputed rather than inherited.
    """
    import numpy as np

    included = frame[~frame["excluded"]]
    total_km = network.required_traversal_km(included)

    # A narrow pair is reachable if *either* direction is, so the requirement is
    # measured on the pair rather than on the representative arc.  Counting only
    # the representative would report a street as unreachable because the
    # direction Stage 0 happened to name first is trapped, which is not a fact
    # about the street.
    index = graph.arc_index
    shared = index["pair_requirement"].to_numpy() > 0
    partner = _partner_rows(index)
    reachable = keep.copy()
    has_twin = shared & (partner >= 0)
    reachable[has_twin] |= keep[partner[has_twin]]

    in_l = float((length_m * traversals).sum() / 1000.0)
    in_scope = float((length_m[reachable] * traversals[reachable]).sum() / 1000.0)

    lost = ~reachable
    classes = graph.arc_index["highway_class"].to_numpy()
    breakdown: dict[str, float] = {}
    for row in np.flatnonzero(lost & (traversals > 0)):
        key = str(classes[row])
        breakdown[key] = breakdown.get(key, 0.0) + float(
            length_m[row] * traversals[row] / 1000.0
        )

    return {
        "required_km_total": total_km,
        "required_km_in_l": in_l,
        "required_km_in_scope": in_scope,
        "required_km_absent_from_l": total_km - in_l,
        "required_km_trapped_in_l": in_l - in_scope,
        "required_km_unreachable": total_km - in_scope,
        "share_unreachable": (total_km - in_scope) / total_km if total_km else 0.0,
        "trapped_by_class": dict(sorted(breakdown.items(), key=lambda kv: -kv[1])),
    }


def _partner_rows(index) -> "np.ndarray":
    """Per L-node, the row of its narrow-pair twin, or -1."""
    import numpy as np

    partner = np.full(len(index), -1, dtype="int64")
    primary = index["variant"].to_numpy() == 0
    arc_id = index["arc_id"].to_numpy()
    pair_id = index["pair_id"].fillna("").to_numpy()
    row_of_arc = {arc_id[i]: int(i) for i in np.flatnonzero(primary)}

    members: dict[str, list[int]] = {}
    for row in np.flatnonzero(primary & (pair_id != "")):
        members.setdefault(pair_id[row], []).append(int(row))
    for rows in members.values():
        if len(rows) == 2:
            partner[rows[0]], partner[rows[1]] = rows[1], rows[0]
    for row in np.flatnonzero(~primary):
        twin = partner[row_of_arc.get(arc_id[row], row)]
        partner[row] = twin
    return partner


def _leg_comparison(zone_graph, labels, field, frame, graph) -> dict:
    """Stage 2's straight-line band estimate against Stage 4's routed time.

    The brief asks for the bands to be *replaced*; this is the receipt.
    """
    import numpy as np
    from pyproj import Geod

    from . import depotlegs

    geod = Geod(ellps="WGS84")
    arc_ids = graph.arc_index["arc_id"].to_numpy()
    centroids = (
        frame.set_index("arc_id").loc[arc_ids].geometry.to_crs(C.METRIC_CRS).centroid
        .to_crs("EPSG:4326")
    )
    lon = centroids.x.to_numpy()
    lat = centroids.y.to_numpy()

    rows = []
    for zone in np.unique(labels):
        nodes = np.concatenate(
            [zone_graph.nodes_of_segment[s] for s in np.flatnonzero(labels == zone)]
        )
        routed = (
            depotlegs.nearest_in_zone(field, nodes, True)[0]
            + depotlegs.nearest_in_zone(field, nodes, False)[0]
        ) / 3600.0
        _, _, metres = geod.inv(
            np.full(len(nodes), C.DEPOT_LON), np.full(len(nodes), C.DEPOT_LAT),
            lon[nodes], lat[nodes],
        )
        straight_km = float(np.min(metres) / 1000.0)
        estimated = 2.0 * straight_km * C.DEPOT_DETOUR_FACTOR / C.DEPOT_LEG_SPEED_KMH
        rows.append(
            {
                "zone": int(zone),
                "straight_km": straight_km,
                "stage2_estimate_h": estimated,
                "routed_h": routed,
                "ratio": routed / estimated if estimated else float("nan"),
            }
        )
    estimated_total = sum(r["stage2_estimate_h"] for r in rows)
    routed_total = sum(r["routed_h"] for r in rows)
    return {
        "zones": rows,
        "stage2_estimate_total_h": estimated_total,
        "routed_total_h": routed_total,
        "ratio": routed_total / estimated_total if estimated_total else float("nan"),
    }


def _daylight_analysis(windows, start_date) -> dict:
    """When the taper starts to bite, and how late the campaign can start."""
    import datetime as dt

    from . import daylight as D

    out = {}
    for name, block in windows.items():
        campaign = block["campaign"]
        shift_start, shift_end = block["shift"]
        days = len(campaign.days)

        def fits_from(date, days=days, shift_start=shift_start, shift_end=shift_end):
            return all(
                D.window_hours(date + dt.timedelta(days=offset), shift_start, shift_end)
                >= day.total_h - 1e-9
                for offset, day in enumerate(campaign.days)
            )

        # Scanning to the last date that fits anywhere in the year finds a
        # February start, because days lengthen again after the solstice.  That
        # is true and useless: the question a scheduler asks is how long *this*
        # decision can wait, so the scan walks forward from the planned start and
        # stops at the first date that does not fit.
        latest = None
        probe = start_date
        horizon = start_date + dt.timedelta(days=200)
        while probe <= horizon:
            if not fits_from(probe):
                break
            latest = probe
            probe += dt.timedelta(days=1)
        first_failure = probe if probe <= horizon else None

        out[name] = {
            "taper_hours": campaign.taper_hours,
            "first_tapered_day": (
                campaign.first_tapered_day.to_dict() if campaign.first_tapered_day else None
            ),
            "sunset_on_start": D.hhmm(D.sunset_hour(start_date)),
            "sunset_on_finish": D.hhmm(D.sunset_hour(campaign.finish_date)),
            "latest_feasible_start": latest.isoformat() if latest else None,
            "first_infeasible_start": first_failure.isoformat() if first_failure else None,
            "slack_days_on_the_decision": (latest - start_date).days if latest else None,
            "days": days,
        }
    return out


def _write_zone_gpkg(frame, graph, zone_graph, labels, campaign, gpkg_path=None) -> None:
    """Zone assignment per **arc**, plus the day that drives it.

    One row per arc of the chosen scope, not one per L-node: a restriction clone
    is a second routing context for the same street, and writing it as a second
    row gives the layer duplicate `arc_id`s and anything that joins on them a
    quiet wrong answer.  Arcs the tour cannot reach are kept with `zone_id = -1`
    and `in_tour_scope = False` rather than dropped (CLAUDE.md rule 4).
    """
    import numpy as np

    position = {day.zone: day.position for day in campaign.days}
    date = {day.zone: day.date.isoformat() for day in campaign.days}

    arc_ids = graph.arc_index["arc_id"].to_numpy()
    segment = zone_graph.segment_of_node

    # Every variant of an arc — the primary and any restriction clone — sits on
    # the same segment and therefore in the same zone, so all of them are read.
    # Reading only the primary loses an arc whose primary variant is a trap while
    # a clone of it is not.
    zone_of_arc: dict[str, int] = {}
    for node in range(graph.n_nodes):
        if segment[node] >= 0:
            zone_of_arc[str(arc_ids[node])] = int(labels[segment[node]])

    table = frame[~frame["excluded"]].copy()
    zones = np.array([zone_of_arc.get(str(a), -1) for a in table["arc_id"]], dtype="int64")
    table["zone_id"] = zones
    table["sequence_position"] = [position.get(int(z), -1) for z in zones]
    table["day_date"] = [date.get(int(z), "") for z in zones]
    table["in_tour_scope"] = zones >= 0

    keep_columns = [
        "arc_id", "way_id", "seg_index", "direction", "highway_class", "name",
        "length_m", "min_passes", "pair_requirement", "is_pair_representative",
        "capture_quality", "capture_speed_kmh", "capture_time_s", "service_role",
        "zone_id", "sequence_position", "day_date", "in_tour_scope", "geometry",
    ]
    out = gpd.GeoDataFrame(
        table[keep_columns].sort_values("arc_id", kind="mergesort").reset_index(drop=True),
        geometry="geometry",
        crs="EPSG:4326",
    )
    network.write_gpkg(out, gpkg_path or C.ZONES_GPKG, layer=C.ZONES_LAYER)


# ================================================== Stage 4b — re-check


def run_stage4b() -> dict:
    """Re-test variant D, dispose of the trapped mainlines, price the extra day.

    Runs each variant's Stage 4 only if its artifact is missing, so re-running
    this to redraft the report costs seconds rather than half an hour.
    """
    import geopandas as gpd

    from . import lstar, recheck, report04b

    started = time.time()
    variants = ("C", "D")
    # Both profiles are named and forced rather than one of them being "whatever
    # the config currently says".  Item 3 changes that config, and a comparison
    # whose baseline moves when you act on it is not a comparison.
    profiles = {
        "fewest_days": ((0.0,), "-fewestdays"),
        "reserved": ((C.COMMUTE_ALLOWANCE_RESERVED,), "-reserved"),
    }

    runs: dict[str, dict] = {}
    for variant in variants:
        runs[variant] = {}
        for profile, (allowances, tag) in profiles.items():
            paths = C.stage4_paths(variant, tag)
            if not paths["json"].exists():
                _log(f"running Stage 4 — variant {variant}, {profile} allowance profile")
                run_stage4(variant=variant, allowances=allowances, allowance_tag=tag)
            runs[variant][profile] = json.loads(paths["json"].read_text())

    _log("item 2 — disposing of the trapped mainline arcs")
    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    frame = scenarios.apply_variant(arcs, C.SCOPE_VARIANT)
    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    parsed = restrictions.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))
    graph = turngraph.build_turn_graph(frame, parsed)
    keep = lstar.largest_strong_component(graph)
    extract = X.load_extract(C.EXTRACT_PATH)

    disposition = recheck.trap_disposition(frame, graph, keep, parsed, extract.boundary)
    fix = recheck.mainline_fix_effect(frame, parsed)
    _log(
        f"  {fix['edges_added']} manoeuvres recover {fix['km_recovered']:.2f} km "
        f"({fix['fast_km_recovered']:.2f} km of it motorway/trunk); "
        f"U1 {'holds' if fix['u1']['holds'] else 'BROKEN'}"
    )

    payload = {
        "item1_variant_recheck": _variant_recheck(runs),
        "item2_trap_disposition": {"disposition": disposition, "fix": fix},
        "item3_allowance_profiles": _allowance_profiles(runs),
        "decision_inputs": _decision_inputs(runs),
        "current_scope_variant": C.SCOPE_VARIANT,
        "meta": {
            "arcs_sha256": X.file_digest(C.NETWORK_GPKG),
            "runtime_s": round(time.time() - started, 1),
        },
    }
    C.RECHECK_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    _log(f"wrote {C.RECHECK_JSON}")
    report04b.write(payload, C.RECHECK_REPORT_MD)
    _log(f"wrote {C.RECHECK_REPORT_MD}")
    _log(f"done in {time.time() - started:.0f}s")
    return payload


def _variant_recheck(runs: dict) -> dict:
    """Variant C against variant D, measured rather than scaled."""
    out = {}
    for variant, profiles in runs.items():
        payload = profiles["reserved"]
        out[variant] = {
            "label": payload["variant_label"],
            "capture_hours": payload["network"]["capture_hours"],
            "overhead": payload["overhead"]["factor"],
            "segments": payload["network"]["segments"],
            "unreachable_km": payload["unreachable"]["required_km_unreachable"],
            "windows": {
                name: {
                    "days": block["campaign"]["days"],
                    "start": block["campaign"]["start_date"],
                    "finish": block["campaign"]["finish_date"],
                    "total_hours": block["campaign"]["total_hours"],
                    "day_min": block["campaign"]["day_hours_min"],
                    "day_max": block["campaign"]["day_hours_max"],
                    "day_stdev": block["campaign"]["day_hours_stdev"],
                    "commute_capture_h": block["campaign"]["commute_capture_h"],
                    "leg_hours": payload["leg_comparison"]["routed_total_h"],
                    "latest_feasible_start": payload["daylight"][name]["latest_feasible_start"],
                    # What a latest start actually implies. The daylight rule is
                    # literal — min(shift_end, sunset) — so a late start can still
                    # "fit" while finishing deep into November, which SPEC §7.3
                    # warns about on quality grounds the model does not carry.
                    "latest_start_finish": _finish_of(
                        payload["daylight"][name]["latest_feasible_start"],
                        block["campaign"]["days"],
                    ),
                    "taper_hours": payload["daylight"][name]["taper_hours"],
                }
                for name, block in payload["windows"].items()
            },
        }
    return out


def _finish_of(start: str | None, days: int) -> str | None:
    import datetime as dt

    if not start:
        return None
    return (dt.date.fromisoformat(start) + dt.timedelta(days=days - 1)).isoformat()


def _allowance_profiles(runs: dict) -> dict:
    """The extra-day trade-off, for each variant, on its own numbers."""
    out = {}
    for variant, profiles in runs.items():
        out[variant] = {}
        for name in ("fewest_days", "reserved"):
            payload = profiles[name]
            window = payload["windows"][payload["default_window"]]["campaign"]
            out[variant][name] = {
                "allowance": payload["commute_allowance"],
                "days": window["days"],
                "total_hours": window["total_hours"],
                "commute_capture_h": window["commute_capture_h"],
                "day_stdev": window["day_hours_stdev"],
                "finish": window["finish_date"],
            }
        fewest = out[variant]["fewest_days"]
        reserved = out[variant]["reserved"]
        out[variant]["delta"] = {
            "extra_days": reserved["days"] - fewest["days"],
            "hours_saved": fewest["total_hours"] - reserved["total_hours"],
            "extra_commute_capture_h": reserved["commute_capture_h"] - fewest["commute_capture_h"],
        }
    return out


def _decision_inputs(runs: dict) -> dict:
    """The dates the scope decision actually turns on, in one place."""
    import datetime as dt

    limit = dt.date(2026, 10, 30)
    out = {"daylight_limit": limit.isoformat(), "variants": {}}
    for variant, profiles in runs.items():
        payload = profiles["reserved"]
        rows = {}
        for name, block in payload["windows"].items():
            finish = dt.date.fromisoformat(block["campaign"]["finish_date"])
            rows[name] = {
                "days": block["campaign"]["days"],
                "finish": finish.isoformat(),
                "margin_days": (limit - finish).days,
                "fits": finish <= limit,
            }
        out["variants"][variant] = rows
    return out


# ================================================== Stage 5 — route solve


def run_stage5() -> dict:
    """Solve one legal, closed, depot-to-depot route for every driving day."""
    import datetime as dt

    import numpy as np

    from . import depotlegs, lstar, orientation, report05, routeio, routes, schedule
    from . import tourcheck as TC
    from . import zoning

    started = time.time()
    for required_file in (C.NETWORK_GPKG, C.ZONES_GPKG, C.ZONES_JSON):
        if not required_file.exists():
            raise FileNotFoundError(
                f"{required_file} missing — Stage 5 depends on the Stage 4 gate having passed"
            )

    _log(f"scope variant {C.SCOPE_VARIANT}, window {C.DEFAULT_SHIFT_WINDOW}")
    arcs = gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)
    frame = scenarios.apply_variant(arcs, C.SCOPE_VARIANT)
    model = timemodel.load_model()

    routable = arcs[(~arcs["excluded"]) & (arcs["in_largest_scc"])]
    parsed = restrictions.parse_restrictions(C.PBF_PATH, set(routable["way_id"].astype(int)))
    graph = turngraph.build_turn_graph(frame, parsed)
    keep = lstar.largest_strong_component(graph)

    arc_ids = graph.arc_index["arc_id"].to_numpy()
    rows = frame.set_index("arc_id").loc[arc_ids]
    capture_s = rows["capture_time_s"].to_numpy(dtype="float64")
    deadhead_s = model.deadhead_time_s(rows)
    length_m = rows["length_m"].to_numpy(dtype="float64")
    zone_graph = zoning.build(graph, keep, capture_s, length_m)
    oriented = orientation.orient(graph.arc_index, keep=keep)

    depot_node, depot_arc, depot_offset = depotlegs.find_depot_node(frame, graph)
    arrays = depotlegs.manoeuvre_arrays(graph)
    field = depotlegs.leg_field(graph, deadhead_s, depot_node, depot_arc, depot_offset, arrays)
    star_template = lstar.build(graph, capture_s, deadhead_s, oriented.lower, keep=keep)
    _log(f"L*: {star_template.n_nodes:,} nodes; depot arc {depot_arc}")

    labels = _stage4_labels(zone_graph, graph, arc_ids)
    shift_start, shift_end = C.SHIFT_WINDOWS[C.DEFAULT_SHIFT_WINDOW]
    window_h = shift_end - shift_start
    start_date = dt.date.fromisoformat(C.CAMPAIGN_START_DATE)

    solved: dict[int, routes.DayRoute] = {}
    splits = []
    for round_index in range(C.ROUTE_SPLIT_MAX_ROUNDS + 1):
        order = _sequence_zones(zone_graph, labels, field)
        pending = [z for z in order if z not in solved]
        _log(f"round {round_index}: solving {len(pending)} of {len(order)} zones")
        for zone in pending:
            nodes = _zone_nodes(zone_graph, labels, zone)
            solved[zone] = routes.solve_zone(
                graph, star_template, capture_s, deadhead_s, nodes, depot_node,
                oriented.lower, keep, zone, 0, "",
            )

        over = [
            z for z in order
            if solved[z].day_hours() > window_h + 1e-9
        ]
        if not over:
            break
        if round_index == C.ROUTE_SPLIT_MAX_ROUNDS:
            _log(f"  {len(over)} days still over the window at the split cap")
            break
        next_label = int(labels.max()) + 1
        for zone in over:
            labels, ok = zoning.split_zone(zone_graph, labels, zone, next_label)
            _log(
                f"  day for zone {zone} runs {solved[zone].day_hours():.2f} h in a "
                f"{window_h:.2f} h window — {'split' if ok else 'CANNOT SPLIT'}"
            )
            if ok:
                splits.append({"zone": int(zone), "into": [int(zone), next_label]})
                solved.pop(zone, None)
                next_label += 1

    order = _sequence_zones(zone_graph, labels, field)
    day_routes = []
    for position, zone in enumerate(order):
        route = solved[zone]
        day_routes.append(
            dataclasses.replace(
                route, position=position,
                date=(start_date + dt.timedelta(days=position)).isoformat(),
            )
        )
    _log(f"{len(day_routes)} days, {sum(r.total_h for r in day_routes):,.1f} h of driving")

    _log("writing per-day routes")
    payload = _write_stage5_outputs(
        graph, star_template, frame, zone_graph, labels, day_routes, oriented,
        capture_s, deadhead_s, field, depot_arc, depot_offset, window_h, splits,
        start_date, arrays,
    )
    payload["meta"] = {
        "arcs_sha256": X.file_digest(C.NETWORK_GPKG),
        "runtime_s": round(time.time() - started, 1),
    }
    C.ROUTES_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    _log(f"wrote {C.ROUTES_JSON}")
    report05.write(payload, C.ROUTES_REPORT_MD)
    _log(f"wrote {C.ROUTES_REPORT_MD}")
    _log(f"done in {time.time() - started:.0f}s")
    return payload


def _stage4_labels(zone_graph, graph, arc_ids):
    """Zone per segment, read back from the Stage 4 GeoPackage."""
    import numpy as np

    zones = gpd.read_file(C.ZONES_GPKG, layer=C.ZONES_LAYER)
    zone_of_arc = zones.set_index("arc_id")["zone_id"].to_dict()
    labels = np.full(zone_graph.n_segments, -1, dtype="int64")
    for node, segment in enumerate(zone_graph.segment_of_node):
        if segment >= 0:
            labels[segment] = int(zone_of_arc.get(str(arc_ids[node]), -1))
    if (labels < 0).any():
        raise RuntimeError(f"{int((labels < 0).sum())} segments carry no zone")
    return labels


def _zone_nodes(zone_graph, labels, zone):
    import numpy as np

    return np.concatenate(
        [zone_graph.nodes_of_segment[s] for s in np.flatnonzero(labels == zone)]
    )


def _sequence_zones(zone_graph, labels, field):
    """Far zones first (SPEC §7.1 mitigation 2), on the plain depot leg."""
    import numpy as np

    from . import depotlegs, schedule

    ids = np.unique(labels)
    legs = np.array(
        [
            depotlegs.nearest_in_zone(field, _zone_nodes(zone_graph, labels, z), True)[0]
            + depotlegs.nearest_in_zone(field, _zone_nodes(zone_graph, labels, z), False)[0]
            for z in ids
        ]
    )
    return [int(z) for z in schedule.sequence_far_first(ids, legs)]


def _write_stage5_outputs(
    graph, star, frame, zone_graph, labels, day_routes, oriented, capture_s,
    deadhead_s, field, depot_arc, depot_offset, window_h, splits, start_date, arrays,
):
    """GPX, turn sheets, the manoeuvre GeoPackage, and every number the report uses."""
    import numpy as np

    from . import lowerbound, routeio
    from . import tourcheck as TC

    C.ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    for stale in C.ROUTES_DIR.glob("day-*"):
        stale.unlink()

    geometry = {
        str(arc_id): list(geom.coords)
        for arc_id, geom in zip(frame["arc_id"], frame.geometry)
    }
    names = dict(zip(frame["arc_id"].astype(str), frame["name"].fillna("")))
    lengths = dict(zip(frame["arc_id"].astype(str), frame["length_m"].astype(float)))
    speeds = dict(zip(frame["arc_id"].astype(str), frame["capture_speed_kmh"].astype(float)))
    exit_s = lowerbound.min_exit_s(graph)
    required_passes = oriented.lower[: star.n_arc_nodes]

    # The same depot legs Stage 4 sizes with — cheapest in and out, minimised over
    # the zone's segments — so that the overhead measured below is on exactly the
    # footing Stage 4's cost model puts it on.
    leg_out_s, leg_back_s = _segment_legs(zone_graph, field)

    rows = []
    day_rows = []
    for route in day_routes:
        day = route.to_dict()
        day.update(_day_legs(zone_graph, labels, route.zone, leg_out_s, leg_back_s))
        steps = routeio.annotate(route.tour, star, graph, required_passes)
        day["lane_instructions"] = sum(1 for s in steps if s["lane_instruction"])
        day["multi_pass_arcs"] = int(
            len({s["arc_id"] for s in steps if s["required_passes"] >= 2})
        )

        zone_nodes = _zone_nodes(zone_graph, labels, route.zone)
        required = zone_nodes[required_passes[zone_nodes] > 0]
        floor_s = float(
            (capture_s[required] * required_passes[required]).sum()
            + (exit_s[required] * required_passes[required]).sum()
        )
        day["lower_bound_h"] = floor_s / 3600.0
        day["optimality_gap"] = (
            (route.total_s - floor_s) / floor_s if floor_s else float("nan")
        )
        day["bound_method"] = "capture floor + cheapest legal exit"
        # Stage 4 sizes a day as capture x overhead + legs + break, so the ratio it
        # needs is the one with the depot legs taken *out*. Reporting route_h /
        # capture_h instead is what charged the legs twice (Stage 4c).
        day["overhead_intra_zone"] = (
            (day["route_h"] - day["leg_total_h"]) / day["capture_h"]
            if day["capture_h"] > 0 else float("nan")
        )
        day["fits"] = route.day_hours() <= window_h + 1e-9
        day["window_h"] = window_h
        day_rows.append(day)

        stem = f"day-{day['day']:02d}"
        points = routeio.route_coordinates(route.tour, star, geometry)
        routeio.write_gpx(
            C.ROUTES_DIR / f"{stem}.gpx", points,
            name=f"EfficientRoute day {day['day']:02d} — {day['date']} (zone {route.zone})",
            description=(
                f"{day['arc_traversals']:,} arc traversals, {day['route_h']:.2f} h driving. "
                "Starts and ends at the depot."
            ),
        )
        day["gpx_points"] = len(points)
        routeio.write_day_sheet(
            C.ROUTES_DIR / f"{stem}.md", day, steps, names, lengths, speeds
        )

        for step in steps:
            rows.append(
                {
                    "day": day["day"],
                    "date": day["date"],
                    "zone": route.zone,
                    "step": step["step"],
                    "arc_id": step["arc_id"],
                    # The L-node, not just the arc: a restriction clone shares its
                    # arc_id with the original, so an arc_id alone does not say
                    # which manoeuvre was driven and the sequence stops being
                    # checkable against L.
                    "l_node": int(step["arc_node"]),
                    "pass_number": step["pass_number"],
                    "required_passes": step["required_passes"],
                    "mode": "capture" if step["is_capture"] else "deadhead",
                    "lane_instruction": step["lane_instruction"],
                    "turn": step["turn"],
                    "turn_penalty_s": step["turn_penalty_s"],
                }
            )

    # Look the geometry up once per arc, not once per manoeuvre: the campaign has
    # tens of thousands of traversals and re-indexing the frame inside the loop
    # turns a two-second write into a twenty-minute one.
    geometry_by_arc = dict(zip(frame["arc_id"].astype(str), frame.geometry))
    manoeuvres = gpd.GeoDataFrame(
        rows,
        geometry=[geometry_by_arc[r["arc_id"]] for r in rows],
        crs="EPSG:4326",
    )
    network.write_gpkg(manoeuvres, C.ROUTES_GPKG, layer=C.ROUTES_LAYER)
    _log(f"wrote {C.ROUTES_GPKG} ({len(rows):,} manoeuvres)")

    totals = {
        "days": len(day_rows),
        "capture_h": sum(d["capture_h"] for d in day_rows),
        "deadhead_h": sum(d["deadhead_h"] for d in day_rows),
        "turn_h": sum(d["turn_h"] for d in day_rows),
        "route_h": sum(d["route_h"] for d in day_rows),
        "day_h": sum(d["day_h"] for d in day_rows),
        "lower_bound_h": sum(d["lower_bound_h"] for d in day_rows),
        "arc_traversals": sum(d["arc_traversals"] for d in day_rows),
        "days_over_window": sum(1 for d in day_rows if not d["fits"]),
        "start_date": day_rows[0]["date"],
        "finish_date": day_rows[-1]["date"],
    }
    totals["optimality_gap"] = (
        (totals["route_h"] - totals["lower_bound_h"]) / totals["lower_bound_h"]
    )
    return {
        "variant": C.SCOPE_VARIANT,
        "window": C.DEFAULT_SHIFT_WINDOW,
        "window_h": window_h,
        "depot": {"arc_id": depot_arc, "offset_m": depot_offset},
        "days": day_rows,
        "totals": totals,
        "splits": splits,
        "overhead_measured": _overhead_distribution(day_rows),
        "stage3_bracket": _stage3_bracket(len(day_rows)),
        "turn_reconciliation": _turn_reconciliation(totals),
        "orientation": oriented.to_dict(),
    }


def rewrite_stage5_report() -> dict:
    """Re-render the Stage 5 report from the artifact, without re-solving."""
    from . import report05

    if not C.ROUTES_JSON.exists():
        raise FileNotFoundError(f"{C.ROUTES_JSON} missing — run `make stage5` first")
    payload = json.loads(C.ROUTES_JSON.read_text())
    report05.write(payload, C.ROUTES_REPORT_MD)
    _log(f"wrote {C.ROUTES_REPORT_MD}")
    return payload


def _stage3_bracket(days: int) -> dict:
    """I5's reference: the Stage 3 bracket for this scope."""
    if not C.BOUNDS_JSON.exists():
        return {}
    bounds = json.loads(C.BOUNDS_JSON.read_text())
    for row in bounds["variants"]:
        if row["variant"] == C.SCOPE_VARIANT:
            return {
                "lower_h": row["lower_bound_h"],
                "upper_h": row["total_h"],
                "note": (
                    "Stage 3 solved one closed tour of the whole scope with no depot "
                    f"legs and no day boundaries. A {days}-day plan drives to and from "
                    f"the depot {days} times, so it sits above the upper end by "
                    "construction."
                ),
            }
    return {}


def _turn_reconciliation(totals: dict) -> dict:
    """Stage 5 settles the turn *count*; the per-turn seconds remain assumptions."""
    out = {"stage5_turn_h": totals["turn_h"], "penalties_s": dict(C.TURN_PENALTY_S)}
    if C.TIME_MODEL_JSON.exists():
        stage2 = json.loads(C.TIME_MODEL_JSON.read_text())
        out["stage2_floor_h"] = stage2["turn"]["hours_floor"]
        out["stage2_estimate_h"] = stage2["turn"]["hours_mean"]
    if C.BOUNDS_JSON.exists():
        bounds = json.loads(C.BOUNDS_JSON.read_text())
        for row in bounds["variants"]:
            if row["variant"] == C.SCOPE_VARIANT:
                out["stage3_tour_turn_h"] = row["turn_h"]
    return out
