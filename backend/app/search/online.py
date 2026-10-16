"""Online search in unknown / dynamic environments.

Two classic online agents are implemented, plus the plan-validation helper the
Disaster Response Commander uses for dynamic replanning:

* ``repeated_astar`` - plans with A* under the *free-space assumption* (unknown
  cells are assumed passable), executes the plan one step at a time, senses the
  surroundings after every move and replans as soon as the remaining plan is
  contradicted by what it has observed. This is exactly the replanning loop the
  commander runs on the live simulation.
* ``lrta_star`` - Learning Real-Time A* (Korf, 1990; AIMA Fig. 4.24). The agent
  never plans a full path: it looks one step ahead, updates the learned cost-to-
  goal estimate H(s) <- min_a [c(s, a, s') + H(s')], and moves to the most
  promising neighbour. H is initialised with the Manhattan heuristic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.environment.grid import Grid
from app.environment.mobility import MobilityProfile
from app.models.entities import CellType, Pos
from app.search.astar import astar
from app.search.base import GridSearchProblem
from app.search.heuristics import manhattan


def first_blocked_index(path: list[Pos], grid: Grid, profile: MobilityProfile) -> int | None:
    """Index of the first cell of `path` (after the start) that `profile` cannot
    enter on `grid`, or None if the whole path is still traversable."""
    for i, cell in enumerate(path[1:], start=1):
        if not profile.passable(grid.type_at(cell)):
            return i
    return None


def path_cost_on(grid: Grid, path: list[Pos], profile: MobilityProfile) -> float | None:
    total = 0.0
    for cell in path[1:]:
        c = profile.step_cost(grid, cell)
        if c is None:
            return None
        total += c
    return total


@dataclass
class OnlineSearchResult:
    algorithm: str
    start: Pos
    goal: Pos
    found: bool
    trajectory: list[Pos] = field(default_factory=list)
    cost: float = 0.0
    replans: int = 0
    nodes_expanded: int = 0
    heuristic_updates: int = 0
    cells_revealed: list[Pos] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    time_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "start": list(self.start),
            "goal": list(self.goal),
            "found": self.found,
            "trajectory": [list(p) for p in self.trajectory],
            "steps": max(0, len(self.trajectory) - 1),
            "cost": round(self.cost, 3),
            "replans": self.replans,
            "nodes_expanded": self.nodes_expanded,
            "heuristic_updates": self.heuristic_updates,
            "cells_revealed": [list(p) for p in self.cells_revealed],
            "events": self.events,
            "time_ms": round(self.time_ms, 3),
        }


class _BeliefMap:
    """What an online agent knows: unknown cells are assumed to be open road."""

    def __init__(self, truth: Grid, sensor_radius: int):
        self.truth = truth
        self.radius = sensor_radius
        self.grid = Grid([[CellType.ROAD] * truth.cols for _ in range(truth.rows)])
        self.known: set[Pos] = set()

    def sense(self, at: Pos) -> list[Pos]:
        """Reveal true terrain within the sensor radius; return cells that
        turned out different from the belief."""
        surprises: list[Pos] = []
        r0, c0 = at
        for r in range(r0 - self.radius, r0 + self.radius + 1):
            for c in range(c0 - self.radius, c0 + self.radius + 1):
                p = (r, c)
                if not self.truth.in_bounds(p) or abs(r - r0) + abs(c - c0) > self.radius:
                    continue
                if p in self.known:
                    continue
                self.known.add(p)
                true_type = self.truth.type_at(p)
                if self.grid.type_at(p) != true_type:
                    self.grid.set_type(p, true_type, recompute=False)
                    surprises.append(p)
        if surprises:
            self.grid.recompute_danger()
        return surprises


def repeated_astar(
    truth: Grid,
    start: Pos,
    goal: Pos,
    profile: MobilityProfile,
    sensor_radius: int = 1,
    max_steps: int = 2000,
) -> OnlineSearchResult:
    t0 = time.perf_counter()
    out = OnlineSearchResult("REPEATED_ASTAR", start, goal, found=False, trajectory=[start])
    belief = _BeliefMap(truth, sensor_radius)
    belief.sense(start)
    pos = start
    plan: list[Pos] = []

    def replan(reason: str | None) -> bool:
        nonlocal plan
        res = astar(GridSearchProblem(belief.grid, pos, goal, profile))
        out.nodes_expanded += res.nodes_expanded
        if reason is not None:
            out.replans += 1
            out.events.append({"step": len(out.trajectory) - 1, "pos": list(pos), "message": reason})
        plan = res.path if res.found else []
        return res.found

    if not replan(None):
        out.time_ms = (time.perf_counter() - t0) * 1000
        return out

    while pos != goal and len(out.trajectory) <= max_steps:
        nxt = plan[1]
        step = profile.step_cost(truth, nxt)
        if step is None:  # sensor radius 0: we only learn by bumping into it
            belief.known.add(nxt)
            belief.grid.set_type(nxt, truth.type_at(nxt))
            if not replan(f"Bumped into {truth.type_at(nxt).value} at {nxt}; replanning"):
                break
            continue
        pos = nxt
        out.cost += step
        out.trajectory.append(pos)
        plan = plan[1:]
        surprises = belief.sense(pos)
        if surprises and pos != goal:
            blocked = first_blocked_index(plan, belief.grid, profile)
            if blocked is not None:
                cell = plan[blocked]
                if not replan(f"Discovered {truth.type_at(cell).value} at {cell} on the planned route"):
                    break

    out.found = pos == goal
    out.cells_revealed = sorted(belief.known)
    out.time_ms = (time.perf_counter() - t0) * 1000
    return out


def lrta_star(
    truth: Grid,
    start: Pos,
    goal: Pos,
    profile: MobilityProfile,
    sensor_radius: int = 1,
    max_steps: int = 3000,
) -> OnlineSearchResult:
    t0 = time.perf_counter()
    out = OnlineSearchResult("LRTA*", start, goal, found=False, trajectory=[start])
    belief = _BeliefMap(truth, sensor_radius)
    H: dict[Pos, float] = {}

    def h_of(p: Pos) -> float:
        return H.get(p, manhattan(p, goal))

    pos = start
    belief.sense(pos)
    while pos != goal and len(out.trajectory) <= max_steps:
        options: list[tuple[float, Pos, float]] = []
        for nxt in belief.grid.neighbors4(pos):
            c = profile.step_cost(belief.grid, nxt)
            if c is not None:
                options.append((c + h_of(nxt), nxt, c))
        out.nodes_expanded += 1
        if not options:
            out.events.append({"step": len(out.trajectory) - 1, "pos": list(pos), "message": "Dead end: no moves"})
            break
        best_f, best_next, _ = min(options)
        if best_f != h_of(pos):
            out.heuristic_updates += 1
        H[pos] = best_f  # learning step
        true_cost = profile.step_cost(truth, best_next)
        if true_cost is None:  # only possible with sensor radius 0
            belief.known.add(best_next)
            belief.grid.set_type(best_next, truth.type_at(best_next))
            continue
        pos = best_next
        out.cost += true_cost
        out.trajectory.append(pos)
        belief.sense(pos)

    out.found = pos == goal
    if not out.found and len(out.trajectory) > max_steps:
        out.events.append({"step": max_steps, "pos": list(pos), "message": "Step limit reached"})
    out.cells_revealed = sorted(belief.known)
    out.time_ms = (time.perf_counter() - t0) * 1000
    return out
