"""Breadth-First Search (uninformed).

BFS expands the shallowest node first using a FIFO queue. It is complete and
returns the path with the fewest *steps*, but it ignores step costs, so with
danger-aware costs its path is generally not the cheapest.
"""

from __future__ import annotations

import time
from collections import deque

from app.models.entities import Pos
from app.search.base import GridSearchProblem, SearchResult, reconstruct_path


def bfs(problem: GridSearchProblem) -> SearchResult:
    t0 = time.perf_counter()
    start = problem.start
    result = SearchResult(algorithm="BFS", start=start, goal=problem.goal, found=False)

    parents: dict[Pos, Pos | None] = {start: None}
    frontier: deque[Pos] = deque([start])
    result.nodes_generated = 1
    result.max_frontier = 1

    if problem.is_goal(start):
        result.found = True
        result.path = [start]
        result.time_ms = (time.perf_counter() - t0) * 1000
        return result

    while frontier:
        node = frontier.popleft()
        result.explored.append(node)
        result.nodes_expanded += 1
        for child, _cost in problem.successors(node):
            if child in parents:  # already in frontier or explored
                continue
            parents[child] = node
            result.nodes_generated += 1
            # Early goal test on generation (standard for BFS).
            if problem.is_goal(child):
                result.found = True
                result.path = reconstruct_path(parents, child)
                result.cost = problem.path_cost(result.path) or 0.0
                result.frontier = list(frontier)
                result.time_ms = (time.perf_counter() - t0) * 1000
                return result
            frontier.append(child)
        result.max_frontier = max(result.max_frontier, len(frontier))

    result.time_ms = (time.perf_counter() - t0) * 1000
    return result
