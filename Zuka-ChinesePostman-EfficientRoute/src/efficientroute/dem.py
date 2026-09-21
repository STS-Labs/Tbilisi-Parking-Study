"""DEM handling — elevation sampling and per-arc gradient.

SPEC §6 makes gradient part of the time model ("a 12% Tbilisi lane is 12 km/h,
not 40"), so Stage 0 has to measure it even though it does no routing.

Source note: Copernicus GLO-30 has no tiles over the N41/E044 and N41/E045
cells — they are withheld from the free instance for this border region — so
Stage 0 uses SRTM 1-arcsec, the other source named in the stage brief and the
same 30 m ground resolution.
"""

from __future__ import annotations

import gzip
import math
import shutil
import urllib.request
from pathlib import Path

import numpy as np
from affine import Affine

from . import config as C

#: SRTM 1-arcsec tiles are 3601x3601 int16, big-endian, no header.
SRTM_SIDE = 3601
SRTM_DTYPE = ">i2"


class BilinearSampler:
    """Bilinear elevation lookup on a north-up raster.

    Nearest-neighbour would quantise gradient badly on short arcs: a 25 m
    residential segment can fall inside one 30 m DEM cell, which reads as a
    perfectly flat street in a city built on ridges.
    """

    def __init__(self, grid: np.ndarray, transform: Affine, nodata: float) -> None:
        values = np.asarray(grid, dtype="float64")
        self.grid = np.where(values == nodata, np.nan, values)
        self.transform = transform
        self._inverse = ~transform
        self.nodata = nodata

    def sample(self, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        lons = np.asarray(lons, dtype="float64")
        lats = np.asarray(lats, dtype="float64")
        cols, rows = self._inverse * (lons, lats)

        # Affine yields pixel-corner coordinates; shift to pixel centres so that
        # an integer index lands exactly on a sample point.
        x = np.asarray(cols, dtype="float64") - 0.5
        y = np.asarray(rows, dtype="float64") - 0.5

        height, width = self.grid.shape
        eps = 1e-9
        inside = (x >= -eps) & (x <= width - 1 + eps) & (y >= -eps) & (y <= height - 1 + eps)

        xc = np.clip(x, 0.0, width - 1.0)
        yc = np.clip(y, 0.0, height - 1.0)
        x0 = np.floor(xc).astype(np.intp)
        y0 = np.floor(yc).astype(np.intp)
        x1 = np.minimum(x0 + 1, width - 1)
        y1 = np.minimum(y0 + 1, height - 1)
        fx = xc - x0
        fy = yc - y0

        top = self.grid[y0, x0] * (1.0 - fx) + self.grid[y0, x1] * fx
        bottom = self.grid[y1, x0] * (1.0 - fx) + self.grid[y1, x1] * fx
        out = top * (1.0 - fy) + bottom * fy
        return np.where(inside, out, np.nan)


def gradient_pct(elev_from: float, elev_to: float, length_m: float) -> float:
    """Signed gradient along a *directed* arc: uphill positive, downhill negative."""
    if not length_m or length_m <= 0:
        return 0.0
    return (elev_to - elev_from) / length_m * 100.0


def srtm_tiles_for_bbox(minx: float, miny: float, maxx: float, maxy: float) -> list[str]:
    """SRTM 1-arcsec tile names covering a lon/lat bounding box."""
    tiles: list[str] = []
    for lat in range(math.floor(miny), math.floor(maxy) + 1):
        for lon in range(math.floor(minx), math.floor(maxx) + 1):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            tiles.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")
    return sorted(tiles)


def tile_path(tile: str, directory: Path | None = None) -> Path:
    return (directory or C.DEM_DIR) / f"{tile}.hgt.gz"


def download_tile(tile: str, directory: Path | None = None) -> Path:
    """Fetch one SRTM tile if it is not already on disk."""
    target = tile_path(tile, directory)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = C.SRTM_TILE_URL.format(lat=tile[:3], tile=tile)
    tmp = target.with_suffix(".part")
    with urllib.request.urlopen(url) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(target)
    return target


def read_tile(tile: str, directory: Path | None = None) -> tuple[np.ndarray, Affine]:
    """Read one SRTM tile into a grid plus its north-up affine transform."""
    path = tile_path(tile, directory)
    with gzip.open(path, "rb") as handle:
        raw = np.frombuffer(handle.read(), dtype=SRTM_DTYPE)
    grid = raw.reshape(SRTM_SIDE, SRTM_SIDE).astype("float64")

    lat = int(tile[1:3]) * (1 if tile[0] == "N" else -1)
    lon = int(tile[4:7]) * (1 if tile[3] == "E" else -1)
    step = 1.0 / (SRTM_SIDE - 1)
    # Cells are point samples on a 1-degree grid; the corner origin sits half a
    # cell outside the sample points.
    transform = Affine(step, 0.0, lon - step / 2, 0.0, -step, lat + 1 + step / 2)
    return grid, transform


def mosaic(tiles: list[str], directory: Path | None = None) -> BilinearSampler:
    """Stitch SRTM tiles into a single sampler covering their union."""
    if not tiles:
        raise ValueError("no DEM tiles requested")

    grids = {tile: read_tile(tile, directory) for tile in tiles}
    lats = sorted({int(t[1:3]) * (1 if t[0] == "N" else -1) for t in tiles})
    lons = sorted({int(t[4:7]) * (1 if t[3] == "E" else -1) for t in tiles})
    step = 1.0 / (SRTM_SIDE - 1)

    height = len(lats) * (SRTM_SIDE - 1) + 1
    width = len(lons) * (SRTM_SIDE - 1) + 1
    canvas = np.full((height, width), C.SRTM_NODATA, dtype="float64")

    for tile, (grid, _) in grids.items():
        lat = int(tile[1:3]) * (1 if tile[0] == "N" else -1)
        lon = int(tile[4:7]) * (1 if tile[3] == "E" else -1)
        row0 = (lats[-1] - lat) * (SRTM_SIDE - 1)
        col0 = (lon - lons[0]) * (SRTM_SIDE - 1)
        canvas[row0 : row0 + SRTM_SIDE, col0 : col0 + SRTM_SIDE] = grid

    transform = Affine(
        step, 0.0, lons[0] - step / 2, 0.0, -step, lats[-1] + 1 + step / 2
    )
    return BilinearSampler(canvas, transform, C.SRTM_NODATA)
