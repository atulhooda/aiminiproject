"""Tests for BFS, Greedy Best-First, A*, heuristics and online search."""

from __future__ import annotations

import random

import pytest

from helpers import is_valid_path
from app.environment.grid import Grid
from app.models.entities import CellType
from app.environment.mobility import (
    DANGER_WEIGHT,
    FIREFIGHTING_TEAM,
    GROUND_VEHICLE,
    WATER_RESCUE_TEAM,
)
from app.search import ALGORITHMS, GridSearchProblem, run_search
from app.search.astar import astar
from app.search.bfs import bfs
from app.search.greedy_best_first import greedy_best_first
from app.search.heuristics import euclidean, manhattan, zero
from app.search.online import first_blocked_index, lrta_star, path_cost_on, repeated_astar

# Straight road along row 2 passes next to a fire at (3, 4); a safe detour
# exists along row 0.
DANGER_MAP = [
    "..........",
    ".########.",
    "..........",
    "####F#####",
]


def random_grid(rng: random.Random, size: int = 14) -> Grid:
    return Grid.from_strings(["".join(rng.choice("......#F~X") for _ in range(size)) for _ in range(size)])


def test_bfs_returns_fewest_steps_path():
    grid = Grid.from_strings([".....", ".###.", "....."])
    res = bfs(GridSearchProblem(grid, (0, 0), (2, 4), GROUND_VEHICLE, danger_aware=False))
    assert res.found
    assert res.steps == 6
    assert res.path[0] == (0, 0) and res.path[-1] == (2, 4)
    assert is_valid_path(res.path, grid, GROUND_VEHICLE)
    assert res.nodes_expanded == len(res.explored) > 0


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_start_equals_goal(algorithm):
    grid = Grid.from_strings(["...", "...", "..."])
    res = run_search(algorithm, GridSearchProblem(grid, (1, 1), (1, 1), GROUND_VEHICLE))
    assert res.found and res.path == [(1, 1)] and res.cost == 0


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_unreachable_goal_reports_failure(algorithm):
    grid = Grid.from_strings(["..#..", "..#..", "..#.."])
    res = run_search(algorithm, GridSearchProblem(grid, (0, 0), (2, 4), GROUND_VEHICLE))
    assert not res.found
    assert res.path == []
    assert res.nodes_expanded == 6  # the whole left component was explored


def test_astar_uses_danger_aware_costs_and_avoids_fire():
    grid = Grid.from_strings(DANGER_MAP)
    problem = GridSearchProblem(grid, (2, 0), (2, 9), GROUND_VEHICLE)
    a, b, g = astar(problem), bfs(problem), greedy_best_first(problem)
    assert a.found and b.found and g.found
    # BFS and Greedy drive straight past the fire; A* takes the safe detour.
    assert (2, 4) in b.path and (2, 4) in g.path
    assert (2, 4) not in a.path
    assert a.cost == pytest.approx(13.0)
    assert b.cost == pytest.approx(9 + DANGER_WEIGHT * (0.6 + 0.3 + 0.3))
    assert a.cost < b.cost and a.cost < g.cost
    assert b.steps < a.steps  # BFS minimises steps, not cost


def test_without_danger_awareness_astar_takes_the_short_road():
    grid = Grid.from_strings(DANGER_MAP)
    res = astar(GridSearchProblem(grid, (2, 0), (2, 9), GROUND_VEHICLE, danger_aware=False))
    assert res.cost == pytest.approx(9.0) and (2, 4) in res.path


def test_astar_is_optimal_and_dominates_uniform_cost_on_random_maps():
    rng = random.Random(7)
    checked = 0
    for _ in range(60):
        grid = random_grid(rng)
        cells = [p for p in grid.positions() if GROUND_VEHICLE.passable(grid.type_at(p))]
        s, g = rng.sample(cells, 2)
        problem = GridSearchProblem(grid, s, g, GROUND_VEHICLE)
        a = astar(problem)
        ucs = astar(problem, zero, "zero")
        b = bfs(problem)
        gr = greedy_best_first(problem)
        assert a.found == ucs.found == b.found == gr.found
        if not a.found:
            continue
        checked += 1
        assert a.cost == pytest.approx(ucs.cost)
        assert a.nodes_expanded <= ucs.nodes_expanded
        assert b.cost >= a.cost - 1e-9 and gr.cost >= a.cost - 1e-9
        assert b.steps <= a.steps
        for res in (a, b, gr):
            assert is_valid_path(res.path, grid, GROUND_VEHICLE)
            assert problem.path_cost(res.path) == pytest.approx(res.cost)
    assert checked > 20


def test_manhattan_is_admissible_and_consistent():
    rng = random.Random(11)
    grid = random_grid(rng, 12)
    cells = [p for p in grid.positions() if GROUND_VEHICLE.passable(grid.type_at(p))]
    goal = cells[len(cells) // 2]
    for n in rng.sample(cells, 25):
        true = astar(GridSearchProblem(grid, n, goal, GROUND_VEHICLE), zero, "zero")
        if true.found:
            assert manhattan(n, goal) <= true.cost + 1e-9
            assert euclidean(n, goal) <= manhattan(n, goal) + 1e-9
        problem = GridSearchProblem(grid, n, goal, GROUND_VEHICLE)
        for m, step in problem.successors(n):
            assert manhattan(n, goal) <= step + manhattan(m, goal) + 1e-9


def test_search_trace_is_well_formed():
    grid = Grid.from_strings(DANGER_MAP)
    for algorithm in ("GREEDY", "ASTAR"):
        res = run_search(algorithm, GridSearchProblem(grid, (2, 0), (2, 9), GROUND_VEHICLE))
        assert res.explored[0] == (2, 0)
        assert len(res.explored) == len(set(res.explored))
        assert not set(res.frontier) & set(res.explored)
        assert res.heuristic_start == manhattan((2, 0), (2, 9))
        assert res.time_ms >= 0 and res.max_frontier >= 1


def test_mobility_profiles():
    grid = Grid.from_strings(["..~~..", "..FF..", "......"])
    across_water = GridSearchProblem(grid, (0, 0), (0, 5), WATER_RESCUE_TEAM, danger_aware=False)
    assert astar(across_water).found
    # Ground vehicles must go around both water and fire via row 2.
    ground = astar(GridSearchProblem(grid, (0, 0), (0, 5), GROUND_VEHICLE))
    assert ground.found and all(grid.type_at(p).value == "ROAD" for p in ground.path)
    walled = Grid.from_strings(["..F.."])
    assert not astar(GridSearchProblem(walled, (0, 0), (0, 4), GROUND_VEHICLE)).found
    assert astar(GridSearchProblem(walled, (0, 0), (0, 4), FIREFIGHTING_TEAM)).found


def test_first_blocked_index_and_path_cost():
    grid = Grid.from_strings(["....."])
    path = [(0, 0), (0, 1), (0, 2), (0, 3)]
    assert first_blocked_index(path, grid, GROUND_VEHICLE) is None
    assert path_cost_on(grid, path, GROUND_VEHICLE) == pytest.approx(3.0)
    grid.set_type((0, 2), CellType.OBSTACLE)
    assert first_blocked_index(path, grid, GROUND_VEHICLE) == 2
    assert path_cost_on(grid, path, GROUND_VEHICLE) is None


def test_repeated_astar_replans_when_unknown_walls_are_discovered():
    # The straight row-1 route looks open under the free-space assumption.
    truth = Grid.from_strings([
        "...........",
        "..#######..",
        "...........",
    ])
    res = repeated_astar(truth, (1, 0), (1, 10), GROUND_VEHICLE, sensor_radius=1)
    assert res.found
    assert res.trajectory[0] == (1, 0) and res.trajectory[-1] == (1, 10)
    assert is_valid_path(res.trajectory, truth, GROUND_VEHICLE)
    assert res.replans >= 1  # it believed the wall row was open road
    assert res.events and "Discovered" in res.events[0]["message"]
    offline = astar(GridSearchProblem(truth, (1, 0), (1, 10), GROUND_VEHICLE))
    assert res.cost >= offline.cost - 1e-9


def test_lrta_star_learns_and_reaches_goal():
    truth = Grid.from_strings([
        "......",
        ".####.",
        ".#....",
        ".#.##.",
        "......",
    ])
    res = lrta_star(truth, (2, 2), (0, 0), GROUND_VEHICLE, sensor_radius=1)
    assert res.found
    assert is_valid_path(res.trajectory, truth, GROUND_VEHICLE)
    assert res.heuristic_updates > 0
    assert len(res.cells_revealed) > 0
