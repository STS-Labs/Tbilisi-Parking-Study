#!/bin/sh
# Run 1 of CUSTOM-RUN-2-PROMPT.md — "everything OSM has in the zone".
#
# Identical to the Zone B campaign under CUSTOM-OUTPUT/ in every respect except
# one: EFFICIENTROUTE_SCOPE_VARIANT=A puts `highway=service` back in scope, so the
# required set is everything OSM records inside Zone B rather than the streets that
# survive variant C.  Nothing else moves — same 9 h shift, same depot, same p75
# overhead, same far-zones-first sequence, same native HMM matcher.
#
# Run from the repository root:  sh tools/run-osm-full.sh [stage ...]
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

export PYTHONPATH=src
export EFFICIENTROUTE_OUTPUT_ROOT="$ROOT/RUN-OSM-FULL"
export EFFICIENTROUTE_BOUNDARY="$EFFICIENTROUTE_OUTPUT_ROOT/data/derived/00-custom-boundary.geojson"
export EFFICIENTROUTE_REQUIRED_BOUNDARY="$EFFICIENTROUTE_BOUNDARY"
export EFFICIENTROUTE_SCOPE_VARIANT=A
# The day after the run, resolved once and written down rather than computed —
# CLAUDE.md rule 5 keeps wall-clock out of the pipeline.
export EFFICIENTROUTE_CAMPAIGN_START=2026-08-29
# Zone A was requested and is not in the data. Stamped under the title of every
# report this run writes, so a Zone B number is never read as an A+B number.
export EFFICIENTROUTE_CAMPAIGN_CAVEAT='**Zone A was requested and is not in the data.** `data/custom/B Zone_Streets/AB_zones.shp` holds one polygon, `Name = "Zone B"`, despite the layer being called `AB_zones`; its `FolderPath` names `Tbilisi Possible parking zones.kmz` as the source, so Zone A presumably exists there and was never exported. **This run covers Zone B only.** Nothing in it is an A+B result, and no Zone A boundary has been inferred or approximated.'

STAGES=${*:-"stage0 stage1 stage0b stage2 stage3 stage4 stage5 stage7"}

for stage in $STAGES; do
    echo "=================================================== $stage"
    uv run python -m efficientroute "$stage"
done
