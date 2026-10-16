# GPX Improver — mission brief

> Written 2026-10-16 by Zuka with Claude in a planning session. It is based on an interview plus a look at this repo, Elisabed's branch, and `survey-navigator-preview`. A fresh Claude Code session executes it:
> `claude "Read docs/superpowers/specs/2026-10-16-gpx-improver-design.md and execute it. The car leaves at 10:00 tomorrow."`

## 0. Situation

- **Deadline:** a complete, checked, re-planned set of days must be on the driver's phone (STS NAV app) before **10:00 on 2026-10-17** (Tbilisi, UTC+4). Aim to have it deployed by **08:30**.
- **Who you work with:** Zuka (repo owner). Ask only when blocked on a decision that is theirs. Log every other judgment call in `GPX_Improver/DECISIONS.md`.
- **Priority order:**
  1. A complete plan that passes every gate.
  2. The viewer, so Zuka can review it.
  3. Optimisation.
  4. The interactive editor (Phase 2, after tomorrow).

  Never trade 1 for 3.

## 1. What already exists (inspected 2026-10-16)

| Input | Facts |
|---|---|
| `Parking_Routing/day_01..09.gpx` (untracked) | The current plan.<br>• GPX 1.1, creator `tbilisi-parking-planner` (source not found).<br>• A `<rte>` with depot start/end, plus one `<trk>`.<br>• ~117 km/day under a "max 120 km" cap; 945 km in total. |
| `Parking_Database_City_Hall/parking_09.*` (untracked; Zuka renamed it from the tracked `Parking_Database/`) | 3,305 polygons, EPSG:32638, areas 9–7,087 m². Fields include:<br>• `PARKIREBIS`: the address, in legacy Latin-font Georgian (e.g. `vaJa-fSavelas gamziri`)<br>• `MANQANIS_A`: number of spaces<br>• `ZONE_ID`: A (2,197) or ALL (1,108) |
| `origin/Elisabed` @ 7e54661 → `Parking_Database/proposed_parking_shp/Parking_lot.*` | 657 polygons, EPSG:32638.<br>• Fields `n_cars`, `length_m`, `ptype` (parallel 467 / perpendicular 148 / angle 42).<br>• Only 20 of them touch City Hall lots.<br>• Byte-identical to the copy on Elisabed's site. |
| Already filmed (14 Oct) | `https://tbilisi-parking.elisabed-archvadze.workers.dev/zuka_covered.geojson`<br>• 340 LineStrings, each a whole junction-to-junction edge with several vertices; 42.3 km in total; `passes`=1.<br>• `street_id` = `<osmNodeA>_<osmNodeB>_<metres>`, with A<B always, so it does **not** encode direction.<br>• 2,207 of 2,217 vertices sit exactly on navigator-graph nodes, so match by coordinates.<br>• Direction rule: see §2. Download and commit a copy. |
| Navigator street graph | `/Users/mat/GitHub/STS-Labs/survey-navigator-preview/data/tbilisi-net.json` (3.9 MB). Its decoder is in that repo's `js/core.js`; it is built by `tools/build_network.py` from Geofabrik georgia-latest.<br>**No OSM ids.**<br>• `nodes`: delta-encoded lon,lat ×1e6 pairs, lon first.<br>• `ways` rows: `[flags, nameIdx, enIdx, refIdx, …delta-encoded node indices]`. Flags carry class, `oneway` (1/-1/0), `round`, `denied` (access no/private) and `minor` (parking_aisle/driveway/drive-through).<br>• `restrictions` rows: `[fromWayIdx, viaNodeIdx, toWayIdx, kind]`; kinds 5–7 are "only" rules.<br>• bbox [44.6, 41.6, 45.1, 41.86].<br>Key everything by node coordinates. The depot is 0.11 m from the nearest node, so snap it. |
| Navigator checks | Node scripts; there is no package.json.<br>• `node tests/plan_check.mjs <gpx> <net.json>` works on any GPX path. It reports wrong-way driving, banned turns, private streets, U-turns not at dead ends, and off-network driving.<br>• **`plan_check.mjs` and `route_check.mjs` always exit 0**, so gates must parse their printed counts.<br>• `tests/drive_test.mjs` exits 1 on failure.<br>• plan_check counts a node as a "dead end" only if it has degree 1 in the whole network, including denied/minor ways. 851 public street ends continue into such stubs, so plan_check does not treat them as dead ends.<br>• plan_check also flags bearing flips of ≥165°, and two same-side turns of ≥60° within 30 m that drive back. |
| Navigator route input | `parseGpx` in `js/core.js:43-59`:<br>• It reads only `<trkpt lat lon>`, in file order. It uses rtepts only if there are fewer than 2 trkpts.<br>• A point snaps to a street only within 1.2 m of a node or 4 m of a segment.<br>• Consecutive points are joined by a street path of at most 3× the straight distance + 40 m. Otherwise the app draws an off-street straight line.<br>Bundled days are hardcoded in `js/days.js:2-8` and in the `SHELL` list at `sw.js:15-29`.<br>• The cache name `APP` (`sw.js:3`) is `sn-app-12` on **origin/main**. Local main is one commit behind (it lacks v1.5.4).<br>• Currently bundled: 6 older days `day_0N_nav.gpx` (creator `make_osmand_nav`, start 41.705740, 44.773655) plus `zuka-testdrive.gpx`. These are **not** the 9-day set.<br>• Deployed by GitHub Pages from the root of `main`. Any push to `main` goes live immediately. |
| Prior art (borrow ideas, don't depend on them) | • `survey-navigator-preview`, branch `worktree-gpx-cleaner`: a MapLibre editor with Esri World Imagery, U-turn classification and legal rerouting (`js/edit.js`).<br>• `Zuka-ChinesePostman-EfficientRoute/src/efficientroute/`: `routeio.write_gpx`, `trace.read_gpx`, `bearings.classify_turn`, `coverage.*`. Its SPEC (front and rear cameras, 9 h shift, a different depot) does **not** apply. Its `.venv` points at an old path; use your own uv environment. |

**Diagnosis of the current routes** (from forensic analysis; the method is inferred):
- **How they were made:** a router sent to each target in turn (visit-the-targets routing, OSRM-style). The result is one city-wide sequence chopped into ~117 km days. It ignores which side of the street a lot is on, and it doesn't credit lots passed along the way.
- **Repeats:** 66% of the 945 km re-drives a street already driven. Only ~322 km is distinct street, and each covered lot is passed 4.3 times on average.
- **Empty driving:** 61% of the km has no lot within 15 m. There are 604 real U-turns (51% of them mid-street) and ~55 km of dead-end spurs.
- **Day areas** overlap by 80–94%, and day 9 adds no new lots.
- **Wrong side:** the lot is on the right in only 48% of passes.
- **Coverage:** Zone A 90%, Zone ALL 26%, proposed 29%.

The new plan must fix all of these.

## 2. Settled decisions (Zuka's — do not reopen)

| Topic | Decision |
|---|---|
| Coverage rule | A lot counts as covered when the car passes it with the lot on the **right**.<br>• **One-way streets:** either side counts.<br>• **Two-way streets** with lots on both sides need a pass in each direction. |
| Scope | **Every** City Hall lot (3,305, Zone A and ALL) and every proposed lot (657), city-wide. |
| Already filmed | Lots covered by the 14 Oct drive (`zuka_covered.geojson`) **count as done**, and are shown as filmed.<br>• Each line's coordinate order **is the driving direction** (Zuka confirmed).<br>• Credit lots on the right of the drawn direction; on one-way edges either side counts. |
| Day limit | **≤ 120 km/day, including depot legs.** The number of days follows from that. |
| Depot | **Fixed:** Kobuleti street, 41.7057010, 44.7737930. Every day starts and ends there. |
| Objective | **Simple to drive:** no doubling back, no pointless streets, few awkward turns. Total km and day count are secondary. |
| Turns | No single global rule.<br>• Turn costs are **configurable** per turn type (U-turn / left / right / straight) and by road class.<br>• Specific places are handled by edits.<br>• Turn restrictions and one-ways are always hard constraints. |
| Edits (v1 contract) | • **Street not needed:** drop it from required coverage; it stays drivable.<br>• **Block / force street:** forbid driving it, or require a pass.<br>No lot-level or day-assignment edits. |
| Tool shape | A local app on this Mac. Map viewer now; **map editor + re-plan** in Phase 2. |
| Delivery | **Bundle the new days into STS NAV** (`survey-navigator-preview`) and redeploy.<br>• **Keep** the 6 old days and TestDrive in the app list, and **add** the new days alongside.<br>• **Never deploy without Zuka's explicit OK.** No OK means no push, even if every gate passes. |

**Calls Claude made while writing this brief** (Zuka: check these, and override any):
1. **Lot-to-street assignment:** a lot belongs to the street it runs along (parallel, nearest), not just the nearest street. Every frontage edge it overlaps is required.
2. **Turnarounds:** only at effective dead ends, never mid-street.
3. **Distance limit:** D = 20 m by default, with a sensitivity report.
4. **First day:** tomorrow's day is the district nearest the depot.
5. **Folder layout:**
   - `Parking_Database_City_Hall/`
   - `Parking_Database_Proposed/`
   - `Parking_Routing/original_9day/`
   - `Parking_Routing/plan_v2/`
   - `GPX_Improver/` for the code
6. **Satellite imagery:** Esri World Imagery (no API key), not Google tiles.
7. **Edits file:** one `edits.geojson` file is the contract; the planner reads it and the Phase 2 UI writes it.
8. **Baseline:** the old-vs-new comparison uses the 9-day set. The app's 6-day set is shown for reference.
9. **Day count:** the sanity range is 3–8 days. If the plan falls outside it, log that and keep going.
10. **Brief location:** this brief lives in `docs/superpowers/specs/`, the STS-Labs superpowers convention.

## 3. Method — the "logical" re-plan (rule-based and explainable; the details are the builder's)

1. **Graph.** Decode `tbilisi-net.json` into a directed street graph:
   - Honour `oneway` and roundabouts.
   - Drop `denied` edges.
   - Avoid `minor` service edges unless forced.
   - Treat turn restrictions as hard.

   Plan on **this** graph, so every output point lies on the navigator's own geometry.
2. **Lots → requirements.** A lot belongs to **the street it runs along** (Claude's call). 1,920 City Hall lots are within 20 m of more than one way, so "nearest" alone goes wrong at corners and on divided avenues.
   - **Candidates:** the edges within D of the polygon (default 20 m, configurable). Report how the result changes at 10, 15, 20 and 25 m.
   - **Assignment:**
     - Keep the candidates roughly parallel to the lot's long axis (from its minimum rotated rectangle), nearest first.
     - Assign the lot to every such edge whose frontage it meaningfully overlaps. **All** of those edges are required, so long bays get filmed end to end.
     - Corner lots go to the parallel street.
   - **Side from geometry:**
     - Two-way edge: the direction that puts the lot on the right.
     - One-way edge: its legal direction (either side counts).
     - On divided avenues each carriageway is its own one-way edge. A lot is assigned to the carriageway on its own curb, so it is never credited from the far carriageway across a median.
   - **Unreachable lots:** lots with no suitable edge within D go to an `unreachable` list with a reason (e.g. an off-street car park). Never silently drop a lot.
3. **Subtract** the filmed coverage (direction rule in §2), then apply edits (`not_needed`, `block`, `force`). Match both to graph edges by coordinates.
4. **Runs.** Merge required directed edges into long straight-through chains along the same street ("runs"). Runs are the planning unit a driver understands.
5. **Districts.**
   - Group runs into compact daily areas, so each day stays ≤ 120 km including depot legs.
   - Day hulls should barely overlap.
   - Tomorrow's day is the district nearest the depot (builder's call; log it).
6. **Order within a day.** Use greedy next-run selection with turn-penalised shortest paths, then local improvement (2-opt / or-opt / relocate).
   - **Credit any required edge driven incidentally on a connector.** This is the core fix over the old planner.
   - **Turnarounds** only at **effective dead ends** (Claude's call): nodes where the car can't legally continue on a public, non-minor street. That means true dead ends, plus street ends that continue only into denied/minor stubs. Never mid-street. List every turnaround in the report and show it in the viewer.
7. **Close and balance.** Add depot legs, enforce the 120 km cap, and move runs between neighbouring days to balance them.
8. **Write GPX.**
   - Points: every graph node along the path, with no duplicate consecutive points and no sub-metre back-and-forth.
   - Format: keep the current OsmAnd-compatible shape (a `<rte>` with depot start/end carrying `osmand:trkpt_idx`, plus one `<trk>`).
   - Use creator `gpx-improver` and names `Parking survey day N (… km)`.

**Edits file.** Edits live in one file, `GPX_Improver/edits.geojson`.
- Each feature is a LineString along graph edges, matched to the graph by node coordinates (the graph has no OSM ids).
- Each feature carries `action ∈ {not_needed, block, force}` and a `note`.
- The planner reads the file; the Phase 2 UI writes it. Until the UI exists, Zuka's review fixes go into this file directly.

## 4. The viewer (needed tonight for Zuka's review)

One command (e.g. `make view`) opens a local page served from Python.
- **Basemaps:** satellite (Esri World Imagery, no API key) and a street map (OSM or Carto), with a toggle.
- **Layers:**
  - City Hall lots and proposed lots, coloured by status: covered on the right / passed only on the wrong side / not covered / filmed 14 Oct / unreachable / not needed.
  - The 14 Oct filmed streets.
  - The depot.
- **Route sets:** a selector for "current 9-day" (the baseline), "app 6-day" (the set STS NAV bundles today) or "new plan".
  - Each day can be toggled on and off, with its own colour and direction arrows.
  - Connector stretches (no lot on the right within D) are highlighted.
- **Day panel:** per-day km, productive km, connector km, re-driven km, U-turns, left turns and new lots. Clicking a day zooms to it. Animated playback is optional.
- **Phase 2:** click a street to mark it not needed / block / force, which writes `edits.geojson`. A "Re-plan" button runs the planner and reloads.

Use the same metric code for the current routes and the new plan, so the comparison is fair. The current GPX must first be snapped to the graph; ~80% of its points are already OSM nodes.

## 5. Layout and housekeeping (Step 0, ~10 min, in Zuka's checkout)

1. On branch `gpx-improver`, run `git merge origin/Elisabed`.
2. Folder layout (Claude's call; log it):
   - `Parking_Database_City_Hall/parking_09.*`: keep Zuka's rename and commit it as a rename.
   - `Parking_Database_Proposed/Parking_lot.*`: moved from Elisabed's path.
   - `Parking_Routing/original_9day/day_0N.gpx`: the current plan, kept unchanged.
3. Add a root `.gitignore` covering `.DS_Store`.
4. Stage files by explicit path. Never use `git add -A`.
5. Code goes in `GPX_Improver/`: Python ≥3.11 managed by uv, with tests and `Makefile` targets.
   - Run outputs go to `GPX_Improver/output/` (gitignored).
   - The approved plan is committed to `Parking_Routing/plan_v2/` as `day_NN.gpx`, `report.md` and `plan.geojson`.

## 6. Gates — tests must assert (a plan that fails any gate is not shippable)

1. **Day length.** Every day starts and ends at the depot and is **≤ 120.0 km**.
2. **Navigator compatibility.** For each output file, run `node tests/plan_check.mjs <gpx> data/tbilisi-net.json`, plus `route_check.mjs` and `drive_test.mjs`. **Parse the printed counts**, because plan_check and route_check always exit 0. Required:
   - 0 wrong-way, 0 banned turns, 0 denied/private, 0 off-network.
   - Every U-turn plan_check reports is either on the planner's effective-dead-end turnaround list, or a plan_check hairpin false positive listed with its coordinates. No mid-street U-turns.

   Report the results per file. Never pipe a step whose exit status matters.
3. **Coverage.** 100% of required lots are covered on the correct side by some day. "Required" means all lots, minus filmed, minus `not_needed`, minus unreachable. Report the count and the list for every exclusion bucket.
4. **Geometry.** Every output point is a graph node. Never invent geometry.
5. **Determinism.** The same inputs give byte-identical outputs.
6. **Report.** `report.md` computes every number; no hand-typed figures. It covers:
   - per-day and total metrics
   - the old-vs-new comparison
   - the D-sensitivity results
   - the turn-cost settings used
   - unreachable lots, with addresses

## 7. Delivery (after Zuka has reviewed the plan in the viewer)

In `survey-navigator-preview`:
1. Branch from **`origin/main`**, not local main, which is one commit behind. Don't touch `worktree-gpx-cleaner`.
2. Add the new days under `data/routes/`, e.g. `v2_day_NN.gpx`.
3. Add them to the day list in `js/days.js` and to the `SHELL` list in `sw.js`. **Keep** the 6 old days and TestDrive. Bump `APP` to `sn-app-13`.
   - Check how bundled days are labelled (`js/app.js:188` relabels them "დღე N"), so the new days are clearly distinguishable from the old ones on the phone.
4. Run `plan_check`, `route_check` and `drive_test` on each bundled file. Serve the app locally (`python3 -m http.server 8790`) and confirm every day loads.
5. Deploy by merging/pushing to `main` (GitHub Pages; live immediately). **Only after Zuka's explicit OK.**
6. Zuka then checks on the phone that each day loads, shows the right length and snaps to the streets.

## 8. Fallback and stop rules

- **Ready for review.** As soon as a plan passes every gate, tell Zuka it's ready to review in the viewer. Include the `make view` command and the summary numbers. Plan and viewer come before polish.
- **No OK from Zuka.** Don't deploy. Leave the branch ready and give Zuka the backup: open `Parking_Routing/plan_v2/*.gpx` on the phone through STS NAV's file picker, which needs no deploy.
- **Plan not ready at 07:30.** If no complete plan passes every gate by 07:30, ship the days that do pass. Tomorrow's day must be one of them. Tell Zuka exactly what's missing.
- **Day count outside 3–8.**
  - The rough estimate is ~215–240 km of required directed driving (City Hall ~180–205 km, proposed ~34 km). With connectors and depot legs, that is about 4–6 days.
  - If the result falls outside 3–8, sanity-check the requirement model and log the finding in the report. Don't stop and wait.
- **Gates and data problems.** Never weaken a gate to make a plan pass. Surface data problems in the report, e.g. a one-way conflict near 41.6954, 44.7963, or lots far from any street.

## 9. Final report to Zuka

- What was built, and where.
- The commands: `make view` and `make plan`.
- New plan vs old: days, km, connector %, re-driven %, U-turns, and coverage per layer.
- Unreachable lots.
- The decisions log.
- Delivery status.
- What Phase 2 still needs: the editor + re-plan loop, and ingesting the real driven trace.
