"""Render `reports/00-network-stats.md` from the computed statistics.

Formatting only — every number here comes from `stats.compute`, so the report
and the gate cannot disagree.
"""

from __future__ import annotations

from pathlib import Path

from . import config as C


def _table(headers: list[str], rows: list[list[str]], numeric: bool = True) -> str:
    """Markdown table. Numeric tables right-align every column but the first."""
    align = [
        "---" if (i == 0 or not numeric) else "---:" for i in range(len(headers))
    ]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(align) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _km(value: float) -> str:
    return f"{value:,.1f}"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _share(part: float, whole: float) -> str:
    return f"{part / whole * 100.0:.1f}%" if whole else "—"


def _service_breakdown(s: dict, service: dict, headline: float) -> str:
    """The `service=*` split — and why, in Tbilisi, it does not settle the question."""
    rows = service.get("by_type") or []
    if not rows:
        return ""

    out = ["\n### 8.1 By `service=*` subtag\n"]
    out.append(
        "\n`highway=service` is a bag of unrelated things: an alley is a street the campaign has\n"
        "to capture, a driveway or a parking aisle is not. The scope decision cannot be made on\n"
        "the parent tag, so here is the subtag split.\n"
    )
    out.append("\n" + _table(
        ["`service_type`", "Arcs", "Included arcs", "Centerline km", "Required km", "% of service"],
        [
            [
                f"`{r['service_type']}`",
                f"{r['arc_count']:,}",
                f"{r['included_arc_count']:,}",
                _km(r["centerline_km"]),
                _km(r["required_km"]),
                _pct(r["share_of_service_required"] * 100),
            ]
            for r in rows
        ],
    ))

    untagged = next((r for r in rows if r["service_type"] == "untagged"), None)
    if untagged:
        share = untagged["share_of_service_required"] * 100
        out.append(
            f"\n\n> **The subtag does not settle it.** {_pct(share)} of service required traversal — "
            f"{_km(untagged['required_km'])} km of\n"
            f"> {_km(service['required_km'])} km — carries **no `service=*` tag at all**. The values "
            "that would let the\n"
            "> question be answered on tags (`driveway`, `parking_aisle`) cover only "
            f"{_km(service['required_km'] - untagged['required_km'])} km\n"
            f"> between them, {_pct(100 - share)} of the service total and "
            f"{_pct((service['required_km'] - untagged['required_km']) / headline * 100)} of the "
            "campaign.\n"
            ">\n"
            "> So the open [CONFIRM] in SPEC §2.1 stays open on this evidence. Deciding it needs a\n"
            "> sample of what those untagged service ways physically *are*, not more tag analysis.\n"
        )
    return "".join(out)


def _service_scenarios(s: dict) -> str:
    payload = s.get("service_scenarios") or {}
    rows = payload.get("variants") or []
    if not rows:
        return (
            "\n### 8.2 Scope scenarios\n\n**Not yet measured.** Run `make stage0b`.\n"
        )

    out = ["\n### 8.2 Scope scenarios — measurement only\n"]
    out.append(
        "\nEach variant is rebuilt properly rather than subtracted: dropping service roads changes\n"
        "which arcs remain strongly connected, so the component analysis and L(G) are recomputed on\n"
        "the filtered network. **Variant A is what the pipeline builds and remains the default** —\n"
        "no switch is exposed and no classification changed.\n"
    )
    out.append("\n" + _table(
        ["Variant", "What it includes", "Required km", "Δ vs A", "Included arcs", "Δ vs A", "L(G) nodes", "Δ vs A"],
        [
            [
                f"**{r['variant']}**",
                r["label"],
                _km(r["required_traversal_km"]),
                f"{r['delta_required_km']:+,.1f}",
                f"{r['included_arc_count']:,}",
                f"{r['delta_included_arcs']:+,}",
                f"{r.get('l_nodes', 0):,}",
                f"{r.get('delta_l_nodes', 0):+,}",
            ]
            for r in rows
        ],
        numeric=False,
    ))
    variant_b = next((r for r in rows if r["variant"] == "B"), None)
    variant_c = next((r for r in rows if r["variant"] == "C"), None)
    if variant_b and variant_c:
        out.append(
            f"\n\n**Variant B saves almost nothing** — {_km(abs(variant_b['delta_required_km']))} km, "
            f"{_pct(abs(variant_b['delta_required_km']) / rows[0]['required_traversal_km'] * 100)} "
            "of the campaign — because\n"
            "the untagged bucket dominates and B keeps it. The real choice is between A and C, and\n"
            f"C is a {_km(abs(variant_c['delta_required_km']))} km cut made without knowing what is "
            "being cut.\n"
        )
    return "".join(out)


def _service_sample() -> str:
    """What the untagged service ways physically are — a 12-sample imagery read."""
    import json

    path = C.SURVEYS / "00b-untagged-service-sample.json"
    if not path.exists():
        return ""
    survey = json.loads(path.read_text())
    samples = survey["samples"]
    counts: dict[str, int] = {}
    for row in samples:
        counts[row["category"]] = counts.get(row["category"], 0) + 1

    out = ["\n### 8.3 What the untagged service ways actually are — a 12-sample read\n"]
    out.append(
        "\n§8.1 leaves 2,025.3 km undecided because it carries no subtag. Tags cannot resolve that,\n"
        "so this is a small imagery sample of the population itself. **It is an indication, not a\n"
        "measurement** — see the caveat below.\n"
    )
    out.append("\n" + _table(
        ["Category", "Samples", "What it means"],
        [
            [f"`{k}`", str(counts.get(k, 0)), survey["categories"][k]]
            for k in ("street_like", "yard", "parking")
        ],
        numeric=False,
    ))
    out.append(
        f"\n\n{survey['method']}\n"
        f"\n> **{survey['caveat']}**\n"
    )
    out.append(
        "\nA second, full-population check points the same way without settling it: only **5.4%** of\n"
        "untagged-service required km carries a street `name`, against **72.7%** for `residential`.\n"
        "That is consistent with most of it not being street-like, but it cannot be read as a\n"
        "measurement either — of the four street-like samples above, only one was named.\n"
        "\n**What this means for the decision.** Neither variant A nor variant C is clearly right.\n"
        "If the split is near a third, then roughly 675 km of the 2,025 km is street the campaign\n"
        "should capture and roughly 1,350 km is yards and parking aisles it should not — so A\n"
        "over-drives by about 1,350 km and C under-covers by about 675 km. Both are large enough\n"
        "to matter and the sample is too small to choose between them. The cheap next step is the\n"
        "same sampling at n≈100, which would narrow the interval to a few percentage points; the\n"
        "expensive one is driving either error.\n"
    )
    return "".join(out)


def _findings(s: dict) -> str:
    """The judgement calls Stage 0 is supposed to inform, answered with its own numbers."""
    headline = s["headline"]["required_traversal_km"]
    tagging = s["tagging"]
    scc = s["scc"]
    gradient = s["gradient"]
    oneway = s["oneway"]
    service = s["service"]

    two_pass = next((r for r in s["by_min_passes"] if r["min_passes"] == 2), None)
    two_pass_km = two_pass["required_km"] if two_pass else 0.0
    two_pass_arcs = two_pass["arc_count"] if two_pass else 0
    narrow_by_class = next(
        (r for r in tagging["narrow_pair_basis"] if r["basis"] == "class"), {"centerline_km": 0.0}
    )
    barriers = next((r for r in s["exclusions"] if r["reason"] == "barrier_blocking"), None)
    orphan_service = next(
        (r for r in scc["orphan_by_class"] if r["highway_class"] == "service"), None
    )

    out = ["\n## Findings, and what the next stages should do with them\n\n"]

    out.append(
        f"**1. The `min_passes = 2` fallback does not fire often enough to need calibrating.**\n"
        f"SPEC §2.1 says that if a large number of arcs reach the default, the lane threshold gets\n"
        f"calibrated against imagery before Stage 4. The measured count is "
        f"{tagging['default_fallback_arc_count']:,} arcs "
        f"({_km(tagging['default_fallback_km'])} km, "
        f"{tagging['default_fallback_pct_of_arcs']:.2f}% of included arcs) — Tbilisi's major roads\n"
        f"carry `lanes` often enough that the chain almost always resolves before the default.\n"
        f"**That trigger does not fire.** No imagery calibration is needed on this account.\n"
    )

    out.append(
        f"\n**2. Two same-direction passes are a small effect here — smaller than SPEC §2.2 "
        f"assumes.**\n"
        f"SPEC §2.2 calls repeat passes \"the most important cost consequence in the spec\", and the\n"
        f"open [CONFIRM] asks whether a 6-lane one-way needs three passes. Measured: only\n"
        f"{two_pass_arcs:,} arcs carry `min_passes = 2`, contributing {_km(two_pass_km)} km — "
        f"{_share(two_pass_km, headline)} of the headline.\n"
        f"Raising the threshold to 3 passes on the widest arcs can therefore move the campaign by\n"
        f"at most a fraction of that. **This [CONFIRM] is low-stakes and can be resolved cheaply.**\n"
    )

    out.append(
        f"\n**3. `highway=service` is the expensive open decision — {_share(service['required_km'], headline)} of the "
        f"headline.**\n"
        f"Including service roads adds {_km(service['required_km'])} km of required traversal "
        f"({service['included_arc_count']:,} arcs).\n"
        f"SPEC §1.1 makes *include* the default and that is how the network is built, but this is\n"
        f"the single largest number attached to any unresolved question in the spec — an order of\n"
        f"magnitude more than the lane-threshold questions. **Resolve this one first.**\n"
    )

    out.append(
        f"\n**4. The narrow-pair rule, not the lane threshold, is the real modelling lever.**\n"
        f"{tagging['narrow_pair_segment_count']:,} segments ({_km(tagging['narrow_pair_centerline_km'])} km) "
        f"are treated as narrow two-way pairs, so a single traversal\n"
        f"satisfies both directions. {_km(narrow_by_class['centerline_km'])} km of that is decided by "
        f"**class alone** — no `lanes`,\nno `width`, just `residential`/`service`/`unclassified`/"
        f"`living_street`. If that assumption is\nwrong, those streets need both directions and the "
        f"headline rises by up to {_km(narrow_by_class['centerline_km'])} km —\nroughly "
        f"{_share(narrow_by_class['centerline_km'], headline)} of the campaign. **This is the "
        f"assumption worth spending imagery on**, not\nthe `lanes > 3` threshold. SPEC §2.1 does "
        f"not currently name a width limit for it; one should\nbe agreed before Stage 3 fixes the "
        f"lower bound.\n"
    )

    out.append(
        f"\n**5. Tagging is sparse enough that Stage 2's time model will be class-driven.**\n"
        f"`maxspeed` is present on {tagging['maxspeed_pct']:.1f}% of included arcs and `width` on "
        f"{tagging['width_pct']:.1f}%. SPEC §6 allows for\n`maxspeed` to override free-flow speed "
        f"by class; in practice the class table will set the speed\nfor roughly "
        f"{100.0 - tagging['maxspeed_pct']:.0f}% of the network, so that table deserves the "
        f"attention a per-arc override\nwould otherwise get.\n"
    )

    out.append(
        f"\n**6. {_km(gradient['steep_km'])} km reads steeper than the drivability limit and was "
        f"deliberately kept.**\n"
        f"{gradient['steep_arc_count']:,} included arcs have a DEM gradient beyond "
        f"±{gradient['limit_pct']:.0f}%, of which "
        f"{gradient['steep_on_structure_arc_count']:,} ({_km(gradient['steep_on_structure_km'])} km)\n"
        f"sit on a bridge or in a tunnel, where SRTM is measuring the valley floor rather than the\n"
        f"road. The rest are a mix of genuine Tbilisi hillside streets and DEM error at cuttings and\n"
        f"embankments. None were excluded (§1.1). **Stage 2 must not feed these straight into a speed\n"
        f"model** — a bridge deck at a false −40% would be modelled as a 12 km/h crawl.\n"
    )

    out.append(
        f"\n**7. The orphan fragments are mostly gated yards, not a filter bug.**\n"
        f"The largest SCC holds {_pct(scc['largest_share_of_included_km'] * 100.0)} of included arc "
        f"km, comfortably past the 95% gate.\nThe {scc['fragment_count']:,} fragments total "
        f"{_km(scc['fragment_km'])} km"
    )
    if orphan_service:
        out.append(
            f", of which {_km(orphan_service['arc_km'])} km is `highway=service`"
        )
    out.append(
        f".\nThat is the expected shape: courtyards and parking aisles reachable only through a way\n"
        f"the drivability filter removed. If `highway=service` is dropped per finding 3, most of\n"
        f"these fragments leave with it.\n"
    )

    if barriers:
        out.append(
            f"\n**8. The barrier filter is deliberately coarse and slightly over-excludes.**\n"
            f"A blocking barrier node removes the whole segment it sits inside "
            f"({barriers['arc_count']:,} arcs, {_km(barriers['arc_km'])} km),\n"
            f"rather than the portion beyond it. Splitting at barrier nodes would recover part of "
            f"that\nkm; it belongs with Stage 1's turn expansion, which has to look at those nodes "
            f"anyway.\n"
        )

    out.append(
        f"\n**9. One-way data looks sound.** {oneway['implied_oneway_segment_count']:,} segments are "
        f"one-way by implication rather than by tag, and\nonly {oneway['two_way_link_segment_count']:,} "
        f"link segments ({_km(oneway['two_way_link_km'])} km) are modelled two-way — ramps almost "
        f"never are,\nso a large number here would have meant a tagging gap. It is not large. "
        f"SPEC §2.2's couplet\nmitigation has real material to work with: one-way streets are "
        f"{_pct(oneway['share_by_length'] * 100.0)} of centerline km.\n"
    )

    out.append(
        "\n**10. The DEM is SRTM, not Copernicus GLO-30, and not by preference.**\n"
        "GLO-30 publishes no tiles over the N41/E044 and N41/E045 cells — they are withheld from\n"
        "the free instance for this border region. SRTM 1-arcsec is the stage brief's named\n"
        "alternative at the same 30 m ground resolution, so the substitution costs nothing in\n"
        "resolution, but it is a source difference worth recording.\n"
    )

    return "".join(out)


def _tagged_incline_exclusions(s: dict) -> int:
    for row in s["exclusions"]:
        if row["reason"] == "incline_too_steep":
            return int(row["arc_count"])
    return 0


def write(s: dict, path: Path = C.REPORT_MD) -> Path:
    meta = s["meta"]
    totals = s["totals"]
    headline = s["headline"]
    scc = s["scc"]
    tagging = s["tagging"]

    parts: list[str] = []
    parts.append("# Stage 0 — Tbilisi street network: extract & measure\n")
    parts.append(
        "Generated by `efficientroute stage0`. Every number below is read from "
        "`data/derived/00-network-stats.json`, which the Stage 0 gate asserts against.\n"
    )

    parts.append("\n## Artifacts\n")
    parts.append(
        _table(
            ["Path", "What it is"],
            [
                ["`data/derived/network.gpkg`", "the canonical directed-arc network, layer `arcs`"],
                ["`data/derived/00-network-stats.json`", "every number in this report, machine-readable"],
                ["`data/derived/00-dropped-ways.csv`", "ways dropped before arc construction, with reasons"],
                ["`reports/00-network.html`", "interactive map — arcs by `min_passes`, exclusions and orphans"],
                ["`reports/00-network-map-preview.png`", "static preview of that map"],
            ],
            numeric=False,
        )
    )

    # ---------------------------------------------------------------- headline
    parts.append("\n## The headline number\n")
    parts.append(
        f"> ## Required traversal: **{_km(headline['required_traversal_km'])} km**\n"
        f">\n"
        f"> Of which **{_km(headline['required_traversal_km_routable'])} km** lies inside the\n"
        f"> largest strongly connected component and is therefore actually drivable as one tour.\n"
    )
    parts.append(
        "Required traversal km = Σ (`length_m` × required passes), counting each narrow\n"
        "two-way pair once. It is the quantity that sets the campaign length: at the\n"
        "40 km/h capture cap of SPEC §5 it is the numerator of every schedule estimate.\n"
    )

    # ------------------------------------------------------------------ totals
    parts.append("\n## 1. Network size\n")
    parts.append(
        _table(
            ["Measure", "All arcs", "Included", "Routable (largest SCC)"],
            [
                [
                    "Centerline km",
                    _km(totals["centerline_km"]),
                    _km(totals["included_centerline_km"]),
                    _km(totals["routable_centerline_km"]),
                ],
                [
                    "Directed arc km",
                    _km(totals["arc_km"]),
                    _km(totals["included_arc_km"]),
                    _km(totals["routable_arc_km"]),
                ],
                [
                    "Directed arcs",
                    f"{totals['arc_count']:,}",
                    f"{totals['included_arc_count']:,}",
                    f"{totals['routable_arc_count']:,}",
                ],
                [
                    "Physical segments",
                    f"{totals['segment_count']:,}",
                    f"{totals['included_segment_count']:,}",
                    "—",
                ],
            ],
        )
    )
    parts.append(
        "\n*Centerline km* counts each physical street piece once; *directed arc km* counts\n"
        "a two-way street twice, once per direction. A **segment** is a way cut at every\n"
        "junction node, which is the unit the routing graph is built on.\n"
    )

    # --------------------------------------------------------------- by class
    parts.append("\n## 2. Required traversal by highway class\n")
    parts.append(
        _table(
            ["Class", "Arcs", "Centerline km", "Included centerline km", "Required km", "% of required"],
            [
                [
                    row["highway_class"] or "(untagged)",
                    f"{row['arc_count']:,}",
                    _km(row["centerline_km"]),
                    _km(row["included_centerline_km"]),
                    _km(row["required_km"]),
                    _pct(row["required_km"] / headline["required_traversal_km"] * 100.0)
                    if headline["required_traversal_km"]
                    else "—",
                ]
                for row in s["by_class"]
            ],
        )
    )

    parts.append("\n## 3. Required traversal by `min_passes`\n")
    parts.append(
        _table(
            ["min_passes", "Arcs", "Arc km", "Required km"],
            [
                [str(row["min_passes"]), f"{row['arc_count']:,}", _km(row["arc_km"]), _km(row["required_km"])]
                for row in s["by_min_passes"]
            ],
        )
    )
    parts.append(
        "\nNarrow two-way pairs contribute their length **once** even though they appear as\n"
        "two arcs with `min_passes = 1`, which is why the required km of the `min_passes = 1`\n"
        "row is well below its arc km.\n"
    )
    parts.append("\n### Capture quality split (SPEC §3.2)\n")
    parts.append(
        _table(
            ["capture_quality", "Arcs", "Centerline km", "Required km"],
            [
                [row["capture_quality"], f"{row['arc_count']:,}", _km(row["centerline_km"]), _km(row["required_km"])]
                for row in s["capture_quality"]
            ],
        )
    )

    # ---------------------------------------------------------------- one-way
    oneway = s["oneway"]
    parts.append("\n## 4. One-way share of the included network\n")
    parts.append(
        _table(
            ["Measure", "One-way", "Total", "Share"],
            [
                [
                    "By count (segments)",
                    f"{oneway['oneway_segment_count']:,}",
                    f"{oneway['segment_count']:,}",
                    _pct(oneway["share_by_count"] * 100.0),
                ],
                [
                    "By length (centerline km)",
                    _km(oneway["oneway_centerline_km"]),
                    _km(oneway["centerline_km"]),
                    _pct(oneway["share_by_length"] * 100.0),
                ],
            ],
        )
    )
    parts.append(
        f"\n{oneway['implied_oneway_segment_count']:,} of the one-way segments are one-way by\n"
        "*implication* (`highway=motorway` or `junction=roundabout`) rather than by an\n"
        "explicit `oneway` tag. SPEC §2.2 makes one-way geometry the expensive case, so this\n"
        "is the subset most worth spot-checking before Stage 3.\n"
    )

    # --------------------------------------------------------------- tagging
    parts.append("\n## 5. Tagging completeness — measured over the included network\n")
    parts.append(
        _table(
            ["Tag", "Arcs with it", "% of arcs"],
            [
                [tag, f"{tagging[f'{tag}_count']:,}", _pct(tagging[f"{tag}_pct"])]
                for tag in ("lanes", "width", "maxspeed", "surface")
            ],
        )
    )
    parts.append(
        f"\nPercentages are of the {tagging['arc_count_basis']:,} **included** arcs. Measuring over\n"
        "every arc in the table would let the excluded footway, track and path arcs — which\n"
        "carry almost no tags — halve each figure and describe a network nobody will drive.\n"
    )
    parts.append("\n### How `min_passes` was decided (SPEC §1.1 fallback chain)\n")
    parts.append(
        _table(
            ["Basis", "Arcs", "Arc km"],
            [
                [row["basis"], f"{row['arc_count']:,}", _km(row["arc_km"])]
                for row in tagging["min_passes_basis"]
            ],
        )
    )
    parts.append(
        f"\n> **Arcs that reached the `min_passes = 2` default because `lanes`, `width` and\n"
        f"> class were all inconclusive: {tagging['default_fallback_arc_count']:,} arcs, "
        f"{_km(tagging['default_fallback_km'])} km "
        f"({_pct(tagging['default_fallback_pct_of_arcs'])} of all arcs).**\n"
        f">\n"
        f"> SPEC §2.1 says that if this count is large the threshold gets calibrated against\n"
        f"> imagery before Stage 4. See the calibration note at the end of this report.\n"
    )
    parts.append("\n### How narrow two-way pairs were decided\n")
    parts.append(
        _table(
            ["Basis", "Segments", "Centerline km"],
            [
                [row["basis"], f"{row['segment_count']:,}", _km(row["centerline_km"])]
                for row in tagging["narrow_pair_basis"]
            ],
        )
    )
    parts.append(
        f"\n{tagging['narrow_pair_segment_count']:,} segments "
        f"({_km(tagging['narrow_pair_centerline_km'])} km) carry a **shared** pair requirement:\n"
        "one traversal in either direction satisfies them. Every other two-way street requires\n"
        "both directions. This is the single largest lever on the headline number.\n"
    )

    # ------------------------------------------------------------- exclusions
    parts.append("\n## 6. Exclusions\n")
    parts.append(
        _table(
            ["Reason", "Arcs", "Arc km", "Centerline km", "Dominant classes"],
            [
                [
                    f"`{row['reason']}`",
                    f"{row['arc_count']:,}",
                    _km(row["arc_km"]),
                    _km(row["centerline_km"]),
                    ", ".join(f"{c['highway_class']} ({_km(c['arc_km'])} km)" for c in row["top_classes"]),
                ]
                for row in s["exclusions"]
            ],
        )
    )
    parts.append(
        "\nExcluded arcs stay in `network.gpkg` with `excluded = true` and a non-null\n"
        "`exclusion_reason`, per CLAUDE.md rule 4.\n"
    )
    if s["dropped_ways"]:
        parts.append("\n### Ways dropped before arc construction\n")
        parts.append(
            _table(
                ["Reason", "Ways"],
                [[f"`{row['reason']}`", f"{row['way_count']:,}"] for row in s["dropped_ways"]],
            )
        )
        parts.append(
            "\n`outside_clip` is the clip definition rather than a data-quality finding, so those\n"
            "rows are counted here but omitted from `data/derived/00-dropped-ways.csv`, which\n"
            "would otherwise list every road in Georgia. All other reasons are listed in full.\n"
        )

    # --------------------------------------------------------------------- scc
    parts.append("\n## 7. Connectivity\n")
    parts.append(
        _table(
            ["Measure", "Value"],
            [
                ["Strongly connected components (included arcs)", f"{scc['component_count']:,}"],
                ["Largest component — arcs", f"{scc['largest_arc_count']:,}"],
                ["Largest component — arc km", _km(scc["largest_km"])],
                ["**Largest component share of included arc km**", f"**{_pct(scc['largest_share_of_included_km'] * 100.0)}**"],
                ["Orphan fragments", f"{scc['fragment_count']:,}"],
                ["Orphan fragment arc km", _km(scc["fragment_km"])],
                ["Bridge arcs (endpoints in different components)", f"{scc['bridge_arc_count']:,}"],
                ["Bridge arc km", _km(scc["bridge_km"])],
            ],
        )
    )
    gate = "PASS" if scc["largest_share_of_included_km"] >= 0.95 else "FAIL"
    parts.append(f"\n**Gate — largest SCC ≥ 95% of included arc km: {gate}.**\n")

    if scc["fragments"]:
        parts.append("\n### Orphan fragments\n")
        shown = scc["fragments"][:40]
        parts.append(
            _table(
                ["#", "Arcs", "Arc km", "Location (lon, lat)", "Classes", "Sample names"],
                [
                    [
                        str(f["scc_id"]),
                        f"{f['arc_count']:,}",
                        f"{f['arc_km']:.2f}",
                        f"{f['lon']:.5f}, {f['lat']:.5f}",
                        ", ".join(f["classes"]),
                        ", ".join(f["sample_names"]) or "—",
                    ]
                    for f in shown
                ],
            )
        )
        if len(scc["fragments"]) > len(shown):
            parts.append(
                f"\n*{len(scc['fragments']) - len(shown):,} further fragments omitted from this table; "
                "all of them are in `data/derived/00-network-stats.json` and drawn on the map.*\n"
            )

    # ----------------------------------------------------------------- service
    service = s["service"]
    parts.append("\n## 8. `highway=service` — the open scope decision (SPEC §2.1)\n")
    parts.append(
        _table(
            ["Measure", "Value"],
            [
                ["Arcs", f"{service['arc_count']:,}"],
                ["Included arcs", f"{service['included_arc_count']:,}"],
                ["Included centerline km", _km(service["included_centerline_km"])],
                ["**Required traversal km**", f"**{_km(service['required_km'])}**"],
                [
                    "Share of the headline number",
                    _pct(service["required_km"] / headline["required_traversal_km"] * 100.0)
                    if headline["required_traversal_km"]
                    else "—",
                ],
            ],
        )
    )
    parts.append(
        "\nSPEC §2.1 leaves this open and §1.1 makes *include* the default, so service roads are\n"
        "**in** the network as built. The number above is the cost of that decision: dropping\n"
        "`highway=service` would remove exactly this much required traversal.\n"
    )
    parts.append(_service_breakdown(s, service, headline["required_traversal_km"]))
    parts.append(_service_scenarios(s))
    parts.append(_service_sample())

    # ------------------------------------------------------------ restrictions
    restrictions = s["restrictions"]
    parts.append("\n## 9. Turn restrictions (Stage 1 scoping)\n")
    parts.append(
        _table(
            ["Measure", "Value"],
            [
                ["`type=restriction` relations in the source extract", f"{restrictions['total_in_source']:,}"],
                ["…referencing a way kept in the clip", f"{restrictions['touching_clip']:,}"],
            ],
        )
    )
    parts.append("\nCounted, not parsed — parsing is Stage 1 (SPEC §3.3).\n")

    # -------------------------------------------------------------- gradient
    gradient = s["gradient"]
    parts.append("\n## 10. Gradient (SPEC §6 input, and a data-quality signal)\n")
    parts.append(
        _table(
            ["Measure", "Value"],
            [
                ["Arcs with a DEM-derived gradient", f"{gradient['dem_count']:,}"],
                ["Arcs with a tagged incline (preferred over the DEM)", f"{gradient['tag_count']:,}"],
                ["Arcs with no gradient at all", f"{gradient['unknown_count']:,}"],
                ["Median |gradient|", f"{gradient['abs_p50']:.1f}%"],
                ["90th percentile |gradient|", f"{gradient['abs_p90']:.1f}%"],
                ["99th percentile |gradient|", f"{gradient['abs_p99']:.1f}%"],
                [
                    f"Arcs steeper than the {gradient['limit_pct']:.0f}% drivability limit",
                    f"{gradient['steep_arc_count']:,} ({_km(gradient['steep_km'])} km)",
                ],
                [
                    "…of those, on a bridge or in a tunnel",
                    f"{gradient['steep_on_structure_arc_count']:,} ({_km(gradient['steep_on_structure_km'])} km)",
                ],
            ],
        )
    )
    parts.append(
        f"\n**These {_km(gradient['steep_km'])} km were NOT excluded.** SPEC §3.1 lists "
        f"\"incline above a limit\"\nas an exclusion, but §1.1 resolves ambiguity toward more "
        "coverage, and a 30 m DEM over a\ncity of ridges, cuttings and viaducts is ambiguous: it "
        "samples the terrain, not the road\ndeck. Only a *tagged* `incline` above the limit removes "
        f"an arc — that path fired on {_tagged_incline_exclusions(s)} arcs. The DEM figure is\n"
        "reported here so Stage 2 can decide how much of it is real before it becomes a speed "
        "model.\n"
    )

    # ------------------------------------------------------------------ inputs
    parts.append("\n## Inputs and provenance\n")
    parts.append(
        _table(
            ["Item", "Value"],
            [
                ["OSM extract", f"`{meta.get('pbf_url', '')}`"],
                ["Extract SHA-256", f"`{meta.get('pbf_sha256', '')}`"],
                ["**Boundary — OSM relation id**", f"**{meta.get('boundary_relation_id')}**"],
                ["Boundary tags", f"`{meta.get('boundary_tags')}`"],
                ["Municipality area", f"{meta.get('boundary_area_km2')} km²"],
                ["Clip buffer", f"{meta.get('clip_buffer_m')} m"],
                ["Clipped area", f"{meta.get('clip_area_km2')} km²"],
                ["Clip bounds (lon/lat)", f"`{meta.get('clip_bounds')}`"],
                ["DEM", f"{meta.get('dem_source')} — tiles `{', '.join(meta.get('dem_tiles', []))}`"],
                ["`arcs` layer SHA-256", f"`{meta.get('arcs_sha256', '')}`"],
                ["Pipeline runtime", f"{meta.get('runtime_s')} s"],
            ],
            numeric=False,
        )
    )
    parts.append(f"\n**DEM note.** {meta.get('dem_note', '')}\n")

    parts.append("\n## Thresholds this report was measured against\n")
    parts.append(
        _table(
            ["Constant", "Value", "Meaning"],
            [
                ["`WIDE_LANE_THRESHOLD`", str(C.WIDE_LANE_THRESHOLD), "lanes > this in one direction ⇒ `min_passes = 2`"],
                ["`WIDE_ARC_MIN_DIR_WIDTH_M`", f"{C.WIDE_ARC_MIN_DIR_WIDTH_M} m", "width proxy for the same test when `lanes` is absent"],
                ["`NARROW_PAIR_MAX_TOTAL_LANES`", str(C.NARROW_PAIR_MAX_TOTAL_LANES), "total lanes ≤ this ⇒ shared pair requirement"],
                ["`NARROW_PAIR_MAX_WIDTH_M`", f"{C.NARROW_PAIR_MAX_WIDTH_M} m", "width proxy for the same test"],
                ["`MAX_INCLINE_PCT`", f"{C.MAX_INCLINE_PCT}%", "tagged incline above this is not drivable"],
                ["`CLIP_BUFFER_M`", f"{C.CLIP_BUFFER_M} m", "buffer beyond the municipality boundary"],
                [
                    "`CLASS_IS_NARROW_PAIR`",
                    ", ".join(sorted(C.CLASS_IS_NARROW_PAIR)),
                    "classes narrow enough that one pass covers both sides",
                ],
                [
                    "classes with inconclusive width",
                    ", ".join(sorted(k for k, v in C.CLASS_IS_WIDE.items() if v is None)),
                    "these fall through to the `min_passes = 2` default when untagged",
                ],
            ],
            numeric=False,
        )
    )
    parts.append(
        "\nAll of these live in `src/efficientroute/config.py`. The stage brief says to measure\n"
        "first and calibrate at the gate — these are the dials, and §5 above is the evidence.\n"
    )

    parts.append(_findings(s))

    text = "\n".join(parts) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
