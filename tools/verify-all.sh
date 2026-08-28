#!/bin/sh
# Every gate, under every campaign this checkout can produce.
#
# The two new runs have to pass their own gates, and — the point of the exercise —
# the two committed campaigns have to keep passing theirs with the new code in
# place. A change that only holds for the campaign it was written for is not a
# change to this pipeline, it is a fork of it.
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

for campaign in tbilisi zone-b osm-full customer-net; do
    echo
    echo "=============================================== $campaign"
    sh tools/with-run-env.sh "$campaign" uv run pytest -q "$@" || echo "^^ $campaign FAILED"
done
