"""Stage 2 item 0 — classify `highway=service` by connectivity, not by subtag.

SPEC §2.1 leaves the service question open and Stage 0b closed the tag route:
92.2% of service arcs carry no `service=*` value, so the tag cannot decide
anything for the bulk of 2,193 km.  What the tag cannot say, the graph can.

Collapse the service-only arcs into undirected components, then ask each
component how many *distinct* non-service nodes it touches:

===========  =======  =============================================
role         touches  meaning
===========  =======  =============================================
``through``  >= 2     enterable by one street, leavable by another —
                      functionally a street
``spur``     1        a dead-end tree: driveway, yard, parking aisle
``orphan``   0        not reachable from the street network at all
===========  =======  =============================================

**Measurement only.**  Nothing here changes a default and nothing is excluded:
variant A remains what the pipeline builds.  The column exists so that Stage 4
can make the scope decision in hours instead of kilometres.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

ROLES: tuple[str, ...] = ("through", "spur", "orphan")

#: Non-service arcs carry no role at all — the column answers a question that is
#: only asked about service roads.
NOT_SERVICE = ""


class _Union:
    """Union-find with path halving.  Deterministic: it never consults order."""

    __slots__ = ("_parent", "_rank")

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}

    def find(self, node: int) -> int:
        parent = self._parent
        if node not in parent:
            parent[node] = node
            self._rank[node] = 0
            return node
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # Union by rank, tie-broken on the smaller id, so the representative a
        # component ends up with does not depend on the row order it arrived in.
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        elif self._rank[ra] == self._rank[rb]:
            if rb < ra:
                ra, rb = rb, ra
            self._rank[ra] += 1
        self._parent[rb] = ra


def classify(arcs: pd.DataFrame) -> pd.Series:
    """`service_role` for every row of the arc table.

    Non-service arcs get ``""``.  Excluded arcs are invisible on *both* sides of
    the test: they are not part of a service component, and they are not doors
    onto the street network either.  A gated yard reached only through a locked
    barrier is an orphan, not a through route — counting it otherwise moves
    45 km out of `orphan` on evidence the camera car cannot drive.
    """
    is_service = (arcs["highway_class"] == "service").to_numpy()
    included = ~arcs["excluded"].to_numpy(dtype=bool)

    service_rows = is_service & included
    from_node = arcs["from_node"].to_numpy(dtype="int64")
    to_node = arcs["to_node"].to_numpy(dtype="int64")

    union = _Union()
    for tail, head in zip(from_node[service_rows], to_node[service_rows]):
        union.union(int(tail), int(head))

    street_rows = (~is_service) & included
    street_nodes = set(from_node[street_rows].tolist())
    street_nodes.update(to_node[street_rows].tolist())

    touches: dict[int, set[int]] = {}
    service_nodes = set(from_node[service_rows].tolist())
    service_nodes.update(to_node[service_rows].tolist())
    for node in sorted(service_nodes & street_nodes):
        touches.setdefault(union.find(node), set()).add(node)

    role = np.full(len(arcs), NOT_SERVICE, dtype=object)
    for index in np.flatnonzero(service_rows):
        count = len(touches.get(union.find(int(from_node[index])), ()))
        role[index] = (
            "through"
            if count >= C.SERVICE_ROLE_THROUGH_MIN_TOUCHES
            else "spur"
            if count == 1
            else "orphan"
        )
    # An excluded service arc is still a service arc; it just took no part in the
    # component analysis.  Saying so beats leaving a blank that reads as
    # "not a service road" (CLAUDE.md rule 4).
    role[is_service & ~included] = "excluded"
    return pd.Series(role, index=arcs.index, name="service_role", dtype=object)


def summarise(arcs: pd.DataFrame, role: pd.Series | None = None) -> dict:
    """Centreline km per role, for `all service` and for `untagged service`.

    Counted on pair representatives only — one physical street piece, not two
    directed arcs — which is what makes it comparable with the Stage 0b service
    total of 2,193.3 km.
    """
    role = classify(arcs) if role is None else role
    representative = arcs["is_pair_representative"].to_numpy(dtype=bool)
    length_km = arcs["length_m"].to_numpy(dtype="float64") / 1000.0
    service = (arcs["highway_class"] == "service").to_numpy()
    included = ~arcs["excluded"].to_numpy(dtype=bool)
    untagged = (arcs["service_type"].fillna("") == "untagged").to_numpy()

    out: dict = {}
    for label, subset in (
        ("all_service", service & included),
        ("untagged_service", service & included & untagged),
    ):
        rows = []
        total = float(length_km[subset & representative].sum())
        for name in ROLES:
            mask = subset & representative & (role.to_numpy() == name)
            km = float(length_km[mask].sum())
            rows.append(
                {
                    "service_role": name,
                    "centerline_km": km,
                    "share": (km / total) if total else 0.0,
                    "arc_count": int((subset & (role.to_numpy() == name)).sum()),
                }
            )
        out[label] = {"rows": rows, "centerline_km": total}
    return out


#: The reference measurement the stage brief supplies, km.  The gate reconciles
#: `summarise` against it to 1 km per bucket; a drift means the connectivity rule
#: changed meaning, which is exactly the thing that must not happen silently.
REFERENCE_KM: dict[str, dict[str, float]] = {
    "all_service": {"through": 1237.2, "spur": 888.6, "orphan": 67.5, "total": 2193.3},
    "untagged_service": {"through": 1150.4, "spur": 810.7, "orphan": 63.1, "total": 2024.1},
}
