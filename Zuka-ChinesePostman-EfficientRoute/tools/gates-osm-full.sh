#!/bin/sh
# Every gate, under Run 1's environment. Same variables as tools/run-osm-full.sh —
# the gates read the same artifacts the stages wrote, so they have to.
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

export PYTHONPATH=src
export EFFICIENTROUTE_OUTPUT_ROOT="$ROOT/RUN-OSM-FULL"
export EFFICIENTROUTE_BOUNDARY="$EFFICIENTROUTE_OUTPUT_ROOT/data/derived/00-custom-boundary.geojson"
export EFFICIENTROUTE_REQUIRED_BOUNDARY="$EFFICIENTROUTE_BOUNDARY"
export EFFICIENTROUTE_SCOPE_VARIANT=A
export EFFICIENTROUTE_CAMPAIGN_START=2026-08-29
# Zone A was requested and is not in the data. Stamped under the title of every
# report this run writes, so a Zone B number is never read as an A+B number.
export EFFICIENTROUTE_CAMPAIGN_CAVEAT='**Zone A was requested and is not in the data.** `data/custom/B Zone_Streets/AB_zones.shp` holds one polygon, `Name = "Zone B"`, despite the layer being called `AB_zones`; its `FolderPath` names `Tbilisi Possible parking zones.kmz` as the source, so Zone A presumably exists there and was never exported. **This run covers Zone B only.** Nothing in it is an A+B result, and no Zone A boundary has been inferred or approximated.'

uv run pytest -q "$@"
