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

uv run pytest -q "$@"
