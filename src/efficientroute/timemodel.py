"""Stage 2 — attach the time model to the arc table.

Three columns, all pure functions of what Stage 0 already wrote:

``service_role``        item 0, from `servicerole`
``capture_speed_kmh``   item 1, from `speedmodel`, free-flow (uncongested)
``capture_time_s``      `length_m / capture_speed_kmh`, in seconds

`capture_speed_kmh` deliberately carries **no congestion**.  Congestion is a
scenario, not a property of a street: the report sweeps it across a range and the
column would otherwise silently encode whichever point of that range happened to
be the assumption of the day.  Everything downstream that wants a congested time
calls `speedmodel.SpeedModel.capture_time_s` with an index, which is why the
sensitivity table is a recomputation rather than a multiplication — the 40 km/h
cap means congestion does not scale hours linearly.

Because the columns are a deterministic function of the Stage 0 table and the
persisted model, the arc table can be rebuilt byte-for-byte from the extract plus
`02-time-model.json` — which is what keeps the Stage 0 determinism gate honest
after Stage 2 has written to `network.gpkg`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import servicerole
from .speedmodel import SpeedModel

#: Appended to `network.COLUMNS`, in this order, immediately before `geometry`.
STAGE2_COLUMNS: tuple[str, ...] = ("service_role", "capture_speed_kmh", "capture_time_s")


def required_traversals(frame: pd.DataFrame) -> np.ndarray:
    """Traversals each arc contributes to the required total (SPEC §2.1, §3.4).

    The vectorised twin of `passes.required_traversals`; `test_timemodel` asserts
    the two agree row by row rather than trusting the comment.
    """
    shared = frame["pair_requirement"].to_numpy() > 0
    representative = frame["is_pair_representative"].to_numpy(dtype=bool)
    return np.where(
        shared,
        np.where(representative, frame["pair_requirement"].to_numpy(), 0),
        frame["min_passes"].to_numpy(),
    ).astype("int64")


def augment(arcs: pd.DataFrame, model: SpeedModel | None = None) -> pd.DataFrame:
    """Return the arc table with the three Stage 2 columns attached.

    Idempotent: re-running on an already-augmented table recomputes the columns
    in place rather than duplicating them.
    """
    model = SpeedModel.from_config() if model is None else model
    frame = arcs.copy()

    frame["service_role"] = servicerole.classify(frame)
    speed = model.capture_speed_kmh(frame)
    frame["capture_speed_kmh"] = speed
    frame["capture_time_s"] = frame["length_m"].to_numpy(dtype="float64") / (speed / 3.6)

    ordered = [c for c in frame.columns if c not in STAGE2_COLUMNS and c != "geometry"]
    ordered += list(STAGE2_COLUMNS)
    if "geometry" in frame.columns:
        ordered.append("geometry")
    return frame[ordered]


def has_stage2_columns(frame: pd.DataFrame) -> bool:
    return all(column in frame.columns for column in STAGE2_COLUMNS)


def load_model(path=C.TIME_MODEL_JSON) -> SpeedModel:
    """The persisted model, or the config prior when Stage 2 has not run.

    Stage 6 refits and rewrites `speed_model` in this artifact; reading it back
    here is what makes a refit propagate to every downstream stage without any
    code change.
    """
    import json

    if not path.exists():
        return SpeedModel.from_config()
    payload = json.loads(path.read_text())
    return SpeedModel.from_dict(payload["speed_model"])


def capture_hours(
    frame: pd.DataFrame, congestion_index=None, model: SpeedModel | None = None
) -> float:
    """Σ capture time over *required* traversals, in hours.

    With no congestion index this reads `capture_time_s` straight off the table,
    which is what the gate reconciles the reported capture hours against.  With
    one, the times are recomputed — because the 40 km/h cap means congestion does
    not scale hours linearly and the column cannot simply be multiplied.  The
    model defaults to whatever is persisted, so a Stage 6 refit is honoured here
    too rather than silently falling back to the config prior.
    """
    traversals = required_traversals(frame)
    if congestion_index is None:
        seconds = frame["capture_time_s"].to_numpy(dtype="float64")
    else:
        seconds = (model or load_model()).capture_time_s(frame, congestion_index)
    return float((seconds * traversals).sum() / 3600.0)
