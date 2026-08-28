#!/bin/sh
# Stage 8 across every campaign, in the order prompts/08 asks for: smallest first,
# Tbilisi last. Tbilisi is where the biggest absolute prize is and where a slow or
# wrong implementation costs the most time to discover.
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

TIER=${TIER:-2}

for campaign in zone-b customer-net osm-full tbilisi; do
    echo
    echo "=============================================== $campaign (tier $TIER)"
    sh tools/with-run-env.sh "$campaign" \
        uv run python -m efficientroute stage8 --tier "$TIER" 2>&1 | tail -14
done
