"""Stage 3 item 2.3 — Euler circuit extraction (Hierholzer).

The min-cost flow leaves a balanced, connected multigraph over `L*`.  Hierholzer
turns that into a single closed walk using every copy of every edge exactly once,
in linear time.

The walk alternates by construction — `a_in → a_out → b_in → b_out → …` — because
the only edges out of an `_in` node price a traversal and the only edges out of an
`_out` node are manoeuvres.  So the sequence of `_in` nodes visited *is* the
sequence of arcs driven, which is the tour, and no separate bookkeeping is needed
to recover it.
"""

from __future__ import annotations

import numpy as np

from .lstar import LStar


def circuit(star: LStar, x: np.ndarray) -> np.ndarray:
    """A closed walk over `L*` using edge `e` exactly `x[e]` times.

    Returns the node sequence, open (the closing step back to the first node is
    implied, which is what `tourcheck.check_closed` verifies independently).
    """
    x = np.asarray(x, dtype="int64")
    if x.min() < 0:
        raise ValueError("negative edge multiplicity")
    total = int(x.sum())
    if total == 0:
        raise ValueError("the augmented multigraph has no edges")
    assert_balanced(star, x)

    used = np.flatnonzero(x > 0)
    order = np.argsort(star.tail[used], kind="stable")
    edges = used[order]
    tails = star.tail[edges]
    heads = star.head[edges]

    start_of = np.searchsorted(tails, np.arange(star.n_nodes + 1))
    pointer = start_of[:-1].copy()
    remaining = x[edges].copy()

    start = int(tails[0])
    stack = [start]
    walk: list[int] = []
    steps = 0
    while stack:
        node = stack[-1]
        index = pointer[node]
        stop = start_of[node + 1]
        while index < stop and remaining[index] == 0:
            index += 1
        pointer[node] = index
        if index >= stop:
            walk.append(stack.pop())
            continue
        remaining[index] -= 1
        steps += 1
        stack.append(int(heads[index]))

    if steps != total:
        raise RuntimeError(
            f"Hierholzer consumed {steps:,} of {total:,} edge copies — the "
            "augmented multigraph is not connected, so it has no single circuit"
        )
    walk.reverse()
    if walk[0] != walk[-1]:
        raise RuntimeError(
            f"the walk runs {walk[0]} … {walk[-1]} and does not close; a balanced "
            "multigraph cannot do this, so the balance check above is wrong"
        )
    return np.asarray(walk[:-1], dtype="int64")  # drop the repeated start node


def assert_balanced(star: LStar, x: np.ndarray) -> None:
    """Every node must be left exactly as often as it is entered.

    Hierholzer on an unbalanced multigraph does not fail — it quietly returns an
    open walk, which looks like a tour and is not one.  Checking first is the
    difference between a wrong answer and an exception.
    """
    x = np.asarray(x, dtype="int64")
    balance = np.zeros(star.n_nodes, dtype="int64")
    np.add.at(balance, star.head, x)
    np.subtract.at(balance, star.tail, x)
    bad = np.flatnonzero(balance != 0)
    if bad.size:
        raise ValueError(
            f"{bad.size} nodes are unbalanced (first: node {bad[0]}, "
            f"in − out = {balance[bad[0]]}); this is not a circulation"
        )


def arcs_of(star: LStar, walk: np.ndarray) -> np.ndarray:
    """The arcs driven, in order: every `_in` node the walk passes through."""
    walk = np.asarray(walk, dtype="int64")
    return walk[walk < star.n_arc_nodes]


def tour(star: LStar, x: np.ndarray) -> np.ndarray:
    """The circuit as a sequence of L-node indices — the Stage 3 tour format."""
    return arcs_of(star, circuit(star, x))
