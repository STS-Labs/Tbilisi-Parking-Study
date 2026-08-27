"""Service-scope scenarios for SPEC §2.1's open `highway=service` question.

**Measurement only.**  Variant A — every `highway=service` arc included — is what
the pipeline builds and remains the default.  B and C exist so the scope decision
is made against real numbers rather than an estimate; nothing here changes a
classification, a threshold or a default, and no switch is exposed.

Each variant is evaluated properly rather than by subtraction: dropping service
roads changes which arcs remain strongly connected, so the base component
analysis and L(G) are both rebuilt on the filtered network.  Subtracting the
service km from the headline would overstate what variants B and C actually save.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import connectivity as K
from . import network as N

#: The Stage 0b axis: split `highway=service` by its `service=*` subtag.
VARIANTS: tuple[str, ...] = ("A", "B", "C")

#: Stage 2 adds a fourth on a different axis — connectivity rather than tagging.
#: It is deliberately *not* in `VARIANTS`: `compare` drives the Stage 0b artifact,
#: which must keep reporting exactly what it reported before, and D needs a
#: `service_role` column that does not exist until Stage 2 has run.
KNOWN_VARIANTS: tuple[str, ...] = ("A", "B", "C", "D")

VARIANT_LABELS: dict[str, str] = {
    "A": "as built — all `highway=service`",
    "B": "streets only — service where `service_type` is alley or untagged",
    "C": "none — no `highway=service`",
    "D": "through only — service whose component links two or more streets",
}


def variant_mask(arcs: pd.DataFrame, variant: str) -> np.ndarray:
    """True where an arc is kept under the variant. Non-service arcs are never touched."""
    if variant not in KNOWN_VARIANTS:
        raise ValueError(
            f"unknown service scope variant {variant!r}; expected one of {KNOWN_VARIANTS}"
        )

    is_service = (arcs["highway_class"] == "service").to_numpy()
    if variant == "A":
        return np.ones(len(arcs), dtype=bool)
    if variant == "C":
        return ~is_service
    if variant == "D":
        if "service_role" not in arcs.columns:
            raise KeyError(
                "variant D needs the `service_role` column — run `make stage2` first"
            )
        role = arcs["service_role"].fillna("").to_numpy()
        return ~is_service | (role == "through")

    subtype = arcs["service_type"].fillna("").to_numpy()
    street_like = np.isin(subtype, list(C.SERVICE_STREET_TYPES))
    return ~is_service | street_like


def apply_variant(arcs: pd.DataFrame, variant: str) -> pd.DataFrame:
    """The arc table as it would stand under one service scope.

    Dropped arcs are marked excluded with a reason rather than deleted
    (CLAUDE.md rule 4), and the strongly-connected components are relabelled,
    because removing service roads changes which streets remain reachable.
    Subtracting service km from the headline would overstate what the variant
    saves; this does not.
    """
    keep = variant_mask(arcs, variant)
    frame = arcs.copy()
    dropped = ~keep & ~frame["excluded"].to_numpy()
    frame.loc[dropped, "excluded"] = True
    frame.loc[dropped, "exclusion_reason"] = "service_scope_variant"

    included = frame[~frame["excluded"]]
    labels = K.label_components(
        list(zip(included["arc_id"], included["from_node"], included["to_node"]))
    )
    frame["scc_id"] = frame["arc_id"].map(labels).fillna(-1).astype("int64")
    frame["in_largest_scc"] = frame["scc_id"] == 0
    return frame


def evaluate(arcs: pd.DataFrame, variant: str, parsed=None) -> dict:
    """Required traversal km, included arcs and |V(L)| under one service scope."""
    from . import turngraph

    frame = apply_variant(arcs, variant)
    dropped = (frame["exclusion_reason"] == "service_scope_variant").to_numpy()
    included = frame[~frame["excluded"]]
    routable = included[included["in_largest_scc"]]

    result = {
        "variant": variant,
        "label": VARIANT_LABELS[variant],
        "included_arc_count": int(len(included)),
        "routable_arc_count": int(len(routable)),
        "included_centerline_km": float(
            included.drop_duplicates(subset=["way_id", "seg_index"])["length_m"].sum() / 1000.0
        ),
        "required_traversal_km": N.required_traversal_km(included),
        "required_traversal_km_routable": N.required_traversal_km(routable),
        "service_arcs_dropped": int(dropped.sum()),
    }
    if parsed is not None:
        result["l_nodes"] = turngraph.build_turn_graph(frame, parsed).n_nodes
    return result


def compare(arcs: pd.DataFrame, parsed=None) -> list[dict]:
    """All three variants, each with its delta from variant A."""
    rows = [evaluate(arcs, variant, parsed) for variant in VARIANTS]
    baseline = rows[0]
    for row in rows:
        row["delta_required_km"] = row["required_traversal_km"] - baseline["required_traversal_km"]
        row["delta_included_arcs"] = row["included_arc_count"] - baseline["included_arc_count"]
        if "l_nodes" in row:
            row["delta_l_nodes"] = row["l_nodes"] - baseline["l_nodes"]
    return rows
