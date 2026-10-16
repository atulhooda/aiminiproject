"""Algorithm Lab: run BFS, Greedy Best-First and A* side by side on the same map.

Every number returned here is measured from a real run; execution time is the
median of several repetitions to smooth out timer noise.
"""

from __future__ import annotations

import random
import statistics

from app.environment.grid import Grid
from app.environment.mobility import GROUND_VEHICLE, PROFILES, MobilityProfile
from app.environment.scenarios import build_scenario
from app.environment.world import World
from app.models.entities import Pos
from app.search import ALGORITHM_LABELS, ALGORITHMS, GridSearchProblem, run_search
from app.search.astar import astar
from app.search.heuristics import HEURISTICS, get_heuristic
from app.search.online import lrta_star, repeated_astar

TIMING_REPEATS = 5


class LabError(ValueError):
    pass


def profile_by_name(name: str) -> MobilityProfile:
    try:
        return PROFILES[name.upper()]
    except KeyError as exc:
        raise LabError(f"unknown mobility profile '{name}'; choose one of {sorted(PROFILES)}") from exc


def _check_endpoints(grid: Grid, start: Pos, goal: Pos, profile: MobilityProfile) -> None:
    for name, p in (("start", start), ("goal", goal)):
        if not grid.in_bounds(p):
            raise LabError(f"{name} {p} is outside the {grid.rows}x{grid.cols} grid")
    if not profile.passable(grid.type_at(goal)):
        raise LabError(f"goal {goal} is {grid.type_at(goal).value}, which a {profile.label} cannot enter")
    if not profile.passable(grid.type_at(start)):
        raise LabError(f"start {start} is {grid.type_at(start).value}, which a {profile.label} cannot occupy")


def suggested_endpoints(world: World, grid: Grid) -> tuple[Pos, Pos]:
    """A long, interesting query: first ambulance -> farthest reachable victim."""
    start = next(iter(world.ambulances.values())).pos
    best, best_d = None, -1
    for v in world.victims.values():
        res = astar(GridSearchProblem(grid, start, v.pos, GROUND_VEHICLE))
        if res.found and res.steps > best_d:
            best, best_d = v.pos, res.steps
    if best is None:
        best = next(iter(world.hospitals.values())).pos
    return start, best


def lab_map(scenario: str, seed: int | None = None, grid: Grid | None = None, world: World | None = None) -> dict:
    if world is None:
        world = build_scenario(scenario, seed=seed).world
    grid = grid or world.grid
    start, goal = suggested_endpoints(world, grid)
    return {
        "rows": grid.rows,
        "cols": grid.cols,
        "cells": grid.to_codes(),
        "danger": grid.danger_matrix(),
        "suggested_start": list(start),
        "suggested_goal": list(goal),
        "victims": [{"id": v.id, "pos": list(v.pos)} for v in world.victims.values() if v.reported],
        "hospitals": [{"id": h.id, "pos": list(h.pos)} for h in world.hospitals.values()],
        "units": [{"id": u.id, "pos": list(u.pos)} for u in world.units().values()],
    }


def compare(
    grid: Grid,
    start: Pos,
    goal: Pos,
    profile_name: str = "GROUND_VEHICLE",
    danger_aware: bool = True,
    heuristic: str = "manhattan",
) -> dict:
    profile = profile_by_name(profile_name)
    get_heuristic(heuristic)
    _check_endpoints(grid, start, goal, profile)
    problem = GridSearchProblem(grid, start, goal, profile, danger_aware=danger_aware)

    results = []
    for algo in ALGORITHMS:
        runs = [run_search(algo, problem, heuristic) for _ in range(TIMING_REPEATS)]
        first = runs[0]
        data = first.to_dict(include_trace=True)
        data["time_ms"] = round(statistics.median(r.time_ms for r in runs), 4)
        data["label"] = ALGORITHM_LABELS[algo]
        results.append(data)

    # Uniform-cost search (A* with h = 0) provides the certified optimum.
    reference = astar(problem, get_heuristic("zero"), "zero")
    optimal = reference.cost if reference.found else None
    for r in results:
        r["optimal"] = bool(r["found"] and optimal is not None and abs(r["cost"] - optimal) < 1e-6)
        r["cost_ratio"] = round(r["cost"] / optimal, 3) if r["found"] and optimal else None
        r["path_danger"] = round(sum(grid.danger_at(tuple(p)) for p in r["path"]), 2)
    return {
        "start": list(start),
        "goal": list(goal),
        "profile": profile.name,
        "danger_aware": danger_aware,
        "heuristic": heuristic,
        "optimal_cost": None if optimal is None else round(optimal, 3),
        "reference": {"algorithm": "UCS (A* with h=0)", "nodes_expanded": reference.nodes_expanded, "cost": round(reference.cost, 3)},
        "results": results,
        "timing_repeats": TIMING_REPEATS,
    }


def benchmark(
    grid: Grid,
    trials: int = 30,
    seed: int = 1,
    profile_name: str = "GROUND_VEHICLE",
    danger_aware: bool = True,
    heuristic: str = "manhattan",
) -> dict:
    if not 1 <= trials <= 200:
        raise LabError("trials must be between 1 and 200")
    profile = profile_by_name(profile_name)
    rng = random.Random(seed)
    cells = [p for p in grid.positions() if profile.passable(grid.type_at(p))]
    if len(cells) < 2:
        raise LabError("not enough passable cells for a benchmark")

    queries: list[tuple[Pos, Pos, float]] = []
    attempts = 0
    while len(queries) < trials and attempts < trials * 20:
        attempts += 1
        s, g = rng.sample(cells, 2)
        ref = astar(GridSearchProblem(grid, s, g, profile, danger_aware), get_heuristic("zero"), "zero")
        if ref.found and ref.steps >= 6:
            queries.append((s, g, ref.cost))

    agg = {a: {"nodes": [], "cost_ratio": [], "time": [], "optimal": 0, "steps": [], "frontier": []} for a in ALGORITHMS}
    for s, g, opt in queries:
        problem = GridSearchProblem(grid, s, g, profile, danger_aware)
        for algo in ALGORITHMS:
            res = run_search(algo, problem, heuristic)
            a = agg[algo]
            a["nodes"].append(res.nodes_expanded)
            a["cost_ratio"].append(res.cost / opt if opt else 1.0)
            a["time"].append(res.time_ms)
            a["steps"].append(res.steps)
            a["frontier"].append(res.max_frontier)
            if abs(res.cost - opt) < 1e-6:
                a["optimal"] += 1
    n = len(queries)
    summary = []
    for algo in ALGORITHMS:
        a = agg[algo]
        summary.append(
            {
                "algorithm": algo,
                "label": ALGORITHM_LABELS[algo],
                "avg_nodes_expanded": round(statistics.mean(a["nodes"]), 1) if n else 0,
                "avg_cost_ratio": round(statistics.mean(a["cost_ratio"]), 3) if n else 0,
                "max_cost_ratio": round(max(a["cost_ratio"]), 3) if n else 0,
                "avg_time_ms": round(statistics.mean(a["time"]), 4) if n else 0,
                "avg_steps": round(statistics.mean(a["steps"]), 1) if n else 0,
                "avg_max_frontier": round(statistics.mean(a["frontier"]), 1) if n else 0,
                "optimal_rate": round(a["optimal"] / n, 3) if n else 0,
            }
        )
    return {"trials": n, "seed": seed, "profile": profile.name, "danger_aware": danger_aware, "heuristic": heuristic, "summary": summary}


def online_comparison(grid: Grid, start: Pos, goal: Pos, profile_name: str = "GROUND_VEHICLE", sensor_radius: int = 1) -> dict:
    if not 0 <= sensor_radius <= 5:
        raise LabError("sensor radius must be between 0 and 5")
    profile = profile_by_name(profile_name)
    _check_endpoints(grid, start, goal, profile)
    offline = astar(GridSearchProblem(grid, start, goal, profile))
    rep = repeated_astar(grid, start, goal, profile, sensor_radius=sensor_radius)
    lrta = lrta_star(grid, start, goal, profile, sensor_radius=sensor_radius)
    return {
        "start": list(start),
        "goal": list(goal),
        "sensor_radius": sensor_radius,
        "offline": {
            "algorithm": "A* (full map known)",
            "found": offline.found,
            "trajectory": [list(p) for p in offline.path],
            "steps": offline.steps,
            "cost": round(offline.cost, 3),
            "nodes_expanded": offline.nodes_expanded,
        },
        "repeated_astar": rep.to_dict(),
        "lrta_star": lrta.to_dict(),
    }


def available_heuristics() -> list[str]:
    return sorted(HEURISTICS)
