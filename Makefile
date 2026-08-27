# This checkout lives under ~/Desktop, which macOS syncs through iCloud Drive.
# iCloud sets the UF_HIDDEN flag on files inside .venv and duplicates them, and
# CPython's site.py silently skips hidden .pth files — so the editable install
# vanishes with no error message, intermittently and mid-run.
#
# Rather than race it, every target below runs the package straight from source
# with PYTHONPATH, which does not consult the editable install at all.
RUN = PYTHONPATH=src uv run python -m efficientroute

.PHONY: setup stage0 stage0b stage1 stage2 stage3 stage4 stage4b stage4c stage5 test gate gate1 gate2 gate3 gate4 gate4b gate4c gate5 all clean-derived

setup:
	uv sync

stage0: setup
	$(RUN) stage0

stage0b: setup
	$(RUN) stage0b

stage1: setup
	$(RUN) stage1

stage2: setup
	$(RUN) stage2

stage3: setup
	$(RUN) stage3

stage4: setup
	$(RUN) stage4

stage4b: setup
	$(RUN) stage4b

stage5: setup
	$(RUN) stage5

stage4c: setup
	$(RUN) stage4c

test: setup
	uv run pytest -q

gate: setup
	uv run pytest -q -m gate

gate1: setup
	uv run pytest -q -m gate1

gate2: setup
	uv run pytest -q -m gate2

gate3: setup
	uv run pytest -q -m gate3

gate4: setup
	uv run pytest -q -m gate4

gate4b: setup
	uv run pytest -q -m gate4b

gate4c: setup
	uv run pytest -q -m gate4c

gate5: setup
	uv run pytest -q -m gate5

all: stage0 gate stage1 gate1 stage0b stage2 gate2 stage3 gate3 stage4 gate4 stage4b gate4b stage5 gate5

clean-derived:
	rm -rf data/derived/* reports/00-network-stats.md reports/00-network.html \
	       reports/01-turn-audit.md reports/01-turn-graph.html \
	       reports/02-time-model.md reports/03-bounds.md reports/03-tour-*.gpx \
	       reports/04-zoning.md reports/04-zones.html
	touch data/derived/.gitkeep
