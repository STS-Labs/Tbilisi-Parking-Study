#!/bin/sh
# Stage 8 across every campaign, in the order prompts/08 asks for: smallest first,
# Tbilisi last. Tbilisi is where the biggest absolute prize is and where a slow or
# wrong implementation costs the most time to discover.
#
# Each campaign's full output goes to its own log and the exit status is checked.
# An earlier version piped straight into `tail`, which meant the shell saw tail's
# exit status and a campaign that crashed looked exactly like one that finished
# quietly — two of four failed that way and the run still reported success.
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

TIER=${TIER:-2}
LOGS=${LOGS:-$ROOT/.stage8-logs}
mkdir -p "$LOGS"

failed=""
for campaign in zone-b customer-net osm-full tbilisi; do
    echo
    echo "=============================================== $campaign (tier $TIER)"
    if sh tools/with-run-env.sh "$campaign" \
        uv run python -m efficientroute stage8 --tier "$TIER" > "$LOGS/$campaign.log" 2>&1
    then
        tail -12 "$LOGS/$campaign.log"
    else
        echo "FAILED — last 25 lines of $LOGS/$campaign.log:"
        tail -25 "$LOGS/$campaign.log"
        failed="$failed $campaign"
    fi
done

echo
if [ -n "$failed" ]; then
    echo "campaigns that FAILED:$failed"
    exit 1
fi
echo "all campaigns completed"
