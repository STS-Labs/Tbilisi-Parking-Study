# Stage 0b — service subtag breakdown + two small fixes

A patch to Stages 0 and 1, not a new stage. Read `SPEC.md` §2.1, §7A and
`CLAUDE.md`. **Measurement only — change no classification and no default.**

## Item 1 — retain and report the OSM `service=*` subtag  *(the decision blocker)*

SPEC §2.1 leaves `highway=service` open. It is 2,196.0 km, 38.4% of required
traversal, and 52% of the graph — but `service` is a bag of unrelated things.
`service=alley` is a real street; `service=driveway` and `service=parking_aisle`
are not. The decision cannot be made on the parent tag.

### Changes

1. Add a `service_type` column to the `arcs` layer of `network.gpkg`, carrying the
   raw OSM `service=*` value (null for non-service arcs, `"untagged"` for
   `highway=service` with no `service` tag).
2. Extend §8 of `reports/00-network-stats.md` with a breakdown table:
   `service_type | arcs | included arcs | centerline km | required traversal km |
   % of the 2,196.0 km`, sorted by required km descending.
3. Add a **scenario table** immediately after it, giving total required traversal
   km, total included arcs, and L(G) node count under each variant:

   | Variant | What it includes |
   |---|---|
   | A — as built | all `highway=service` |
   | B — streets only | service where `service_type` ∈ {alley, `untagged`} |
   | C — none | no `highway=service` |

   Report each as absolute and as a delta from variant A. Do **not** implement a
   switch or change the default — variant A remains as built. This is a
   measurement so the decision is made against numbers.

## Item 2 — classify clip-boundary traps  *(cosmetic but load-bearing)*

`reports/01-turn-audit.md` §4 lists 47 no-exit and 58 no-entry arcs. The largest
entries — Tbilisi Bypass Road, Tbilisi–Senaki–Leselidze, Ponichala–Marneuli,
Tbilisi–Bakurtsikhe–Lagodekhi — appear as **both** `F: no_legal_entry` **and**
`B: no_legal_exit` for the same `way_id`. That is the signature of a road
continuing past the 2 km clip buffer, not a broken junction.

Add a `trap_cause` field with values `clip_boundary` / `genuine`. An arc is
`clip_boundary` when its dangling endpoint node lies within a tolerance of the clip
polygon edge, or when its reverse arc carries the mirrored trap. Split §4 of the
audit into two tables. The genuine list is what needs fixing; today it is buried.

## Gate

- Variant A totals reconcile **exactly** to the current numbers: 2,196.0 km
  service required traversal, 5,725.3 km overall. A mismatch means the subtag join
  is wrong, not that the old number was.
- `service_type` is non-null for every `highway=service` arc and null for all others.
- Determinism holds; the `arcs` layer hash changes only by the added columns.
- Every trap is classified; `clip_boundary` + `genuine` sums to 47 and 58.
- All 374 existing tests still pass.

## Non-goals

Do not exclude service roads. Do not change `CLASS_IS_NARROW_PAIR`. Do not touch
the min_passes thresholds. Do not start Stage 2.
