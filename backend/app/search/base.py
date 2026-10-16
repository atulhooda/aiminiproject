"""State-space search problem on the grid and the common search result type.

Formulation (route-finding sub-problem of the disaster state space):
  * State       : a cell (row, col) occupied by the moving unit
  * Initial     : the unit's current cell
  * Actions     : move N / E / S / W into a cell passable for the unit's profile
  * Transition  : the neighbouring cell
  * Goal test   : state == goal cell
  * Step cost   : terrain cost of the entered cell + DANGER_WEIGHT * danger
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator

from app.environment.grid import Grid
from app.environment.mobility import MobilityProfile
from app.models.entities import Pos

Heuristic = Callable[[Pos, Pos], float]


class GridSearchProblem:
    def __init__(
        self,
        grid: Grid,
        start: Pos,
        goal: Pos,
        profile: MobilityProfile,
        danger_aware: bool = True,
    ):
        if not grid.in_bounds(start) or not grid.in_bounds(goal):
            raise ValueError("start and goal must lie inside the grid")
        self.grid = grid
        self.start = start
        self.goal = goal
        self.profile = profile
        self.danger_aware = danger_aware

    def is_goal(self, state: Pos) -> bool:
        return state == self.goal

    def successors(self, state: Pos) -> Iterator[tuple[Pos, float]]:
        """Yield (next_state, step_cost) for every legal move from `state`."""
        for nxt in self.grid.neighbors4(state):
            cost = self.profile.step_cost(self.grid, nxt, self.danger_aware)
            if cost is not None:
                yield nxt, cost

    def step_cost(self, to: Pos) -> float | None:
        return self.profile.step_cost(self.grid, to, self.danger_aware)

    def path_cost(self, path: list[Pos]) -> float | None:
        """Cost of a full path (None if any step is illegal)."""
        total = 0.0
        for a, b in zip(path, path[1:]):
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                return None
            c = self.step_cost(b)
            if c is None:
                return None
            total += c
        return total


@dataclass
class SearchResult:
    algorithm: str
    start: Pos
    goal: Pos
    found: bool
    path: list[Pos] = field(default_factory=list)
    cost: float = 0.0
    nodes_expanded: int = 0
    nodes_generated: int = 0
    max_frontier: int = 0
    explored: list[Pos] = field(default_factory=list)  # in expansion order
    frontier: list[Pos] = field(default_factory=list)  # frontier when search stopped
    time_ms: float = 0.0
    heuristic_name: str | None = None
    heuristic_start: float | None = None  # h(start)

    @property
    def steps(self) -> int:
        return max(0, len(self.path) - 1)

    def summary(self) -> str:
        if not self.found:
            return (
                f"{self.algorithm}: no path {self.start}->{self.goal} "
                f"({self.nodes_expanded} nodes expanded, {self.time_ms:.2f} ms)"
            )
        return (
            f"{self.algorithm}: path {self.steps} steps, cost {self.cost:.1f}, "
            f"{self.nodes_expanded} nodes expanded, {self.time_ms:.2f} ms"
        )

    def to_dict(self, include_trace: bool = True) -> dict:
        data = {
            "algorithm": self.algorithm,
            "start": list(self.start),
            "goal": list(self.goal),
            "found": self.found,
            "path": [list(p) for p in self.path],
            "cost": round(self.cost, 3),
            "steps": self.steps,
            "nodes_expanded": self.nodes_expanded,
            "nodes_generated": self.nodes_generated,
            "max_frontier": self.max_frontier,
            "time_ms": round(self.time_ms, 4),
            "heuristic": self.heuristic_name,
            "heuristic_start": None if self.heuristic_start is None else round(self.heuristic_start, 3),
        }
        if include_trace:
            data["explored"] = [list(p) for p in self.explored]
            data["frontier"] = [list(p) for p in self.frontier]
        return data


def reconstruct_path(parents: dict[Pos, Pos | None], goal: Pos) -> list[Pos]:
    path: list[Pos] = []
    node: Pos | None = goal
    while node is not None:
        path.append(node)
        node = parents[node]
    path.reverse()
    return path
