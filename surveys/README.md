# surveys/

Hand-authored human verification. **This is the one directory in the repo whose
contents are not regenerable**, which is exactly why it is not in `reports/` or
`data/derived/` — CLAUDE.md says those are rebuilt from source and never edited
by hand.

| File | What it is |
| --- | --- |
| `01-junction-spotchecks.json` | The Stage 1 gate's 20-junction check against satellite imagery |
| `00b-untagged-service-sample.json` | Stage 0b's 12-segment imagery read of untagged `highway=service` |

Each Stage 1 spot-check row carries:

- `osm_node`, `lon`, `lat` — the junction, so the check is repeatable
- `graph_says` — generated from L(G) by `efficientroute.spotcheck`
- `imagery` — what overhead imagery actually shows, written by a human
- `verdict` — `confirmed` | `mismatch` | `missing_in_osm` | `inconclusive`

`confirmed` means the manoeuvres L permits and bans are consistent with the
physical layout. It does **not** mean OSM's restriction set is proven complete:
overhead imagery shows medians, islands and kerb lines but not signage.
