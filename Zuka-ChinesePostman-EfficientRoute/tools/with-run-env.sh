#!/bin/sh
# Run a command under one of the two campaign environments defined by
# tools/run-osm-full.sh and tools/run-customer-net.sh, so that a diagnostic reads
# exactly the artifacts the stages wrote.
#
#   sh tools/with-run-env.sh customer-net uv run python some/diagnostic.py
#   sh tools/with-run-env.sh osm-full     uv run pytest -q -m gate4
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

WHICH=$1
shift

export PYTHONPATH=src
export EFFICIENTROUTE_CAMPAIGN_START=2026-08-29
export EFFICIENTROUTE_SCOPE_VARIANT=A
# Zone A was requested and is not in the data. Stamped under the title of every
# report this run writes, so a Zone B number is never read as an A+B number.
export EFFICIENTROUTE_CAMPAIGN_CAVEAT='**Zone A was requested and is not in the data.** `data/custom/B Zone_Streets/AB_zones.shp` holds one polygon, `Name = "Zone B"`, despite the layer being called `AB_zones`; its `FolderPath` names `Tbilisi Possible parking zones.kmz` as the source, so Zone A presumably exists there and was never exported. **This run covers Zone B only.** Nothing in it is an A+B result, and no Zone A boundary has been inferred or approximated.'

case "$WHICH" in
    osm-full)
        export EFFICIENTROUTE_OUTPUT_ROOT="$ROOT/RUN-OSM-FULL"
        export EFFICIENTROUTE_BOUNDARY="$EFFICIENTROUTE_OUTPUT_ROOT/data/derived/00-custom-boundary.geojson"
        export EFFICIENTROUTE_REQUIRED_BOUNDARY="$EFFICIENTROUTE_BOUNDARY"
        ;;
    customer-net)
        export EFFICIENTROUTE_OUTPUT_ROOT="$ROOT/RUN-CUSTOMER-NET"
        export EFFICIENTROUTE_BOUNDARY="$EFFICIENTROUTE_OUTPUT_ROOT/data/derived/00-custom-boundary.geojson"
        export EFFICIENTROUTE_REQUIRED_NETWORK="$EFFICIENTROUTE_OUTPUT_ROOT/data/derived/00-custnet-network.geojson"
        ;;
    zone-b)
        # The committed Zone B campaign predates the caveat and has to keep
        # regenerating byte for byte, so it does not get one.
        unset EFFICIENTROUTE_CAMPAIGN_CAVEAT
        export EFFICIENTROUTE_OUTPUT_ROOT="$ROOT/CUSTOM-OUTPUT"
        export EFFICIENTROUTE_BOUNDARY="$EFFICIENTROUTE_OUTPUT_ROOT/data/derived/00-custom-boundary.geojson"
        export EFFICIENTROUTE_REQUIRED_BOUNDARY="$EFFICIENTROUTE_BOUNDARY"
        export EFFICIENTROUTE_SCOPE_VARIANT=C
        export EFFICIENTROUTE_CAMPAIGN_START=2026-08-28
        ;;
    tbilisi)
        unset EFFICIENTROUTE_SCOPE_VARIANT
        unset EFFICIENTROUTE_CAMPAIGN_START
        unset EFFICIENTROUTE_CAMPAIGN_CAVEAT
        ;;
    *)
        echo "usage: $0 {osm-full|customer-net|zone-b|tbilisi} command..." >&2
        exit 2
        ;;
esac

exec "$@"
