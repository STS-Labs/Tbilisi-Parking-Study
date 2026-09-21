#!/bin/sh
# Run 2 of CUSTOM-RUN-2-PROMPT.md — the customer's own network as the required set.
#
#   The customer's layer says WHAT to cover. OSM says HOW to drive it.
#
# EFFICIENTROUTE_REQUIRED_NETWORK replaces the zone polygon as the definition of
# "required": an arc is required where the customer's noded linework covers it, and
# every other arc in the clip is routable but never needs filming.
#
# The scope variant is A, and deliberately so. The variant filter drops arcs from
# the network entirely, so running C here would let a scope decision made for a
# different campaign delete a street the customer explicitly asked for. Under A the
# filter drops nothing, the required set is exactly the customer's 347 km, and the
# service roads it adds are routable-only — extra legal deadhead, never work.
#
# Run from the repository root:  sh tools/run-customer-net.sh [stage ...]
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

export PYTHONPATH=src
export EFFICIENTROUTE_OUTPUT_ROOT="$ROOT/RUN-CUSTOMER-NET"
export EFFICIENTROUTE_BOUNDARY="$EFFICIENTROUTE_OUTPUT_ROOT/data/derived/00-custom-boundary.geojson"
export EFFICIENTROUTE_REQUIRED_NETWORK="$EFFICIENTROUTE_OUTPUT_ROOT/data/derived/00-custnet-network.geojson"
export EFFICIENTROUTE_SCOPE_VARIANT=A
export EFFICIENTROUTE_CAMPAIGN_START=2026-08-29
# Zone A was requested and is not in the data. Stamped under the title of every
# report this run writes, so a Zone B number is never read as an A+B number.
export EFFICIENTROUTE_CAMPAIGN_CAVEAT='**Zone A was requested and is not in the data.** `data/custom/B Zone_Streets/AB_zones.shp` holds one polygon, `Name = "Zone B"`, despite the layer being called `AB_zones`; its `FolderPath` names `Tbilisi Possible parking zones.kmz` as the source, so Zone A presumably exists there and was never exported. **This run covers Zone B only.** Nothing in it is an A+B result, and no Zone A boundary has been inferred or approximated.'

STREETS="data/custom/B Zone_Streets/Streets.shp"
ZONES="data/custom/B Zone_Streets/AB_zones.shp"

STAGES=${*:-"prepare stage0 stage1 stage0b stage2 stage3 stage4 stage5 stage7"}

for stage in $STAGES; do
    echo "=================================================== $stage"
    case "$stage" in
        prepare)
            uv run python -m efficientroute prepare-zone --shapefile "$ZONES" --name "Zone B"
            uv run python -m efficientroute prepare-network --shapefile "$STREETS"
            ;;
        *)
            uv run python -m efficientroute "$stage"
            ;;
    esac
done
