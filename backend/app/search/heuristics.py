"""Heuristic functions h(n) for informed search on a 4-connected grid.

Because every legal step costs at least MIN_STEP_COST (= 1) and a unit moves one
cell per step, the Manhattan distance never overestimates the true remaining
cost: it is admissible, and since |h(n) - h(n')| <= 1 <= c(n, n') it is also
consistent. Hence A* with Manhattan returns optimal paths.
"""

from __future__ import annotations

import math

from app.environment.mobility import MIN_STEP_COST
from app.models.entities import Pos
from app.search.base import Heuristic


def manhattan(a: Pos, b: Pos) -> float:
    return MIN_STEP_COST * (abs(a[0] - b[0]) + abs(a[1] - b[1]))


def euclidean(a: Pos, b: Pos) -> float:
    return MIN_STEP_COST * math.hypot(a[0] - b[0], a[1] - b[1])


def zero(a: Pos, b: Pos) -> float:  # noqa: ARG001 - signature must match Heuristic
    """h = 0 turns A* into uniform-cost search (Dijkstra)."""
    return 0.0


HEURISTICS: dict[str, Heuristic] = {
    "manhattan": manhattan,
    "euclidean": euclidean,
    "zero": zero,
}


def get_heuristic(name: str) -> Heuristic:
    try:
        return HEURISTICS[name]
    except KeyError as exc:
        raise ValueError(f"unknown heuristic '{name}'; choose one of {sorted(HEURISTICS)}") from exc
