"""Stage 2 item 2 — congestion, and being explicit that it is assumed.

**There is no traffic data for Tbilisi in this pipeline.**  Every coefficient in
this module is a declared assumption, and the stage report says so in those
words.  What the module provides instead of false precision is the machinery to
show how much the answer depends on them: `scaled` rescales the assumed *delay*
so the campaign estimate can be recomputed across a range, and the Stage 2 report
carries the resulting sensitivity table.

The index is a **travel-time ratio**: 1.00 is free flow and 1.45 means the same
journey takes 45% longer.  Rescaling multiplies the delay, not the ratio —
`index(λ) = 1 + λ·(index − 1)` — so λ = 0 is free flow, λ = 1 the assumption as
declared, and λ = 1.5 half again as much delay.  Scaling the ratio itself would
make "+50% congestion" mean a 2.2× travel time on a road that is barely
congested, which is not what the phrase means to a scheduler.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from . import config as C


@dataclasses.dataclass(frozen=True)
class CongestionModel:
    """Multiplier by `highway_class` × time-of-day band.  Assumed throughout."""

    bands: tuple[tuple[str, float, float], ...]
    index: Mapping[str, Mapping[str, float]]
    default: Mapping[str, float]
    scale: float = 1.0

    @classmethod
    def from_config(cls) -> CongestionModel:
        return cls(
            bands=tuple(C.CONGESTION_BANDS),
            index={k: dict(v) for k, v in C.CONGESTION_INDEX.items()},
            default=dict(C.CONGESTION_DEFAULT),
            scale=1.0,
        )

    def to_dict(self) -> dict:
        return {
            "bands": [list(b) for b in self.bands],
            "index": {k: dict(sorted(v.items())) for k, v in sorted(self.index.items())},
            "default": dict(sorted(self.default.items())),
            "scale": self.scale,
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> CongestionModel:
        return cls(
            bands=tuple(tuple(b) for b in payload["bands"]),
            index={k: dict(v) for k, v in payload["index"].items()},
            default=dict(payload["default"]),
            scale=float(payload.get("scale", 1.0)),
        )

    # ------------------------------------------------------------- sensitivity

    def scaled(self, factor: float) -> CongestionModel:
        """The same model with the assumed *delay* multiplied by `factor`."""
        return dataclasses.replace(self, scale=factor)

    def band_names(self) -> list[str]:
        return [name for name, _, _ in self.bands]

    def value(self, highway_class: str, band: str) -> float:
        row = self.index.get(highway_class, self.default)
        raw = row.get(band, self.default.get(band, 1.0))
        return 1.0 + self.scale * (raw - 1.0)

    # ------------------------------------------------------------------ arrays

    def index_for(self, frame: pd.DataFrame, band: str) -> np.ndarray:
        classes = frame["highway_class"].astype(str).to_numpy()
        lookup = {name: self.value(name, band) for name in np.unique(classes)}
        return np.array([lookup[name] for name in classes], dtype="float64")

    def blended_index(self, frame: pd.DataFrame, weights: Mapping[str, float]) -> np.ndarray:
        """One index per arc, averaged over the bands the working day spans.

        Weighted by *duration* in each band.  An index is already a time ratio,
        so a duration-weighted mean of ratios is the first-order right answer;
        the second-order correction (congested time is itself longer, so the car
        spends more of the day in the worse band) is well inside the ±25% the
        sensitivity table already sweeps.
        """
        total = sum(weights.values())
        if total <= 0:
            return np.ones(len(frame), dtype="float64")
        out = np.zeros(len(frame), dtype="float64")
        for band, weight in weights.items():
            out += (weight / total) * self.index_for(frame, band)
        return out

    # ------------------------------------------------------- day arithmetic

    def band_hours(self) -> dict[str, float]:
        return {name: float(end - start) for name, start, end in self.bands}

    def overlap_hours(self, start: float, end: float) -> dict[str, float]:
        """Hours of `[start, end)` that fall inside each band."""
        return {
            name: max(0.0, min(end, band_end) - max(start, band_start))
            for name, band_start, band_end in self.bands
        }

    def work_band_weights(
        self, leg_hours: float, break_hours: float = C.BREAK_HOURS
    ) -> dict[str, float]:
        """Band exposure of the productive window, given a one-way depot leg.

        SPEC §7.2: a 09:00 start puts the outbound leg in the morning peak and an
        18:00 finish puts the return leg in the evening peak, so the longer the
        legs the *less* of the peak the capture work actually sees.  That is a
        real effect on eastern days and it is why this is computed rather than
        assumed flat.  The break is taken out of the midday band.
        """
        first = self.bands[0][1]
        last = self.bands[-1][2]
        start = min(first + max(leg_hours, 0.0), last)
        end = max(last - max(leg_hours, 0.0), start)
        weights = self.overlap_hours(start, end)

        remaining = max(break_hours, 0.0)
        for name in ("midday", *self.band_names()):
            if remaining <= 0:
                break
            if name not in weights:
                continue
            taken = min(weights[name], remaining)
            weights[name] -= taken
            remaining -= taken
        return weights

    def leg_band_weights(self) -> dict[str, float]:
        """Depot legs sit at the two ends of the shift, one in each peak."""
        first, last = self.bands[0][0], self.bands[-1][0]
        if first == last:
            return {first: 1.0}
        return {first: 0.5, last: 0.5}


def sensitivity_levels(
    levels: Sequence[float] = C.CONGESTION_SENSITIVITY,
) -> list[float]:
    """The λ values the report sweeps.  Sorted, deduplicated, deterministic."""
    return sorted({float(v) for v in levels})
