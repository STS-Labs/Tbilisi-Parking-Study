# Stage 4 — Zoning into shift-sized days

Read `SPEC.md` §4 (Stage B), §7.1, §7.3 and `CLAUDE.md`. Stage 3's gate must have
passed, and **the scope variant must be chosen** before this stage runs.

## Inputs

- **`VARIANT = C`** — decided 25 Aug 2026 (SPEC §2.1, `DECISION-schedule.md`).
  `highway=service` is excluded entirely. This is the first stage that consumes an
  include set; until now `service_role` has been a column, not a filter. Keep the
  column and keep the variant configurable — phase 2 (SPEC §2.1.1) re-includes
  `through` service later, and that must be a config change, not a rebuild.

- **Shift window:** C fits at either 9 h or 10 h (38.5 vs 33.8 days). Report both;
  do not assume the earlier start has been agreed.

- **Re-report the unreachable set.** Stage 3 logged 129.9 km that no closed tour can
  reach — 117.4 km of Stage 0 fragments plus 12.5 km of legal traps. Stage 0's orphan
  fragments were overwhelmingly `service`, so **most of that may simply cease to be
  required under variant C**. Recompute it for C rather than carrying the A-scope
  figure forward, and state what genuinely remains unreachable.
- Stage 2 capture times, Stage 3 bounds.

## Tasks

### 1. Partition
Split required elements into **connected, geographically compact zones**, each
sized to one shift *net of depot legs*. Weight by **capture time**, not length.

Use balanced graph partitioning (METIS/KaHIP) over the network, **not** geometric
clustering: the Mtkvari and the ridgelines mean two points 500 m apart can be 6 km
apart by road. Connectivity is checked in `L(G)`, so a zone is never split by a
one-way pair or a turn restriction.

### 2. Depot legs — routed, not estimated
Depot at 41.730736 N, 44.734583 E. For each zone compute the **routed** shortest
time from depot to zone entry and zone exit to depot over `L(G)`, replacing
Stage 2's straight-line bands.

### 3. Capture on the commute (SPEC §7.1 mitigation 1)
A depot leg is only deadhead if the corridor it runs along is already covered.
Where a leg can be routed through **uncovered required arcs** at a detour cost
below the coverage value gained, it must be. Report how many hours this reclaims —
on eastern zones it should be most of the leg.

### 4. Sequence: far zones first (SPEC §7.1 mitigation 2 — a hard rule)
Order zones by **descending depot-leg cost**. Early in the campaign the connecting
corridors are uncovered, so long legs absorb productive capture; late in the
campaign the same legs are pure deadhead. This is counter-intuitive and easy to
implement backwards — assert the ordering in a test.

### 5. Daylight taper (SPEC §7.3)
Productive hours are not constant across the campaign. Compute per-day sunset for
Tbilisi and cap each day's window at `min(shift_end, sunset)`. Report the day on
which the campaign first becomes daylight-limited, and total hours lost to taper.

## Outputs

- `data/derived/04-zones.gpkg` — zone assignment per arc
- `reports/04-zoning.md` — zone table (capture h, leg h, total h, sequence
  position), balance statistics, reclaimed-commute hours, taper analysis, and a
  **calendar**: start date → finish date
- `reports/04-zones.html` — zone map, coloured by sequence position

## Gate — tests must assert

- Every required element of the chosen variant is in **exactly one** zone.
- Every zone is connected in `L(G)`.
- **I4** no day exceeds its window: capture + turns + legs + break ≤ available hours.
- Zone sequence is strictly descending in depot-leg cost (rule 4).
- Depot leg times are routed over `L(G)`, not straight-line — assert against a
  known pair.
- Balance: stdev of day durations below a stated threshold.
- Determinism; all prior tests still pass.

## Non-goals

No intra-zone route solving — that is Stage 5. Zones define *what* each day covers,
not the order within a day.
