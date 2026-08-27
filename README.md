# EfficientRoute

Camera-car coverage planner for the Tbilisi street network.
`SPEC.md` is the contract; `prompts/` holds one brief per stage.

## Stage 0 — extract & measure

```bash
make stage0     # fetch -> extract -> arc table -> report -> map
make stage1     # turn restrictions -> L(G) -> audit -> report -> map
make stage0b    # service subtag breakdown + A/B/C scope scenarios
make stage2     # time & capture model -> campaign estimate -> report
make stage3     # node-split -> min-cost flow -> Euler tour -> LP bound -> report
make stage4     # partition -> routed depot legs -> sequence -> calendar -> report
make stage4b    # re-test variant D, dispose of the trapped mainlines
make stage4c    # compare the re-zoned plan against the committed one
make stage5     # solve one route per driving day -> GPX + turn sheets
make test       # unit tests
make gate       # Stage 0 gate assertions
make gate1      # Stage 1 gate assertions
make gate2      # Stage 2 gate assertions
make gate3      # Stage 3 gate assertions
make gate4      # Stage 4 gate assertions
make gate4b     # Stage 4b gate assertions
make gate4c     # Stage 4c gate assertions
make gate5      # Stage 5 gate assertions
```

Outputs:

| Path | What it is |
| --- | --- |
| `data/derived/network.gpkg` | canonical directed-arc network, layer `arcs` |
| `data/derived/00-network-stats.json` | every number the report and the gate use |
| `data/derived/00-dropped-ways.csv` | ways dropped before arc construction, with reasons |
| `data/derived/00-extract.pkl.gz` | cached PBF read, so the arc table rebuilds in seconds |
| `reports/00-network-stats.md` | the human-readable stage report |
| `reports/00-network.html` | interactive map |
| `data/derived/turn_graph.pkl` | L(G) — the turn-expanded graph |
| `data/derived/01-turn-stats.json` | every number in the Stage 1 report |
| `data/derived/01-restrictions.csv` | every restriction, applied or not, with its outcome |
| `data/derived/01-restrictions-unparsed.csv` | relations skipped at parse time, with reasons |
| `data/derived/01-traps.csv` | arcs with no legal entry or no legal exit |
| `reports/01-turn-audit.md` | the Stage 1 report |
| `reports/01-turn-graph.html` | traps, restricted junctions, permitted U-turns |
| `data/derived/00b-service-scenarios.json` | service scope variants A/B/C |
| `surveys/01-junction-spotchecks.json` | hand-authored imagery verification (not regenerable) |
| `surveys/00b-untagged-service-sample.json` | hand-authored imagery read of untagged service ways |
| `data/derived/02-time-model.json` | the fitted speed model, sensitivity sweep and campaign estimate |
| `reports/02-time-model.md` | the Stage 2 report |
| `data/derived/03-bounds.json` | the bracket, the tour metrics and the A/D/C table |
| `data/derived/03-tour-{A,D,C}.npz` | each tour, plus the arrays needed to re-audit it |
| `reports/03-bounds.md` | the Stage 3 report |
| `reports/03-tour-A.gpx` | the constructive tour — a sanity artifact, **not** a day plan |
| `data/derived/04-zones.gpkg` | zone, sequence position and date per arc, layer `arcs` |
| `data/derived/04-zones.json` | every number in the Stage 4 report |
| `reports/04-zoning.md` | the Stage 4 report, including the campaign calendar |
| `reports/04-zones.html` | zone map, coloured by sequence position |
| `data/derived/04b-recheck.json` | every number in the Stage 4b report |
| `data/derived/04b-zones-*.{json,gpkg}` | alternative scopes and allowance profiles |
| `reports/04b-recheck.md` | the Stage 4b report — variant D, the trapped mainlines |
| `data/derived/04c-baseline-{zones,routes}.json` | the plan Stage 4c replaced, kept so the comparison regenerates |
| `data/derived/04c-sweep.json` | the overhead-quantile sweep and which candidate won |
| `reports/04c-rezone.md` | the Stage 4c report — the sizing correction and the sweep |
| `data/derived/05-routes.gpkg` | every manoeuvre, in order, with mode and lane instruction |
| `data/derived/05-routes.json` | every number in the Stage 5 report |
| `reports/05-routes.md` | the Stage 5 report — per-day table, bracket, turn account |
| `reports/05-routes/day-NN.gpx` | **the file that goes in the car** — one track per day |
| `reports/05-routes/day-NN.md` | turn-by-turn sheet for that day |

Re-running is cheap: the PBF read is cached, so only the arc table, report and
map are rebuilt. `make stage0` after `rm data/derived/00-extract.pkl.gz`, or
`uv run efficientroute stage0 --force-extract`, re-reads the source.

Stage 2 writes three columns — `service_role`, `capture_speed_kmh`,
`capture_time_s` — back into the `arcs` layer of `network.gpkg`. Re-running
`make stage0` rebuilds that layer and so removes them; it says so, and drops the
now-stale `02-time-model.json` rather than leaving it describing columns that are
no longer there. `make stage2` restores both. The speed-model coefficients live in
that JSON and are read back by the rebuild, which is how a Stage 6 refit reaches
every downstream stage without a code change.

Stage 3 takes about 12 minutes: three scope variants, each a min-cost flow over a
621k-edge graph plus an LP relaxation of similar size. It writes each tour to
`data/derived/03-tour-*.npz` so that `make gate3` can re-run the full invariant
suite against the artifact rather than against anything the solver kept in memory.

Stage 4 sizes a day as `capture x overhead + legs + break`, so `overhead` is the
driving *inside* a zone per hour of capture — the depot legs are a separate term.
Stage 5 measures that ratio over the days it solves and writes the distribution to
`05-routes.json`; `config.ZONE_OVERHEAD_MEASURED` pins the value the committed plan
was sized on, because Stage 4 reading a figure Stage 5 rewrites would mean each run
sizes on whatever the last one produced. Pin to full precision: the zone count is
knife-edge in it. See `reports/04c-rezone.md`.

Stage 4 is the first stage that consumes an **include set**. `config.SCOPE_VARIANT`
selects it — `"C"` per `DECISION-schedule.md`. SPEC §2.1.1 defers the
through-connected service network to a phase 2 that must be a configuration change
rather than a rebuild, so `service_role` stays on every arc and nothing downstream
hard-codes a variant: set `SCOPE_VARIANT = "D"` and re-run Stages 4–5.

Both shift windows are reported every run (`config.SHIFT_WINDOWS`); the default
only decides which one the GeoPackage and the map are written for.

Stage 4 writes to the canonical `04-*` names only for `SCOPE_VARIANT`. Any other
variant, or any non-default commute-allowance profile, writes beside it as
`04b-*`, so measuring an alternative can never overwrite the plan the project is
working to. `make stage4b` uses that to re-test variant D against C without
touching the committed artifacts.

## A note on `make`

This checkout lives under `~/Desktop`, which macOS syncs through iCloud Drive.
iCloud sets the `UF_HIDDEN` flag on files inside `.venv` and duplicates them
(`_editable_impl_efficientroute 2.pth`), and CPython's `site.py` silently skips
hidden `.pth` files — so the editable install stops resolving, intermittently
and with no error message. The Makefile sidesteps it entirely by running the
package from source (`PYTHONPATH=src uv run python -m efficientroute`), and the
pytest config sets `pythonpath = ["src"]` for the same reason.

`uv run efficientroute ...` relies on the console script and so will fail
whenever iCloud has just touched the venv. Moving the checkout off iCloud-synced
storage, or pointing `UV_PROJECT_ENVIRONMENT` at a path outside it, fixes it at
the source.
