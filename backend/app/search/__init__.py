"""Search algorithms implemented from scratch (no path-finding libraries)."""

from __future__ import annotations

from app.search.astar import astar
from app.search.base import GridSearchProblem, SearchResult
from app.search.bfs import bfs
from app.search.greedy_best_first import greedy_best_first
from app.search.heuristics import get_heuristic

ALGORITHMS = ("BFS", "GREEDY", "ASTAR")
ALGORITHM_LABELS = {
    "BFS": "Breadth-First Search",
    "GREEDY": "Greedy Best-First Search",
    "ASTAR": "A* Search",
}


def run_search(algorithm: str, problem: GridSearchProblem, heuristic: str = "manhattan") -> SearchResult:
    algo = algorithm.upper()
    if algo == "BFS":
        return bfs(problem)
    if algo == "GREEDY":
        return greedy_best_first(problem, get_heuristic(heuristic), heuristic)
    if algo == "ASTAR":
        return astar(problem, get_heuristic(heuristic), heuristic)
    raise ValueError(f"unknown algorithm '{algorithm}'; choose one of {ALGORITHMS}")


__all__ = ["ALGORITHMS", "ALGORITHM_LABELS", "GridSearchProblem", "SearchResult", "run_search"]
