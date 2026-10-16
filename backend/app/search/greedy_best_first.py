"""Greedy Best-First Search.

Expands the node that *appears* closest to the goal, i.e. it orders the
frontier by f(n) = h(n) only. It is usually very fast but neither optimal nor
(on infinite spaces) complete; on a finite grid with an explored set it is
complete.
"""

from __future__ import annotations

import heapq
import itertools
import time

from app.models.entities import Pos
from app.search.base import GridSearchProblem, Heuristic, SearchResult, reconstruct_path
from app.search.heuristics import manhattan


def greedy_best_first(
    problem: GridSearchProblem, heuristic: Heuristic = manhattan, heuristic_name: str = "manhattan"
) -> SearchResult:
    t0 = time.perf_counter()
    start, goal = problem.start, problem.goal
    result = SearchResult(
        algorithm="GREEDY",
        start=start,
        goal=goal,
        found=False,
        heuristic_name=heuristic_name,
        heuristic_start=heuristic(start, goal),
    )

    counter = itertools.count()
    frontier: list[tuple[float, int, Pos]] = [(heuristic(start, goal), next(counter), start)]
    in_frontier: set[Pos] = {start}
    parents: dict[Pos, Pos | None] = {start: None}
    explored: set[Pos] = set()
    result.nodes_generated = 1
    result.max_frontier = 1

    while frontier:
        _h, _, node = heapq.heappop(frontier)
        in_frontier.discard(node)
        if problem.is_goal(node):
            result.found = True
            result.path = reconstruct_path(parents, node)
            result.cost = problem.path_cost(result.path) or 0.0
            break
        explored.add(node)
        result.explored.append(node)
        result.nodes_expanded += 1
        for child, _cost in problem.successors(node):
            if child in explored or child in in_frontier:
                continue
            parents[child] = node
            heapq.heappush(frontier, (heuristic(child, goal), next(counter), child))
            in_frontier.add(child)
            result.nodes_generated += 1
        result.max_frontier = max(result.max_frontier, len(frontier))

    result.frontier = [entry[2] for entry in frontier]
    result.time_ms = (time.perf_counter() - t0) * 1000
    return result
