"""Stage 7 prep — turn the solved plan into something a person can watch.

The renderer is deliberately dumb: it interpolates a position along a polyline and
blits two bitmaps. Everything that requires knowing about the plan happens here, so
the page needs no libraries and no server.

Three things this does that the GeoPackage does not:

**Cumulative time.** `05-routes.gpkg` says what is driven in what order but not
when. Travel time is recomputed per manoeuvre from the same model Stage 5 priced
with — capped capture speed for a required pass, uncapped for everything else —
and accumulated, so the playback clock is the plan's own clock rather than a guess.

**The third mode.** SPEC and the brief both distinguish depot legs from ordinary
deadhead, and nothing in the artifacts marks them. They are recovered structurally:
a day begins and ends at the depot, so its leading and trailing runs of deadhead
*are* the legs. Everything between them is repositioning inside the day's work.

**A basemap made of the network itself.** Drawing the street network as thin grey
lines removes the last external dependency — no tiles, no fonts, no CDN — which is
what lets the embed build open on a laptop with no network at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import config as C

MODES = ("capture", "deadhead", "leg")


def _round(coords, dp: int) -> list:
    return [[round(float(x), dp), round(float(y), dp)] for x, y in coords]


def _dedupe(coords: list) -> list:
    """Drop consecutive duplicates left behind by rounding."""
    out = [coords[0]]
    for point in coords[1:]:
        if point != out[-1]:
            out.append(point)
    return out


def _simplify(frame, tolerance_m: float):
    """Douglas-Peucker in metres, returned in lon/lat.

    Simplifying in degrees would cut harder east-west than north-south; at 41.7°N
    a degree of longitude is 0.75 of a degree of latitude, so a single tolerance
    means two different distances. Projecting first makes the tolerance mean what
    it says.
    """
    metric = frame.to_crs(C.METRIC_CRS)
    simplified = metric.simplify(tolerance_m, preserve_topology=False)
    return simplified.set_crs(C.METRIC_CRS).to_crs("EPSG:4326"), metric, simplified


def deviation_m(frame, tolerance_m: float) -> float:
    """Worst distance any simplified line strays from its source, in metres."""
    _, metric, simplified = _simplify(frame, tolerance_m)
    worst = 0.0
    for original, cut in zip(metric.geometry, simplified):
        if cut.is_empty:
            continue
        worst = max(worst, float(original.hausdorff_distance(cut)))
    return worst


def _line(simplified, source) -> list:
    """A drawable line for one manoeuvre, never fewer than two points.

    Rounding to metre precision can collapse a very short arc — Tbilisi has 4 m
    junction stubs — to a single repeated coordinate, and a one-point line is not a
    line: the renderer cannot orient the car along it and the segment silently
    vanishes from the playback. Falling back to the unsimplified geometry recovers
    almost all of them; anything still degenerate keeps both endpoints at full
    precision, so the segment is present and the car sits on it for its duration.
    """
    coords = _dedupe(_round(simplified.coords, C.PLAYBACK_COORD_DP))
    if len(coords) >= 2:
        return coords
    coords = _dedupe(_round(source.coords, C.PLAYBACK_COORD_DP))
    if len(coords) >= 2:
        return coords
    ends = list(source.coords)
    return [[round(float(ends[0][0]), 7), round(float(ends[0][1]), 7)],
            [round(float(ends[-1][0]), 7), round(float(ends[-1][1]), 7)]]


def _leg_mask(modes: np.ndarray) -> np.ndarray:
    """Which manoeuvres are depot legs: the leading and trailing deadhead runs."""
    is_leg = np.zeros(len(modes), dtype=bool)
    i = 0
    while i < len(modes) and modes[i] == "deadhead":
        is_leg[i] = True
        i += 1
    j = len(modes) - 1
    while j >= 0 and modes[j] == "deadhead":
        is_leg[j] = True
        j -= 1
    return is_leg


def build_days(manoeuvres, arcs, model, out_dir: Path | None = None) -> list[dict]:
    """One playback file per day. Returns the per-day summaries."""
    out_dir = out_dir or C.PLAYBACK_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    indexed = arcs.set_index(arcs["arc_id"].astype(str))
    rows = indexed.loc[manoeuvres["arc_id"].astype(str)]
    is_capture = (manoeuvres["mode"] == "capture").to_numpy()
    travel_s = np.where(is_capture,
                        rows["capture_time_s"].to_numpy(float),
                        model.deadhead_time_s(rows))
    work = manoeuvres.assign(
        travel_s=travel_s,
        turn_s=manoeuvres["turn_penalty_s"].to_numpy(float),
        length_m=rows["length_m"].to_numpy(float),
        street=rows["name"].fillna("").to_numpy(),
    )

    summaries = []
    for day in sorted(work["day"].unique()):
        block = work[work["day"] == day].sort_values("step", kind="mergesort")
        modes = block["mode"].to_numpy().astype(object).copy()
        modes[_leg_mask(modes)] = "leg"

        simplified, _, _ = _simplify(block, C.PLAYBACK_SIMPLIFY_M)
        segments, clock = [], 0.0
        for (_, row), mode, geometry, source in zip(
            block.iterrows(), modes, simplified, block.geometry
        ):
            coords = _line(geometry, source)
            travel = float(row.travel_s)
            turn = float(row.turn_s)
            # Round first, then derive: `t0` and `t1` are what the renderer reads, so
            # `tv` has to fit inside the rounded window rather than the exact one.
            # Deriving it from the unrounded travel let it exceed `t1 - t0` by a
            # hundredth of a second and the car overran the end of its own segment.
            t0 = round(clock, 2)
            t1 = round(clock + travel + turn, 2)
            # `t1` closes over travel *and* the turn taken on leaving, so the last
            # segment's `t1` is the day's whole driving time. `tv` is how much of
            # that the car is moving for; the rest it sits at the junction.
            segments.append({
                "m": MODES.index(mode),
                "t0": t0,
                "t1": t1,
                "tv": round(min(travel, t1 - t0), 2),
                "km": round(float(row.length_m) / 1000.0, 4),
                "s": str(row.street),
                "c": coords,
            })
            clock += travel + turn

        by_mode = {}
        for mode in MODES:
            picked = [s for s in segments if s["m"] == MODES.index(mode)]
            by_mode[mode] = {
                "h": round(sum(s["tv"] for s in picked) / 3600.0, 4),
                "km": round(sum(s["km"] for s in picked), 3),
            }
        lons = [c[0] for s in segments for c in s["c"]]
        lats = [c[1] for s in segments for c in s["c"]]
        payload = {
            "day": int(day),
            "date": str(block["date"].iloc[0]),
            "zone": int(block["zone"].iloc[0]),
            "start_s": C.PLAYBACK_START_S,
            "duration_s": round(clock, 2),
            "modes": list(MODES),
            "by_mode": by_mode,
            "turn_h": round(float(block["turn_s"].sum()) / 3600.0, 4),
            "km": round(float(block["length_m"].sum()) / 1000.0, 3),
            "bbox": [min(lons), min(lats), max(lons), max(lats)],
            "segments": segments,
        }
        path = out_dir / f"day-{int(day):02d}.json"
        path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=False))
        summaries.append({k: v for k, v in payload.items() if k != "segments"}
                         | {"segments": len(segments), "file": path.name})
    return summaries


def build_network(arcs, out_dir: Path | None = None) -> dict:
    """The context basemap: every routable arc, cut hard, drawn once."""
    out_dir = out_dir or C.PLAYBACK_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    simplified, _, _ = _simplify(arcs, C.NETWORK_SIMPLIFY_M)
    lines = []
    for geometry in simplified:
        if geometry.is_empty:
            continue
        coords = _dedupe(_round(geometry.coords, C.PLAYBACK_COORD_DP))
        if len(coords) >= 2:
            lines.append(coords)
    lons = [c[0] for line in lines for c in line]
    lats = [c[1] for line in lines for c in line]
    payload = {"lines": lines,
               "bbox": [min(lons), min(lats), max(lons), max(lats)]}
    path = out_dir / "network.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    return {"lines": len(lines), "vertices": len(lons), "file": path.name,
            "bytes": path.stat().st_size}


def build_index(summaries: list[dict], network: dict,
                out_dir: Path | None = None) -> Path:
    """The manifest the page loads first: which days exist, and how big they are."""
    out_dir = out_dir or C.PLAYBACK_DATA_DIR
    payload = {
        "scope": f"Tbilisi camera-car campaign — variant {C.SCOPE_VARIANT}, "
                 f"{len(summaries)} days",
        "variant": C.SCOPE_VARIANT,
        "network": network,
        "days": [
            {k: s[k] for k in ("day", "date", "zone", "duration_s", "km", "by_mode",
                               "bbox", "segments", "file")}
            for s in summaries
        ],
    }
    path = out_dir / "index.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    return path


def embed(day: int, out_path: Path, data_dir: Path | None = None,
          template: Path | None = None) -> Path:
    """One day, as a single file that works with no network at all.

    The page already loads everything through one indirection, so embedding is a
    matter of answering those loads from an object instead of the filesystem — no
    second renderer to keep in step with the first. Only the chosen day's data goes
    in, because the point is a file small enough to send someone.
    """
    data_dir = data_dir or C.PLAYBACK_DATA_DIR
    template = template or (C.PLAYBACK_INDEX if C.PLAYBACK_INDEX.exists()
                            else C.PLAYBACK_TEMPLATE)
    name = f"day-{int(day):02d}.json"
    if not (data_dir / name).exists():
        raise FileNotFoundError(f"{data_dir / name} missing — run `make stage7` first")

    index = json.loads((data_dir / "index.json").read_text())
    index["days"] = [d for d in index["days"] if d["day"] == int(day)]
    bundle = {
        "data/index.json": index,
        "data/network.json": json.loads((data_dir / "network.json").read_text()),
        f"data/{name}": json.loads((data_dir / name).read_text()),
    }
    html = template.read_text()
    # `</script>` inside a string would close the tag it is written in.
    blob = json.dumps(bundle, separators=(",", ":")).replace("</", "<\\/")
    injected = f"<script>window.PLAYBACK_EMBED={blob};</script>\n"
    marker = "<script>\n(function(){"
    if marker not in html:
        raise ValueError("template changed shape; embed cannot find the script block")
    html = html.replace(marker, injected + marker, 1)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path
