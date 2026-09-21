"""Stage 2 item 1 — per-arc capture speed, as a model rather than a table.

SPEC §6 lists the terms; the arrangement below is what makes them *fittable*.
Every term is a multiplicative factor on speed::

    v = v_base(class | maxspeed) · f_gradient · f_surface · f_width / c_congestion
    v_capture = v            where capture_quality == "reduced"   (SPEC §3.2)
              = min(v, 40)   everywhere else                      (SPEC §5)

Multiplicative means **linear in log speed**, and that is the whole design.
Stage 6 map-matches real traces onto these arcs and calls :meth:`SpeedModel.fit`,
which recovers every coefficient with one ordinary least-squares solve — no
optimiser, no re-derivation, no hand-tuning.  A hard-coded speed table cannot be
calibrated later; this can, and the interface exists now so Stage 6 does not have
to reopen the model.

The gradient term is the one place the functional form was chosen for this
property: `exp(-k·g)` rather than `1/(1 + k·g)`.  Both are monotone and bounded;
only the first is log-linear.  Its coefficient is still pinned to SPEC §6's
worked example — see `config.GRADIENT_ANCHOR_PCT`.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

from . import config as C

#: Below this a "speed" is a modelling accident, not a driving speed.  Nothing in
#: the Tbilisi table comes near it; the floor exists so a pathological tag
#: (`maxspeed=1`) cannot produce an arc that takes a day to drive.
MIN_SPEED_KMH = 3.0

#: Structures are flat by construction, so a DEM gradient on one is not evidence
#: about the road deck (SPEC §6, Stage 0 §10).
FLAT_STRUCTURES: frozenset[str] = frozenset({"bridge", "tunnel"})


@dataclasses.dataclass(frozen=True)
class SpeedModel:
    """The coefficients of the capture-speed model, and nothing else.

    Held as data rather than code so that the fitted model from Stage 6 and the
    prior from `config` are the same kind of object, serialise the same way, and
    can be diffed against each other.
    """

    base_free_flow_kmh: Mapping[str, float]
    default_free_flow_kmh: float
    gradient_uphill_decay_per_pct: float
    gradient_downhill_decay_per_pct: float
    gradient_cap_pct: float
    gradient_dem_noise_m: float
    gradient_deadband_max_pct: float
    surface_factor: Mapping[str, float]
    default_surface_factor: float
    narrow_dir_width_m: float
    narrow_width_factor: float
    capture_speed_max_kmh: float

    # ------------------------------------------------------------ construction

    @classmethod
    def from_config(cls) -> SpeedModel:
        """The prior: every constant as declared and justified in `config`."""
        return cls(
            base_free_flow_kmh=dict(C.BASE_FREE_FLOW_KMH),
            default_free_flow_kmh=float(C.BASE_FREE_FLOW_DEFAULT_KMH),
            gradient_uphill_decay_per_pct=float(C.GRADIENT_UPHILL_DECAY_PER_PCT),
            gradient_downhill_decay_per_pct=float(
                C.GRADIENT_UPHILL_DECAY_PER_PCT * C.GRADIENT_DOWNHILL_DECAY_RATIO
            ),
            gradient_cap_pct=float(C.GRADIENT_CAP_PCT),
            gradient_dem_noise_m=float(C.GRADIENT_DEM_NOISE_M),
            gradient_deadband_max_pct=float(C.GRADIENT_DEADBAND_MAX_PCT),
            surface_factor=dict(C.SURFACE_FACTOR),
            default_surface_factor=float(C.SURFACE_DEFAULT_FACTOR),
            narrow_dir_width_m=float(C.NARROW_DIR_WIDTH_M),
            narrow_width_factor=float(C.NARROW_WIDTH_FACTOR),
            capture_speed_max_kmh=float(C.CAPTURE_SPEED_MAX_KMH),
        )

    def to_dict(self) -> dict:
        payload = dataclasses.asdict(self)
        payload["base_free_flow_kmh"] = dict(sorted(self.base_free_flow_kmh.items()))
        payload["surface_factor"] = dict(sorted(self.surface_factor.items()))
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping) -> SpeedModel:
        fields = {f.name for f in dataclasses.fields(cls)}
        unknown = set(payload) - fields
        if unknown:
            raise ValueError(f"unknown SpeedModel fields: {sorted(unknown)}")
        return cls(**{k: payload[k] for k in fields})

    def replace(self, **changes) -> SpeedModel:
        return dataclasses.replace(self, **changes)

    # ------------------------------------------------------------------ terms

    def free_flow_kmh(self, frame: pd.DataFrame) -> np.ndarray:
        """Item 1.1 and 1.2 — base speed by class, overridden by posted `maxspeed`."""
        base = (
            frame["highway_class"]
            .map(self.base_free_flow_kmh)
            .fillna(self.default_free_flow_kmh)
            .to_numpy(dtype="float64")
        )
        tagged = _column(frame, "maxspeed")
        return np.where(np.isnan(tagged), base, tagged)

    def gradient_deadband_pct(self, frame: pd.DataFrame) -> np.ndarray:
        """The spurious grade a fixed DEM elevation error puts on an arc.

        A constant vertical error over a short arc *is* a steep gradient
        arithmetically, so the deadband has to scale with 1/length.  The
        magnitude is measured, not assumed: see `config.GRADIENT_DEM_NOISE_M`.
        """
        length = _column(frame, "length_m")
        with np.errstate(divide="ignore", invalid="ignore"):
            band = np.where(length > 0, self.gradient_dem_noise_m / length * 100.0, 0.0)
        return np.minimum(np.nan_to_num(band), self.gradient_deadband_max_pct)

    def effective_gradient_pct(self, frame: pd.DataFrame) -> np.ndarray:
        """Signed gradient the model should believe, after noise and structure.

        Three corrections, in order: a tagged `incline` is direct evidence and
        keeps its full value; a DEM gradient on a bridge or tunnel is discarded
        outright; every other DEM gradient is shrunk by the deadband and then
        capped at the point where a 30 m DEM stops being evidence at all.
        """
        gradient = _column(frame, "gradient_pct")
        gradient = np.nan_to_num(gradient, nan=0.0)
        source = frame.get("gradient_source", pd.Series("dem", index=frame.index))
        from_dem = (source.fillna("dem").to_numpy() == "dem")

        structure = frame.get("structure", pd.Series("", index=frame.index))
        flat = np.isin(structure.fillna("").to_numpy(), list(FLAT_STRUCTURES)) & from_dem

        deadband = np.where(from_dem, self.gradient_deadband_pct(frame), 0.0)
        magnitude = np.maximum(np.abs(gradient) - deadband, 0.0)
        magnitude = np.minimum(magnitude, self.gradient_cap_pct)
        magnitude = np.where(flat, 0.0, magnitude)
        return np.sign(gradient) * magnitude

    def gradient_factor(self, frame: pd.DataFrame) -> np.ndarray:
        """Item 1.3 — `exp(-k·g)`, with a shallower coefficient downhill."""
        gradient = self.effective_gradient_pct(frame)
        decay = np.where(
            gradient >= 0,
            self.gradient_uphill_decay_per_pct,
            self.gradient_downhill_decay_per_pct,
        )
        return np.exp(-decay * np.abs(gradient))

    def surface_factor_of(self, frame: pd.DataFrame) -> np.ndarray:
        """Item 1.4, surface half.  Untagged takes `default_surface_factor`."""
        surface = frame.get("surface", pd.Series("", index=frame.index)).fillna("")
        mapped = surface.map(self.surface_factor).to_numpy(dtype="float64")
        return np.where(np.isnan(mapped), self.default_surface_factor, mapped)

    def is_narrow(self, frame: pd.DataFrame) -> np.ndarray:
        """Too narrow for two vehicles to pass without one of them yielding.

        Two independent kinds of evidence, either of which is enough: a tagged
        carriageway width below the threshold *for this direction of travel*, or
        a single tagged lane on a two-way street.
        """
        width = _column(frame, "width")
        oneway = frame.get("oneway", pd.Series("no", index=frame.index)).fillna("no").to_numpy()
        dir_width = np.where(oneway != "no", width, width / 2.0)
        narrow_width = ~np.isnan(dir_width) & (dir_width < self.narrow_dir_width_m)

        lanes = _column(frame, "lanes")
        single_lane_two_way = (~np.isnan(lanes)) & (lanes <= 1) & (oneway == "no")
        return narrow_width | single_lane_two_way

    def width_factor(self, frame: pd.DataFrame) -> np.ndarray:
        return np.where(self.is_narrow(frame), self.narrow_width_factor, 1.0)

    # ----------------------------------------------------------------- speeds

    def unconstrained_kmh(
        self, frame: pd.DataFrame, congestion_index: np.ndarray | float = 1.0
    ) -> np.ndarray:
        """Every term applied, before the capture cap.  This is deadhead speed.

        SPEC §6: "Deadhead segments are uncapped."
        """
        speed = (
            self.free_flow_kmh(frame)
            * self.gradient_factor(frame)
            * self.surface_factor_of(frame)
            * self.width_factor(frame)
        ) / np.asarray(congestion_index, dtype="float64")
        return np.maximum(speed, MIN_SPEED_KMH)

    def capture_speed_kmh(
        self, frame: pd.DataFrame, congestion_index: np.ndarray | float = 1.0
    ) -> np.ndarray:
        """Item 1.5 — the 40 km/h cap, and SPEC §3.2's exemption from it.

        The cap is applied **after** congestion, not before, and that ordering is
        the reason the campaign estimate survives the congestion assumption:
        where traffic is already slower than 40 km/h the cap never binds, and
        where free flow is faster than 40 the cap absorbs the traffic entirely.
        Congestion only moves the answer in the band between the two.
        """
        speed = self.unconstrained_kmh(frame, congestion_index)
        reduced = (
            frame.get("capture_quality", pd.Series("full", index=frame.index))
            .fillna("full")
            .to_numpy()
            == "reduced"
        )
        return np.where(reduced, speed, np.minimum(speed, self.capture_speed_max_kmh))

    def capture_time_s(
        self, frame: pd.DataFrame, congestion_index: np.ndarray | float = 1.0
    ) -> np.ndarray:
        """Seconds to capture one traversal of each arc."""
        speed = self.capture_speed_kmh(frame, congestion_index)
        return _column(frame, "length_m") / (speed / 3.6)

    def deadhead_time_s(
        self, frame: pd.DataFrame, congestion_index: np.ndarray | float = 1.0
    ) -> np.ndarray:
        return _column(frame, "length_m") / (
            self.unconstrained_kmh(frame, congestion_index) / 3.6
        )

    # -------------------------------------------------------------- refitting

    def design(self, frame: pd.DataFrame) -> tuple[np.ndarray, list[str], np.ndarray]:
        """Log-space design matrix, its column names, and the `maxspeed` offset.

        Model: ``log v = Σ β_class·1[class] + β_up·g⁺ + β_down·g⁻
        + Σ β_surface·1[surface] + β_narrow·narrow + log(maxspeed)``.

        A row with a posted `maxspeed` carries its base speed in the offset and
        contributes **no** class column, so posted speeds constrain the penalty
        terms without biasing the class table that only applies where nothing is
        posted.  The smooth-pavement default is the reference surface level and
        is therefore absent from the matrix — without that the class and surface
        blocks would both carry an intercept and the system would be singular.
        """
        gradient = self.effective_gradient_pct(frame)
        tagged = _column(frame, "maxspeed")
        has_maxspeed = ~np.isnan(tagged)

        columns: list[str] = []
        blocks: list[np.ndarray] = []

        classes = sorted(set(frame["highway_class"].astype(str)))
        for name in classes:
            indicator = (frame["highway_class"].astype(str).to_numpy() == name) & ~has_maxspeed
            if indicator.any():
                columns.append(f"log_base_kmh[{name}]")
                blocks.append(indicator.astype("float64"))

        columns += ["gradient_uphill_decay_per_pct", "gradient_downhill_decay_per_pct"]
        blocks.append(-np.maximum(gradient, 0.0))
        blocks.append(-np.maximum(-gradient, 0.0))

        surface = frame.get("surface", pd.Series("", index=frame.index)).fillna("").to_numpy()
        known = {s for s in np.unique(surface) if s in self.surface_factor}
        for name in sorted(known):
            columns.append(f"log_surface_factor[{name}]")
            blocks.append((surface == name).astype("float64"))

        columns.append("log_narrow_width_factor")
        blocks.append(self.is_narrow(frame).astype("float64"))

        offset = np.where(has_maxspeed, np.log(np.where(has_maxspeed, tagged, 1.0)), 0.0)
        return np.column_stack(blocks), columns, offset

    def fit(
        self,
        frame: pd.DataFrame,
        observed_kmh: np.ndarray,
        congestion_index: np.ndarray | float = 1.0,
        weights: np.ndarray | None = None,
    ) -> tuple[SpeedModel, dict]:
        """Refit the coefficients from observed speeds.  Stage 6's entry point.

        `observed_kmh` is the map-matched speed actually driven, and
        `congestion_index` is what the congestion model believed at the time —
        dividing it back out is what turns a congested observation into evidence
        about free flow.  Coefficients with no observations behind them keep
        their prior value, so a partial campaign refits only what it saw.

        Returns the new model and a diagnostics dict (residual RMSE in log space,
        observation counts, and the coefficients that moved).
        """
        observed = np.asarray(observed_kmh, dtype="float64")
        usable = np.isfinite(observed) & (observed > 0)
        if not usable.any():
            raise ValueError("no usable observations: every observed speed is zero or NaN")

        frame = frame.loc[usable] if isinstance(frame, pd.DataFrame) else frame
        observed = observed[usable]
        index = np.broadcast_to(
            np.asarray(congestion_index, dtype="float64"), usable.shape
        )[usable]

        matrix, columns, offset = self.design(frame)
        target = np.log(observed * index) - offset

        if weights is not None:
            root = np.sqrt(np.asarray(weights, dtype="float64")[usable])[:, None]
            solution, *_ = np.linalg.lstsq(matrix * root, target * root.ravel(), rcond=None)
        else:
            solution, *_ = np.linalg.lstsq(matrix, target, rcond=None)

        support = (matrix != 0).sum(axis=0)
        fitted = dict(zip(columns, solution))
        counts = dict(zip(columns, support.astype(int)))

        base = dict(self.base_free_flow_kmh)
        surface = dict(self.surface_factor)
        changes: dict[str, float] = {}
        for name, value in fitted.items():
            if counts[name] == 0:
                continue
            if name.startswith("log_base_kmh["):
                key = name[len("log_base_kmh[") : -1]
                base[key] = float(np.clip(math.exp(value), MIN_SPEED_KMH, 130.0))
                changes[name] = base[key]
            elif name.startswith("log_surface_factor["):
                key = name[len("log_surface_factor[") : -1]
                surface[key] = float(np.clip(math.exp(value), 0.1, 1.5))
                changes[name] = surface[key]

        narrow = float(np.clip(math.exp(fitted["log_narrow_width_factor"]), 0.1, 1.5))
        uphill = float(max(fitted["gradient_uphill_decay_per_pct"], 0.0))
        downhill = float(max(fitted["gradient_downhill_decay_per_pct"], 0.0))

        model = self.replace(
            base_free_flow_kmh=base,
            surface_factor=surface,
            narrow_width_factor=narrow,
            gradient_uphill_decay_per_pct=uphill,
            gradient_downhill_decay_per_pct=downhill,
        )
        residual = target - matrix @ solution
        diagnostics = {
            "n_observations": int(usable.sum()),
            "log_rmse": float(np.sqrt(np.mean(residual**2))),
            "coefficient_support": counts,
            "refit": changes
            | {
                "log_narrow_width_factor": narrow,
                "gradient_uphill_decay_per_pct": uphill,
                "gradient_downhill_decay_per_pct": downhill,
            },
        }
        return model, diagnostics


def _column(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        raise KeyError(f"the arc table has no {name!r} column")
    return frame[name].to_numpy(dtype="float64")
