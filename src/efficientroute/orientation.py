"""Stage 3 item 2.1 — choose a direction for every narrow two-way pair.

SPEC §2.1 row 3: a narrow two-way street carries a requirement of **one**
traversal, satisfiable from either direction.  SPEC §3.4 calls this a
*generalised* coverage requirement, and it is what puts the problem outside the
polynomial class.  Fixing a direction for each pair removes the generalisation
and leaves an ordinary Directed Chinese Postman — solvable exactly — at the cost
of making the answer an **upper** bound rather than a lower one.

**Where the imbalance lives.**  It is tempting to minimise imbalance on `L*`, but
imbalance there is orientation-invariant: every required edge `a_in → a_out`
creates exactly one unit of source and one of sink, and a pair contributes
exactly one required edge whichever way it is turned, so `Σ|supply| = 2·Σ lower`
no matter what this module decides.  The choice only moves *where* the sources
and sinks are.  The quantity that actually responds to orientation is imbalance
at the **base network's junctions** — a junction that required traversals enter
more often than they leave needs deadhead to make up the difference — which is
what SPEC §4 Stage A means and what this module minimises.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd


@dataclasses.dataclass(frozen=True)
class Orientation:
    """Per-L-node lower bounds, plus how the choice was arrived at."""

    lower: np.ndarray
    imbalance_naive: int
    imbalance_after_greedy: int
    imbalance_after: int
    flips_greedy: int
    flips_local_search: int
    passes: int
    pair_count: int
    #: Pairs whose two directions share a junction at both ends — flipping one
    #: changes nothing, so the heuristic cannot help them.
    degenerate_pairs: int
    #: Pairs with only one drivable direction: the heuristic had no choice.
    forced_pairs: int
    #: Pairs with neither direction inside the tour's component.  Their coverage
    #: requirement cannot be met by any closed tour and is reported, not met.
    unreachable_pairs: int

    def to_dict(self) -> dict:
        return {
            "imbalance_naive": int(self.imbalance_naive),
            "imbalance_after_greedy": int(self.imbalance_after_greedy),
            "imbalance_after": int(self.imbalance_after),
            "imbalance_reduction": int(self.imbalance_naive - self.imbalance_after),
            "flips_greedy": int(self.flips_greedy),
            "flips_local_search": int(self.flips_local_search),
            "local_search_passes": int(self.passes),
            "pair_count": int(self.pair_count),
            "degenerate_pairs": int(self.degenerate_pairs),
            "forced_pairs": int(self.forced_pairs),
            "unreachable_pairs": int(self.unreachable_pairs),
        }


def _pairs(index: pd.DataFrame) -> list[tuple[int, int]]:
    """(representative row, twin row) for every narrow pair, in a fixed order.

    Only primary variants take part: a restriction clone is an alternative
    routing context for the same street, not a second street.
    """
    primary = index["variant"].to_numpy() == 0
    pair_id = index["pair_id"].fillna("").to_numpy()
    requirement = index["pair_requirement"].to_numpy()
    representative = index["is_pair_representative"].to_numpy(dtype=bool)

    members: dict[str, dict[str, int]] = {}
    for row in np.flatnonzero(primary & (requirement > 0) & (pair_id != "")):
        slot = "rep" if representative[row] else "twin"
        members.setdefault(pair_id[row], {})[slot] = int(row)

    return [
        (m["rep"], m["twin"])
        for _key, m in sorted(members.items())
        if "rep" in m and "twin" in m
    ]


def base_lower_bounds(index: pd.DataFrame, keep: np.ndarray | None = None) -> np.ndarray:
    """Lower bounds before any pair is oriented: `min_passes`, pairs at zero.

    Restriction clones take a lower bound of zero and the requirement sits on the
    primary variant.  That is marginally conservative — it denies the required
    pass the clone's routing context — and applies to 14 L-nodes out of 166,693.
    """
    lower = np.zeros(len(index), dtype="int64")
    primary = index["variant"].to_numpy() == 0
    solo = primary & (index["pair_requirement"].to_numpy() == 0)
    if keep is not None:
        solo &= np.asarray(keep, dtype=bool)
    lower[solo] = index["min_passes"].to_numpy(dtype="int64")[solo]
    return lower


def orient(
    index: pd.DataFrame, keep: np.ndarray | None = None, max_passes: int = 20
) -> Orientation:
    """Greedy orientation, then local search on junction imbalance.

    `keep` marks the L-nodes a closed tour can reach.  A direction outside it is
    not a candidate: choosing one would leave the street uncovered while the
    lower bound quietly reported that it had been dealt with.  Where only one
    direction is drivable the choice is forced; where neither is, the pair is
    outside the tour's scope and is counted rather than silently dropped.
    """
    lower = base_lower_bounds(index, keep)
    reachable = np.ones(len(index), dtype=bool) if keep is None else np.asarray(keep, dtype=bool)
    pairs = _pairs(index)
    from_node = index["from_node"].to_numpy(dtype="int64")
    to_node = index["to_node"].to_numpy(dtype="int64")

    junctions = pd.unique(np.concatenate([from_node, to_node]))
    junctions.sort()
    slot = {int(node): i for i, node in enumerate(junctions)}
    tail = np.array([slot[int(n)] for n in from_node], dtype="int64")
    head = np.array([slot[int(n)] for n in to_node], dtype="int64")

    imbalance = np.zeros(len(junctions), dtype="int64")
    np.add.at(imbalance, tail, lower)
    np.subtract.at(imbalance, head, lower)

    degenerate = sum(1 for rep, _twin in pairs if tail[rep] == head[rep])

    # ---- the do-nothing orientation, to measure the heuristic against
    naive = imbalance.copy()
    for rep, twin in pairs:
        row = rep if reachable[rep] else twin
        if reachable[row]:
            _apply(naive, tail[row], head[row])
    imbalance_naive = int(np.abs(naive).sum())

    # ---- greedy: take each pair once, in pair_id order, best direction first
    flips_greedy = 0
    forced_pairs = 0
    unreachable_pairs = 0
    choosable: list[tuple[int, int]] = []
    for rep, twin in pairs:
        options = [row for row in (rep, twin) if reachable[row]]
        if not options:
            unreachable_pairs += 1
            continue
        if len(options) == 1:
            forced_pairs += 1
            row = options[0]
            lower[row] = 1
            _apply(imbalance, tail[row], head[row])
            flips_greedy += int(row == twin)
            continue
        choosable.append((rep, twin))
        if _delta(imbalance, tail[twin], head[twin]) < _delta(imbalance, tail[rep], head[rep]):
            lower[twin] = 1
            _apply(imbalance, tail[twin], head[twin])
            flips_greedy += 1
        else:
            lower[rep] = 1
            _apply(imbalance, tail[rep], head[rep])
    after_greedy = int(np.abs(imbalance).sum())

    # ---- local search: flip whichever pairs still reduce the total
    flips_local = 0
    passes = 0
    for passes in range(1, max_passes + 1):
        improved = 0
        for rep, twin in choosable:
            chosen, other = (rep, twin) if lower[rep] else (twin, rep)
            gain = _flip_gain(imbalance, tail[chosen], head[chosen],
                              tail[other], head[other])
            if gain < 0:
                _unapply(imbalance, tail[chosen], head[chosen])
                _apply(imbalance, tail[other], head[other])
                lower[chosen], lower[other] = 0, 1
                improved += 1
        flips_local += improved
        if improved == 0:
            break

    return Orientation(
        lower=lower,
        imbalance_naive=imbalance_naive,
        imbalance_after_greedy=after_greedy,
        imbalance_after=int(np.abs(imbalance).sum()),
        flips_greedy=flips_greedy,
        flips_local_search=flips_local,
        passes=passes,
        pair_count=len(pairs),
        degenerate_pairs=degenerate,
        forced_pairs=forced_pairs,
        unreachable_pairs=unreachable_pairs,
    )


def _delta(imbalance: np.ndarray, u: int, v: int) -> int:
    """Change in Σ|imbalance| from requiring one traversal u → v."""
    if u == v:
        return 0
    return (abs(imbalance[u] + 1) - abs(imbalance[u])
            + abs(imbalance[v] - 1) - abs(imbalance[v]))


def _apply(imbalance: np.ndarray, u: int, v: int) -> None:
    imbalance[u] += 1
    imbalance[v] -= 1


def _unapply(imbalance: np.ndarray, u: int, v: int) -> None:
    imbalance[u] -= 1
    imbalance[v] += 1


def _flip_gain(imbalance, cu, cv, ou, ov) -> int:
    """Change in Σ|imbalance| from dropping the chosen direction for the other."""
    before = _abs_at(imbalance, (cu, cv, ou, ov))
    _unapply(imbalance, cu, cv)
    _apply(imbalance, ou, ov)
    after = _abs_at(imbalance, (cu, cv, ou, ov))
    _unapply(imbalance, ou, ov)
    _apply(imbalance, cu, cv)
    return after - before


def _abs_at(imbalance: np.ndarray, nodes) -> int:
    return sum(abs(int(imbalance[n])) for n in set(nodes))
