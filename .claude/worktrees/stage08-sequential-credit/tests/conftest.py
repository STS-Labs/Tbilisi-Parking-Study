import json

import pytest

from efficientroute import config as C


@pytest.fixture(scope="session")
def arcs():
    """The canonical Stage 0 arc table. Skips when the pipeline has not been run."""
    if not C.NETWORK_GPKG.exists():
        pytest.skip(f"{C.NETWORK_GPKG} not built — run `uv run efficientroute stage0`")
    import geopandas as gpd

    return gpd.read_file(C.NETWORK_GPKG, layer=C.NETWORK_LAYER)


@pytest.fixture(scope="session")
def stats():
    if not C.STATS_JSON.exists():
        pytest.skip(f"{C.STATS_JSON} not built — run `uv run efficientroute stage0`")
    return json.loads(C.STATS_JSON.read_text())
