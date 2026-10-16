"""A* search: f(n) = g(n) + h(n).

g(n) is the exact danger-aware cost of the best known path from the start to n,
h(n) the heuristic estimate from n to the goal. With an admissible and
consistent heuristic (Manhattan on this grid) the first time the goal is
popped from the frontier its path is optimal.

Ties on f are broken in favour of the larger g (smaller h), which pushes the
search towards the goal and keeps the explored set small.
"""

from __future__ import annotations

import heapq
import itertools
import time

from app.models.entities import Pos
from app.search.base import GridSearchProblem, Heuristic, SearchResult, reconstruct_path
from app.search.heuristics import manhattan


def astar(
    problem: GridSearchProblem, heuristic: Heuristic = manhattan, heuristic_name: str = "manhattan"
) -> SearchResult:
    t0 = time.perf_counter()
    start, goal = problem.start, problem.goal
    h0 = heuristic(start, goal)
    result = SearchResult(
        algorithm="ASTAR",
        start=start,
        goal=goal,
        found=False,
        heuristic_name=heuristic_name,
        heuristic_start=h0,
    )

    counter = itertools.count()
    # Entries: (f, h, tie-break counter, node). Stale entries are skipped lazily.
    frontier: list[tuple[float, float, int, Pos]] = [(h0, h0, next(counter), start)]
    g_score: dict[Pos, float] = {start: 0.0}
    parents: dict[Pos, Pos | None] = {start: None}
    closed: set[Pos] = set()
    result.nodes_generated = 1
    result.max_frontier = 1

    while frontier:
        _f, _h, _, node = heapq.heappop(frontier)
        if node in closed:
            continue
        if problem.is_goal(node):
            result.found = True
            result.path = reconstruct_path(parents, node)
            result.cost = g_score[node]
            break
        closed.add(node)
        result.explored.append(node)
        result.nodes_expanded += 1
        g_node = g_score[node]
        for child, step in problem.successors(node):
            if child in closed:
                continue
            tentative = g_node + step
            if tentative < g_score.get(child, float("inf")):
                g_score[child] = tentative
                parents[child] = node
                h = heuristic(child, goal)
                heapq.heappush(frontier, (tentative + h, h, next(counter), child))
                result.nodes_generated += 1
        result.max_frontier = max(result.max_frontier, len(frontier))

    # Report each frontier cell once (lazy deletion can leave duplicates).
    seen: set[Pos] = set()
    for entry in frontier:
        cell = entry[3]
        if cell not in closed and cell not in seen:
            seen.add(cell)
            result.frontier.append(cell)
    result.time_ms = (time.perf_counter() - t0) * 1000
    return result
