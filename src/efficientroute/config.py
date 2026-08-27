"""Stage 0 configuration.

Every threshold that could change the headline number lives here, so that the
Stage 0 gate can calibrate them against measured counts rather than against
prose.  SPEC.md is the contract; the docstrings below name the clause each
constant implements.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- paths

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"
REPORTS = ROOT / "reports"

PBF_URL = "https://download.geofabrik.de/europe/georgia-latest.osm.pbf"
PBF_PATH = RAW / "georgia-latest.osm.pbf"
BOUNDARY_PATH = RAW / "tbilisi-boundary.geojson"
DEM_DIR = RAW / "dem"

EXTRACT_PATH = DERIVED / "00-extract.pkl.gz"
NETWORK_GPKG = DERIVED / "network.gpkg"
NETWORK_LAYER = "arcs"
DROPPED_WAYS_CSV = DERIVED / "00-dropped-ways.csv"
MANIFEST_PATH = DERIVED / "00-manifest.json"
STATS_JSON = DERIVED / "00-network-stats.json"
REPORT_MD = REPORTS / "00-network-stats.md"
REPORT_HTML = REPORTS / "00-network.html"

# --------------------------------------------------------------------------- clip

#: SPEC §3.1 — municipality boundary plus a configurable buffer so that routes
#: near the edge are not artificially trapped.
CLIP_BUFFER_M = 2000.0

#: Metric CRS for buffering only.  All stored geometry stays in EPSG:4326 and
#: all lengths are geodesic (see arcs.geodesic_length_m).
METRIC_CRS = "EPSG:32638"  # UTM zone 38N, covers Tbilisi

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

#: SPEC §5 — fixed depot.
DEPOT_LAT = 41.730736
DEPOT_LON = 44.734583

# --------------------------------------------------------------------------- scope

#: SPEC §3.1 — included AND required.  `service` is included pending the
#: [CONFIRM] in SPEC §2.1; §1.1 makes "include" the default.  Stage 0 isolates
#: it as its own report line so the decision is made against a real number.
INCLUDED_HIGHWAY_CLASSES: frozenset[str] = frozenset(
    {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
        "living_street",
        "service",
        "motorway_link",
        "trunk_link",
        "primary_link",
        "secondary_link",
        "tertiary_link",
    }
)

#: SPEC §3.2 — captured at prevailing traffic speed, stereo quality degraded.
REDUCED_QUALITY_CLASSES: frozenset[str] = frozenset(
    {"motorway", "trunk", "motorway_link", "trunk_link"}
)

# --------------------------------------------------------------------- drivability

ACCESS_KEYS: tuple[str, ...] = ("access", "vehicle", "motor_vehicle", "motorcar")
#: Most specific key wins, so iterate this order and take the last one present.
ACCESS_PRIVATE_VALUES: frozenset[str] = frozenset({"private"})
ACCESS_NO_VALUES: frozenset[str] = frozenset({"no"})

#: §1.1 resolves toward coverage: gravel, dirt, ground and cobblestone are
#: drivable in a passenger car and stay in.  Only genuinely impassable surfaces
#: are dropped.
IMPASSABLE_SURFACES: frozenset[str] = frozenset(
    {"mud", "sand", "grass", "woodchips", "ice", "snow", "salt"}
)
IMPASSABLE_SMOOTHNESS: frozenset[str] = frozenset({"impassable"})

#: Barrier node values that stop a passenger car outright.
BLOCKING_BARRIERS: frozenset[str] = frozenset(
    {"bollard", "block", "cycle_barrier", "kissing_gate", "stile", "turnstile",
     "jersey_barrier", "wall", "fence", "hedge", "planter", "debris"}
)
#: Barriers that stop a car only when locked or access-restricted.
CONDITIONAL_BARRIERS: frozenset[str] = frozenset(
    {"gate", "lift_gate", "swing_gate", "chain", "yes", "log", "sliding_gate",
     "height_restrictor", "bar"}
)

#: SPEC §3.1 "incline above a limit".  A camera car is a passenger vehicle; the
#: 12% grade named in SPEC §6 is slow but drivable, so the limit sits well above
#: it.  Applied to the *tagged* incline only — a DEM-derived gradient carries too
#: much error to justify removing coverage (§1.1).
MAX_INCLINE_PCT = 20.0

# ------------------------------------------------------------- passes thresholds

#: SPEC §2.1 — `lanes > 3` is the trigger for a second same-direction pass.
WIDE_LANE_THRESHOLD = 3

#: Width proxy for "more than 3 lanes in this direction": 3 lanes x 3.5 m plus a
#: margin.  Only consulted when `lanes` is absent (§1.1 fallback chain).
WIDE_ARC_MIN_DIR_WIDTH_M = 11.0

#: A two-way street this narrow is captured on a single pass from either
#: direction (SPEC §2.1 row 3).  A *shared* requirement is the cheaper option,
#: so under §1.1 it needs positive evidence — absence of evidence means both
#: directions are required.
NARROW_PAIR_MAX_TOTAL_LANES = 2
NARROW_PAIR_MAX_WIDTH_M = 7.0

#: Does the class alone settle "more than 3 lanes in this direction"?
#: True  -> yes, wide.   False -> yes, not wide.   None -> inconclusive, and
#: SPEC §1.1 then assigns min_passes = 2.
CLASS_IS_WIDE: dict[str, bool | None] = {
    "motorway": None,
    "trunk": None,
    "primary": None,
    "motorway_link": False,
    "trunk_link": False,
    "primary_link": False,
    "secondary": False,
    "secondary_link": False,
    "tertiary": False,
    "tertiary_link": False,
    "unclassified": False,
    "residential": False,
    "living_street": False,
    "service": False,
}

#: Does the class alone settle "narrow enough that one pass covers both sides"?
CLASS_IS_NARROW_PAIR: frozenset[str] = frozenset(
    {"residential", "living_street", "service", "unclassified"}
)

#: Fallback when the whole chain is inconclusive (SPEC §1.1).
DEFAULT_MIN_PASSES = 2

# --------------------------------------------------------------------------- dem

#: GLO-30 has no tiles over the 41N/44E and 41N/45E cells (withheld in the free
#: instance for this border region), so Stage 0 uses SRTM 1-arcsec — the other
#: source the stage brief names, and the same 30 m ground resolution.
SRTM_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{lat}/{tile}.hgt.gz"
SRTM_NODATA = -32768.0

# ------------------------------------------------------------------ determinism

#: Pinned so that the GPKG driver stamps a fixed `last_change` into
#: gpkg_contents; without it two identical runs differ in bytes.
OGR_CURRENT_DATE = "2000-01-01T00:00:00.000Z"


# ============================================================ Stage 1 — L(G)

#: SPEC §3.3 turn classification.  A manoeuvre within ±30° of straight ahead is
#: not a turn; beyond ±150° it is a u-turn however it is signed.
TURN_STRAIGHT_MAX_DEG = 30.0
TURN_UTURN_MIN_DEG = 150.0

#: Metres of geometry used to measure the heading at an arc's tip.  OSM
#: centrelines carry metre-scale jitter; reading the last vertex pair alone turns
#: that jitter into spurious left and right turns.
BEARING_SAMPLE_M = 25.0

#: SPEC §3.3 turn penalties, seconds.  Marked **[CONFIRM values]** in the spec —
#: these are the spec's own approximations, held here so Stage 2 can calibrate
#: them without touching the graph builder.
TURN_PENALTY_S: dict[str, float] = {
    "straight": 0.0,
    "right": 3.0,
    "left": 8.0,
    "u_turn": 20.0,
}

#: SPEC §3.3 leaves the minimum width for a mid-street U-turn **[CONFIRM]**.
#: §1.1 settles the direction: inventing a manoeuvre that cannot be driven
#: breaks invariant U1, while withholding one only costs deadhead.  So a U-turn
#: away from a dead-end tip needs positive evidence of room to make it.
U_TURN_MIN_WIDTH_M = 12.0
U_TURN_MIN_TOTAL_LANES = 4

#: SPEC §3.3: "Motorway and trunk nodes carry no U-turn edges."
NO_U_TURN_CLASSES: frozenset[str] = frozenset(
    {"motorway", "motorway_link", "trunk", "trunk_link"}
)

#: SPEC §3.3: mainlines are "enterable only via ramp arcs".  Applied to motorway
#: only by default; see the Stage 1 report for the measured cost of extending it
#: to trunk, which in Tbilisi is an at-grade arterial class.
MAINLINE_ENTRY_VIA_RAMPS_ONLY: frozenset[str] = frozenset({"motorway"})

#: Stage 4b, item 2.  The rule above strands a mainline whose only OSM connection
#: is a plain junction rather than a tagged ramp — 4.5 km of required motorway and
#: trunk under variant C.  With this on, the rule is enforced at every junction
#: that *has* a ramp and relaxed at junctions that have none, which is the
#: narrowest change that recovers the reachability.  It cannot weaken invariant
#: U1: turn restrictions are applied separately and are unaffected, and a junction
#: OSM models as a junction is drivable.
#:
#: **Adopted 26 Aug 2026** (`DECISION-schedule.md`).  Under SPEC §1.1 recovering
#: 4.74 km of trapped motorway and trunk for three manoeuvres is required rather
#: than optional, and it had to land before Stage 5 because it changes L(G) and
#: therefore every route.
MAINLINE_ENTRY_FALLBACK_WHERE_NO_RAMP = True

#: Provisional free-flow speeds (km/h) by class, used ONLY for the provisional
#: edge cost in Stage 1.  SPEC §11 places the real time model in Stage 2; this
#: is a placeholder so that L carries a cost at all, and is decomposed from the
#: turn penalty so Stage 2 can replace it without rebuilding the graph.
PROVISIONAL_FREE_FLOW_KMH: dict[str, float] = {
    "motorway": 90.0, "motorway_link": 60.0,
    "trunk": 70.0, "trunk_link": 50.0,
    "primary": 60.0, "primary_link": 40.0,
    "secondary": 50.0, "secondary_link": 40.0,
    "tertiary": 40.0, "tertiary_link": 30.0,
    "unclassified": 30.0, "residential": 30.0,
    "living_street": 20.0, "service": 20.0,
}
PROVISIONAL_DEFAULT_KMH = 30.0

#: SPEC §5.
CAPTURE_SPEED_MAX_KMH = 40.0

TURN_GRAPH_PATH = DERIVED / "turn_graph.pkl"
TURN_STATS_JSON = DERIVED / "01-turn-stats.json"
TURN_RESTRICTIONS_CSV = DERIVED / "01-restrictions.csv"
TURN_UNPARSED_CSV = DERIVED / "01-restrictions-unparsed.csv"
TURN_TRAPS_CSV = DERIVED / "01-traps.csv"
TURN_REPORT_MD = REPORTS / "01-turn-audit.md"
TURN_REPORT_HTML = REPORTS / "01-turn-graph.html"
#: Hand-authored human verification — the one non-regenerable input in the repo,
#: which is why it lives outside `reports/` (see CLAUDE.md on regenerable dirs).
SURVEYS = ROOT / "surveys"
SPOTCHECK_PATH = SURVEYS / "01-junction-spotchecks.json"


# ================================================== Stage 0b — service scope

#: SPEC §2.1 leaves `highway=service` open.  It is the largest number attached to
#: any unresolved question in the spec, and `service` is a bag of unrelated
#: things, so Stage 0b measures the subtag split rather than guessing.
#:
#: These are the `service=*` values that describe something a camera car would
#: treat as a *street*.  Used ONLY by the scenario measurement — variant A (all
#: service) remains as built, and nothing here changes a classification or a
#: default.
SERVICE_STREET_TYPES: frozenset[str] = frozenset({"alley", "untagged"})

SERVICE_SCENARIOS_JSON = DERIVED / "00b-service-scenarios.json"

#: Stage 0b item 2 — a trap whose dangling node sits this close to (or beyond)
#: the clip polygon edge is an artefact of where the extract stops, not a broken
#: junction.
CLIP_EDGE_TOLERANCE_M = 100.0


# ============================================== Stage 2 — time & capture model

# --------------------------------------------------------------- service role

#: SPEC §2.1 leaves `highway=service` open and Stage 0b showed the `service=*`
#: subtag cannot settle it — 92.2% of service arcs carry no subtag at all.
#: Connectivity can.  A service-only component is classified by how many
#: *distinct* non-service nodes it touches:
#:
#:   through  >= 2  — traffic can enter by one street and leave by another, so
#:                    the component is functionally a street
#:   spur      = 1  — a dead-end tree hanging off one junction: driveway, yard,
#:                    parking aisle
#:   orphan    = 0  — not reachable from the street network at all
#:
#: Both sides of the test use *included* arcs only.  An `access=private` or
#: barriered arc is not a door the camera car can drive through, so counting it
#: as one would promote yards to streets (it moves 45 km out of `orphan`).
SERVICE_ROLE_THROUGH_MIN_TOUCHES = 2

#: Stage 2 measures A/D/C, not Stage 0b's A/B/C: the question Stage 4 has to
#: answer is "are spurs worth the hours", and `service_role` is the axis that
#: asks it.  Held separately so `scenarios.compare` — and therefore the Stage 0b
#: artifact — keeps reporting exactly what it reported before.
STAGE2_SCOPE_VARIANTS: tuple[str, ...] = ("A", "D", "C")

# ----------------------------------------------------------- base free flow

#: Item 1.1 — free-flow speed by class, km/h, before any penalty.  Georgia's
#: default urban limit is 60 km/h; each class sits below it by the amount of
#: friction the class implies (junction density, parking, pedestrians).  These
#: are the same numbers Stage 1 used provisionally, so L(G) does not have to be
#: rebuilt — `test_stage2_base_speeds_match_the_stage1_provisional_table` fails
#: if the two ever drift apart.
BASE_FREE_FLOW_KMH: dict[str, float] = dict(PROVISIONAL_FREE_FLOW_KMH)
BASE_FREE_FLOW_DEFAULT_KMH = PROVISIONAL_DEFAULT_KMH

# ------------------------------------------------------------ gradient term

#: Item 1.3 anchor, taken from SPEC §6 verbatim: "a 12% Tbilisi lane is 12 km/h,
#: not 40".  A residential lane free-flows at 30 km/h, so a 12% grade costs it a
#: factor of 12/30.  Every gradient constant below is derived from this pair
#: rather than chosen, which is why the model has one gradient assumption and
#: not four.
GRADIENT_ANCHOR_PCT = 12.0
GRADIENT_ANCHOR_FACTOR = 12.0 / 30.0

#: Speed decays multiplicatively with gradient: `f = exp(-decay * g)`.  The
#: exponential is not cosmetic — it makes every term in the speed model linear in
#: log-speed, so `speedmodel.SpeedModel.fit` can refit the whole thing from
#: Stage 6 traces with ordinary least squares and no optimiser.
GRADIENT_UPHILL_DECAY_PER_PCT = 0.07636  # = -ln(12/30) / 12
#: Descending a grade costs a camera car less than climbing it, but not nothing:
#: engine braking, sightlines and switchbacks.  Half the uphill coefficient is an
#: **assumption**, and it is the gradient term's only unmeasured constant.
GRADIENT_DOWNHILL_DECAY_RATIO = 0.5

#: Beyond this the 30 m DEM is no longer evidence about the road (Stage 0 §10),
#: so the penalty saturates at `exp(-decay * 12) = 0.40`.
GRADIENT_CAP_PCT = 12.0

#: **Measured, not assumed.**  Bridge and tunnel arcs of 25 m or less are flat
#: road decks by construction, so their DEM-derived elevation change is close to
#: pure sampling error: over 1,426 such arcs the median |Δz| is 0.52 m, which at
#: the median arc length of 39 m is a spurious 1.3% grade — and on the shortest
#: arcs, 4%.  The deadband subtracts that fixed elevation error before the
#: gradient term sees it, which is why it scales with 1/length.
GRADIENT_DEM_NOISE_M = 0.5
#: A 5 m arc would otherwise get a 10% deadband and lose a real grade with it.
GRADIENT_DEADBAND_MAX_PCT = 5.0

# ------------------------------------------------------- surface and width

#: Item 1.4.  Speed multipliers.  Only 39.6% of required km carries a `surface`
#: tag, so the untagged default below is the load-bearing choice, not the table.
SURFACE_FACTOR: dict[str, float] = {
    # smooth bituminous or rigid pavement — the reference case
    "asphalt": 1.00, "paved": 1.00, "concrete": 1.00, "concrete:plates": 0.95,
    "concrete:lanes": 0.90, "chipseal": 1.00, "metal": 0.90,
    # rough pavement: passable at speed, but ride quality and camera stability
    # both fall away, and drivers slow for it
    "paving_stones": 0.70, "sett": 0.70, "cobblestone": 0.70,
    "unhewn_cobblestone": 0.65, "pebblestone": 0.65, "grass_paver": 0.65,
    "wood": 0.70, "bricks": 0.70,
    # bound but unsealed
    "compacted": 0.80, "fine_gravel": 0.80,
    # loose or soft
    "gravel": 0.65, "unpaved": 0.65, "ground": 0.65, "dirt": 0.65,
    "earth": 0.65, "sand": 0.55, "mud": 0.50,
}
#: **Assumption.**  An untagged surface is treated as paved.  Among arcs that
#: *are* tagged, 73% of required km is smooth pavement, so this follows the
#: observed distribution rather than §1.1's more-demanding default — and §1.1
#: governs *coverage*, which this does not touch.  The report quantifies what the
#: alternative would cost.
SURFACE_DEFAULT_FACTOR = 1.00

#: Item 1.4, width.  A carriageway too narrow for two cars to pass forces
#: yielding.  `width` is tagged on 1.6% of arcs, so this term is close to inert
#: by construction and the report says so rather than implying coverage.
NARROW_DIR_WIDTH_M = 3.0
NARROW_WIDTH_FACTOR = 0.85

# -------------------------------------------------------------- congestion

#: Item 2.  **Every number in this section is an assumption.**  There is no
#: traffic data for Tbilisi in this pipeline.  The index is a travel-time ratio:
#: 1.00 is free flow, 1.45 means a journey takes 45% longer than free flow.
#: The report carries a sensitivity table over the whole range instead of
#: presenting any one of these as a measurement.
CONGESTION_BANDS: tuple[tuple[str, float, float], ...] = (
    ("am_peak", 9.0, 10.0),
    ("midday", 10.0, 16.0),
    ("pm_peak", 16.0, 18.0),
)

#: Grouped by how exposed a class is to the flows that congest: arterials carry
#: the through traffic and clog worst; residential and service streets are mostly
#: obstructed by parking and manoeuvring, which does not follow the peak.
CONGESTION_INDEX: dict[str, dict[str, float]] = {
    "motorway":       {"am_peak": 1.35, "midday": 1.12, "pm_peak": 1.35},
    "motorway_link":  {"am_peak": 1.35, "midday": 1.12, "pm_peak": 1.35},
    "trunk":          {"am_peak": 1.40, "midday": 1.15, "pm_peak": 1.40},
    "trunk_link":     {"am_peak": 1.40, "midday": 1.15, "pm_peak": 1.40},
    "primary":        {"am_peak": 1.45, "midday": 1.18, "pm_peak": 1.45},
    "primary_link":   {"am_peak": 1.45, "midday": 1.18, "pm_peak": 1.45},
    "secondary":      {"am_peak": 1.45, "midday": 1.18, "pm_peak": 1.45},
    "secondary_link": {"am_peak": 1.45, "midday": 1.18, "pm_peak": 1.45},
    "tertiary":       {"am_peak": 1.25, "midday": 1.10, "pm_peak": 1.25},
    "tertiary_link":  {"am_peak": 1.25, "midday": 1.10, "pm_peak": 1.25},
    "unclassified":   {"am_peak": 1.20, "midday": 1.08, "pm_peak": 1.20},
    "residential":    {"am_peak": 1.10, "midday": 1.05, "pm_peak": 1.10},
    "living_street":  {"am_peak": 1.05, "midday": 1.03, "pm_peak": 1.05},
    "service":        {"am_peak": 1.05, "midday": 1.03, "pm_peak": 1.05},
}
CONGESTION_DEFAULT: dict[str, float] = {"am_peak": 1.20, "midday": 1.08, "pm_peak": 1.20}

#: Item 2's sensitivity range.  λ scales the *delay*, not the index:
#: `index(λ) = 1 + λ·(index − 1)`, so λ = 0 is free flow and λ = 1.5 is half
#: again the assumed delay.  The gate requires at least −25% … +50%.
CONGESTION_SENSITIVITY: tuple[float, ...] = (0.0, 0.75, 1.0, 1.25, 1.5)

# ----------------------------------------------------------- day and depot

#: SPEC §5.
SHIFT_HOURS = 9.0
BREAK_HOURS = 0.75

#: SPEC §7.1 gives the only depot-leg observation in the project: ~22 km
#: straight-line to the eastern districts is "27–30 km of driving, 50–60 min each
#: way in traffic".  The detour factor is the top of 27–30 over 22; the leg speed
#: is 29.7 km in 55 min.  Both are read off that sentence rather than assumed,
#: and Stage 4 replaces the whole band table with routed times.
DEPOT_DETOUR_FACTOR = 30.0 / 22.0
DEPOT_LEG_SPEED_KMH = 32.0

#: Straight-line distance bands from the depot, km.  Upper edge of each band;
#: the last band is open-ended.
DEPOT_DISTANCE_BANDS_KM: tuple[float, ...] = (5.0, 10.0, 15.0, 20.0, 25.0)

# ------------------------------------------------------------------ outputs

#: SPEC §7.3 — sunset drops below the 18:00 shift end around 1 November, and the
#: spec asks Stage 2 to say whether its estimate pushes the finish past October.
#: Both dates are declared here rather than read from the clock: CLAUDE.md rule 5
#: puts no wall-clock behaviour in the pipeline, and a campaign-length check that
#: silently changes answer tomorrow is not a check.
CAMPAIGN_START_DATE = "2026-08-25"   # SPEC v0.3, 25 Aug 2026
DAYLIGHT_BINDING_DATE = "2026-11-01"  # SPEC §7.3
WORKING_DAYS_PER_WEEK = 7             # SPEC §5

TIME_MODEL_JSON = DERIVED / "02-time-model.json"
TIME_REPORT_MD = REPORTS / "02-time-model.md"


# ================================================== Stage 3 — bounds & tour

#: Item 4 — `days = total_hours / productive_hours_per_day`.  Stage 3 has no
#: depot legs (they are an explicit non-goal), so the productive day is the
#: Stage 2 shift net of the break and nothing else.  Stated here rather than
#: inlined so the report can print the constant it divided by.
STAGE3_PRODUCTIVE_HOURS = SHIFT_HOURS - BREAK_HOURS

#: The cheapest schedule lever available: an 08:00 start instead of 09:00.
#: SPEC §7.2 already argues the outbound leg wants to be earlier, and SPEC §7.3
#: puts sunset well clear of 18:00 until November, so the extra hour is at the
#: front of the day.  Quantified in the Stage 3 report rather than guessed.
STAGE3_EXTENDED_SHIFT_HOURS = 10.0
STAGE3_EXTENDED_PRODUCTIVE_HOURS = STAGE3_EXTENDED_SHIFT_HOURS - BREAK_HOURS

#: Seconds before the LP relaxation is abandoned for the combinatorial fallback.
LP_TIME_LIMIT_S = 2400.0

#: The tour itself, plus the two arrays needed to rebuild the exact `L*` it was
#: audited against.  Persisted so the Stage 3 gate can re-run the invariant suite
#: from the artifact instead of taking the stage's word for it — a gate that reads
#: a stage's own verdict is not a gate.
TOUR_NPZ = DERIVED / "03-tour-{variant}.npz"

BOUNDS_JSON = DERIVED / "03-bounds.json"
BOUNDS_REPORT_MD = REPORTS / "03-bounds.md"
TOUR_GPX = REPORTS / "03-tour-{variant}.gpx"
#: Only variant A gets a GPX: the artifact is a sanity check on the solver, and
#: three copies of the same check is three times the disk for no more evidence.
TOUR_GPX_VARIANT = "A"


# ================================================== Stage 4 — zoning

#: **The scope decision.**  `DECISION-schedule.md`, 25 Aug 2026: one car, variant
#: C, no `highway=service`.  Stage 4 is the first stage that consumes an include
#: set — until now `service_role` has been a column, not a filter.
#:
#: SPEC §2.1.1 defers `through` service to phase 2, and says re-including it must
#: be a configuration change rather than a rebuild.  That is what this constant is
#: for: set it to "D" and re-run Stages 4–5.  Nothing downstream hard-codes "C".
SCOPE_VARIANT = "C"

#: Sunset is computed for the middle of the municipality rather than the depot.
#: The spread across Tbilisi's 0.5° of longitude is under two minutes, which is
#: below anything a shift plan can act on, but the centre is the honest place to
#: stand: it is where the late-afternoon capture happens.
DAYLIGHT_LAT = 41.7151
DAYLIGHT_LON = 44.8271
#: Asia/Tbilisi is UTC+4 all year — Georgia abolished daylight saving in 2005, so
#: there is no clock change inside any plausible campaign window.
UTC_OFFSET_HOURS = 4.0

#: The two shift windows the decision left open.  Stage 3 costed variant C at
#: 32.9 days on the first and 29.4 on the second; the earlier start has not been
#: agreed, so Stage 4 reports both rather than assuming.
SHIFT_WINDOWS: dict[str, tuple[float, float]] = {
    "9h": (9.0, 18.0),
    "10h": (8.0, 18.0),
}
#: **9 h confirmed 26 Aug 2026** (`DECISION-schedule.md`): the originally specified
#: window.  C needs 38 days and finishes 1 Oct with +29 days of margin, against
#: 33 days at 10 h — near-identical total driving, five calendar days traded for an
#: hour's later start.
DEFAULT_SHIFT_WINDOW = "9h"

#: SPEC §4 Stage B asks for zones of roughly one shift of capture time.  What a
#: day actually costs is capture *plus* the deadhead and turn time of driving it,
#: and Stage 3 measured that ratio on a real tour rather than assuming it — so it
#: is read from `03-bounds.json` at run time, not written here.  This is only the
#: fallback for when that artifact is missing.
ZONE_OVERHEAD_FALLBACK = 1.95

#: **Measured by Stage 5, 26 Aug 2026.**  Stage 3's global tour amortises deadhead
#: across the whole city; a single day's route must also get out to its zone and
#: back, so its deadhead per capture hour is higher.  Solving all 38 days measured
#: the intra-zone ratio at 1.59–2.55 (p90 2.31) against the 1.95 Stage 4 inherited
#: — and 24 of 38 days overran their window as a result.  This is the observed
#: maximum, so the sizing is built on the worst zone rather than the average one.
#: Set to None to go back to reading Stage 3's figure.
#:
#: **Stage 4c, 27 Aug 2026 — set to None.**  2.55 was the worst zone's
#: `route_h / capture_h`, and `route_h` *includes* both depot legs.
#: `zoning.zone_durations` adds the legs as their own term, so every zone was
#: charged for them twice and its predicted day came out about 1.2 h long — which
#: is why 48 zones were sized for 8.85 h days that Stage 5 then drove in 7.1 h.
#: The ratio is now read from `05-routes.json`, where Stage 5 measures it with the
#: legs removed, and this constant is only an override.
#: **Pinned by Stage 4c, 27 Aug 2026 — 2.2598119655864606.**  The p75 of the
#: intra-zone distribution measured over the 49-day run, then swept: p90 (2.3942)
#: gave 47 zones and 49 days, p75 gave 43 zones and 47 days, p50 (2.1024) collapsed
#: to 39 zones, 16 splits and 55 days.  p75 won and is fixed here.
#:
#: It is pinned rather than left to `ZONE_OVERHEAD_QUANTILE` because the quantile
#: is read from `05-routes.json`, which Stage 5 rewrites — so leaving it live makes
#: Stage 4 size on whatever the last run produced, and the adopted plan stops being
#: reproducible.  This run's own p75 is 2.2030, not 2.2598: the loop has not reached
#: a fixed point, and CLAUDE.md rule 5 wants the committed plan regenerable.  Set to
#: None to sweep again.
#:
#: Pinned to full precision deliberately: the zone-count search is knife-edge in
#: this constant.  Rounding it to 2.2598 — a difference of 1.2e-05 — moves the
#: 9 h partition from 43 zones to 44.  Anything that stores this value must keep
#: every digit or it will not reproduce the committed plan.
ZONE_OVERHEAD_MEASURED: float | None = 2.2598119655864606

#: Where the pin above came from.  A pinned number with no provenance is a guess
#: wearing a measurement's clothes, and the Stage 4 gate rejects it: leave this
#: empty and the artifact records "config pin", which fails
#: `test_the_overhead_came_from_a_measurement_not_a_guess`.  Say where it came
#: from or do not pin it.
ZONE_OVERHEAD_PIN_SOURCE = (
    "Stage 5 measurement, intra-zone p75 of 49 solved days "
    "(pinned by Stage 4c so the adopted plan regenerates)"
)

#: Which quantile of Stage 5's measured intra-zone distribution to size on.
#: An undersized zone wastes a day; an oversized one overruns and gets split, and
#: the split is the more expensive failure — so the sizing sits in the upper tail
#: rather than at the middle.  `prompts/04c-rezone-on-measured-overhead.md` asks
#: for p75-p90.
ZONE_OVERHEAD_QUANTILE = "p75"

#: Whether zone sizing may credit capture-on-the-commute (SPEC §7.1 mitigation 1).
#:
#: Stage 4 credited it and sized days on the smaller requirement that leaves.
#: **Stage 5 does not realise it**: each day is solved as a closed circuit over its
#: own zone, and although its legs do pass through other zones they do so at
#: deadhead speed, capturing nothing.  Stage 4's day table therefore carried 126.5
#: capture hours where Stage 5 actually drives 139.3.  Until a solver delivers the
#: mitigation, sizing must not claim it.
CAPTURE_ON_COMMUTE_IN_SIZING = False

#: Room reserved in each day for a leg routed through uncovered required arcs, as
#: a fraction of that zone's plain leg.  Without it the zones fill the day exactly
#: and every coverage-routed leg is refused for overrunning, which makes SPEC
#: §7.1's first mitigation unreachable in practice.  Proportional to the leg, so
#: the far zones — first in the sequence, when least is covered — reserve most.
#:
#: **Suspended by Stage 5, 26 Aug 2026 — set to 0.0.**  Stage 4b raised this to
#: 0.35 because reserving room for a productive leg saved driving hours.  That
#: finding assumed the productive leg happens; Stage 5's routes show it does not
#: (see `CAPTURE_ON_COMMUTE_IN_SIZING`).  Reserving room for a manoeuvre nobody
#: performs only makes zones smaller and the campaign longer, so the reserve is
#: withdrawn until a solver earns it back.  The Stage 4b measurement stands; what
#: changed is whether its premise holds.
#:
#: Historic note — raised from 0.10 to 0.35 by Stage 4b, item 3.  Stage 4 set it low because the
#: calendar was the binding constraint; Stage 4 then measured 42 days of slack, so
#: it is not.  SPEC §4 names **total driving hours** as the KPI, and on that
#: measure the reserved profile wins on both variants: variant C drives 8.0 hours
#: less for one more day, variant D 5.9 hours less for one more day.  Both
#: profiles are reported every run — see `reports/04b-recheck.md` §3.
COMMUTE_ALLOWANCE = 0.0

#: A depot leg routed through uncovered required arcs may wander; this caps how
#: far.  Expressed against the pure-deadhead leg it replaces, so it scales with
#: how far out the zone is rather than being a flat number that is generous in
#: the west and binding in the east.
LEG_COVERAGE_DETOUR_CAP = 2.0

#: Partitioning is retried with more zones until every day fits its window.  The
#: cap exists so an infeasible input fails loudly instead of looping.
ZONE_COUNT_MAX_ITERATIONS = 40

#: Whether the zone search may fall back to reserving no commute room in order to
#: save a day.  Stage 4 said yes, because `DECISION-schedule.md` had turned on the
#: calendar.  Stage 4b says no: the slack is real and SPEC §4's KPI is hours, so
#: the search commits to the allowance and accepts the day it costs.  Set True to
#: get the shortest calendar instead.
ZONE_PREFER_FEWEST_DAYS = False

#: METIS is seeded so two runs give the same partition (CLAUDE.md rule 5).
METIS_SEED = 20260825
#: Extra seeds tried on the best weighting, so the day spread does not hang on
#: one arbitrary draw.  Fixed values, so the search is still deterministic.
METIS_SEEDS: tuple[int, ...] = (20260825, 20260826, 20260827, 20260828)

#: Gate threshold: the standard deviation of day durations, in hours.  Stated
#: here so the gate asserts a number the report also prints.
DAY_BALANCE_STDEV_MAX_H = 1.0

ZONES_GPKG = DERIVED / "04-zones.gpkg"
ZONES_LAYER = "arcs"
ZONES_JSON = DERIVED / "04-zones.json"
ZONING_REPORT_MD = REPORTS / "04-zoning.md"
ZONING_REPORT_HTML = REPORTS / "04-zones.html"


def stage4_paths(variant: str, allowance_tag: str = "") -> dict:
    """Where a Stage 4 run writes.

    The *chosen* scope writes to the canonical `04-*` names — those are the stage's
    contract and what the gate reads.  Anything else is a re-check and writes
    beside it under `04b-*`, so that measuring an alternative can never overwrite
    the plan the project is actually working to.  Change `SCOPE_VARIANT` and the
    alternative becomes canonical without any path juggling.
    """
    suffix = f"-{variant}{allowance_tag}"
    if variant == SCOPE_VARIANT and not allowance_tag:
        return {
            "gpkg": ZONES_GPKG,
            "json": ZONES_JSON,
            "report": ZONING_REPORT_MD,
            "html": ZONING_REPORT_HTML,
        }
    return {
        "gpkg": DERIVED / f"04b-zones{suffix}.gpkg",
        "json": DERIVED / f"04b-zones{suffix}.json",
        "report": REPORTS / f"04b-zoning{suffix}.md",
        "html": REPORTS / f"04b-zones{suffix}.html",
    }


# --------------------------------------------------------------- Stage 4b

#: The "reserve the room" commute-allowance profile, measured against the default
#: in `reports/04b-recheck.md`.  Item 3 of the Stage 4b brief.
COMMUTE_ALLOWANCE_RESERVED = 0.35

#: Stage 4c preserves the committed plan under these names before re-zoning, so the
#: before/after comparison is regenerable from disk rather than from a backup that
#: lives outside the repository.
BASELINE_ZONES_JSON = DERIVED / "04c-baseline-zones.json"
BASELINE_ROUTES_JSON = DERIVED / "04c-baseline-routes.json"
SWEEP_JSON = DERIVED / "04c-sweep.json"
REZONE_REPORT_MD = REPORTS / "04c-rezone.md"

RECHECK_JSON = DERIVED / "04b-recheck.json"
RECHECK_REPORT_MD = REPORTS / "04b-recheck.md"


# ================================================== Stage 5 — route solve

#: A day that will not fit its window is split in two and re-solved.  Each split
#: costs exactly one day, against a day per zone for shrinking every zone, so the
#: repair is local.  The cap stops a pathological zone looping.
ROUTE_SPLIT_MAX_ROUNDS = 6

#: Seconds allowed per zone for the exact solve before the heuristic result stands
#: as the answer.  A zone that hits it is a *known* approximation: its optimality
#: gap is reported against the bound rather than quietly assumed to be zero.
ROUTE_MIP_TIME_LIMIT_S = 45.0

ROUTES_GPKG = DERIVED / "05-routes.gpkg"
ROUTES_LAYER = "manoeuvres"
ROUTES_JSON = DERIVED / "05-routes.json"
ROUTES_REPORT_MD = REPORTS / "05-routes.md"
ROUTES_DIR = REPORTS / "05-routes"
