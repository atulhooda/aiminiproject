"""Grid environment: cells with coordinates, traversal cost, danger and accessibility."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Iterator

from app.models.entities import CELL_CODES, CODE_TO_CELL, CellType, Pos

# Danger contributed by hazards to nearby cells (distance -> danger).
FIRE_DANGER_BY_DISTANCE = {0: 1.0, 1: 0.6, 2: 0.3}
WATER_CELL_DANGER = 0.5
WATER_ADJACENT_DANGER = 0.2
DEBRIS_ADJACENT_DANGER = 0.1

# Cell types a hazard may never overwrite (infrastructure the scenario depends on).
PROTECTED_TYPES = {CellType.HOSPITAL, CellType.RESCUE_BASE, CellType.SAFE_ZONE}

DIRECTIONS: tuple[Pos, ...] = ((-1, 0), (0, 1), (1, 0), (0, -1))


@dataclass(frozen=True)
class Cell:
    """Read-only view of one grid cell."""

    row: int
    col: int
    type: CellType
    danger: float
    traversal_cost: float | None  # for a ground vehicle; None = impassable
    accessible: bool

    def to_dict(self) -> dict:
        return {
            "row": self.row,
            "col": self.col,
            "type": self.type.value,
            "danger": round(self.danger, 2),
            "traversal_cost": self.traversal_cost,
            "accessible": self.accessible,
        }


class Grid:
    """A rectangular disaster zone.

    The grid only stores terrain; victims and units are entities that live on
    top of it. Danger is derived from hazards (fire, water, debris) and is
    recomputed whenever terrain changes.
    """

    def __init__(self, cells: list[list[CellType]]):
        if not cells or not cells[0]:
            raise ValueError("grid must have at least one cell")
        width = len(cells[0])
        if any(len(row) != width for row in cells):
            raise ValueError("all grid rows must have the same length")
        self.rows = len(cells)
        self.cols = width
        self._cells = [list(row) for row in cells]
        self._danger = [[0.0] * self.cols for _ in range(self.rows)]
        self.version = 0
        self.recompute_danger()

    # ------------------------------------------------------------------ build
    @classmethod
    def from_strings(cls, lines: Iterable[str]) -> "Grid":
        rows = [[CODE_TO_CELL[ch] for ch in line] for line in lines]
        # Victim markers are terrain-wise roads.
        rows = [[CellType.ROAD if c == CellType.VICTIM else c for c in row] for row in rows]
        return cls(rows)

    def copy(self) -> "Grid":
        clone = Grid.__new__(Grid)
        clone.rows = self.rows
        clone.cols = self.cols
        clone._cells = [list(row) for row in self._cells]
        clone._danger = [list(row) for row in self._danger]
        clone.version = self.version
        return clone

    # ---------------------------------------------------------------- queries
    def in_bounds(self, pos: Pos) -> bool:
        r, c = pos
        return 0 <= r < self.rows and 0 <= c < self.cols

    def type_at(self, pos: Pos) -> CellType:
        return self._cells[pos[0]][pos[1]]

    def danger_at(self, pos: Pos) -> float:
        return self._danger[pos[0]][pos[1]]

    def neighbors4(self, pos: Pos) -> Iterator[Pos]:
        r, c = pos
        for dr, dc in DIRECTIONS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.rows and 0 <= nc < self.cols:
                yield (nr, nc)

    def positions(self) -> Iterator[Pos]:
        for r in range(self.rows):
            for c in range(self.cols):
                yield (r, c)

    def cells_of_type(self, *types: CellType) -> list[Pos]:
        wanted = set(types)
        return [p for p in self.positions() if self.type_at(p) in wanted]

    def cell(self, pos: Pos) -> Cell:
        from app.environment.mobility import GROUND_VEHICLE  # local import avoids a cycle

        cost = GROUND_VEHICLE.step_cost(self, pos)
        return Cell(
            row=pos[0],
            col=pos[1],
            type=self.type_at(pos),
            danger=self.danger_at(pos),
            traversal_cost=None if cost is None else round(cost, 2),
            accessible=cost is not None,
        )

    # -------------------------------------------------------------- mutation
    def set_type(self, pos: Pos, cell_type: CellType, recompute: bool = True) -> CellType:
        """Change terrain at `pos`, returning the previous type."""
        if not self.in_bounds(pos):
            raise ValueError(f"cell {pos} is outside the grid")
        previous = self._cells[pos[0]][pos[1]]
        if previous != cell_type:
            self._cells[pos[0]][pos[1]] = cell_type
            self.version += 1
            if recompute:
                self.recompute_danger()
        return previous

    def recompute_danger(self) -> None:
        danger = [[0.0] * self.cols for _ in range(self.rows)]

        # Fire: multi-source BFS so danger decays with distance from the flames.
        fire_sources = self.cells_of_type(CellType.FIRE)
        dist: dict[Pos, int] = {p: 0 for p in fire_sources}
        queue = deque(fire_sources)
        max_d = max(FIRE_DANGER_BY_DISTANCE)
        while queue:
            p = queue.popleft()
            d = dist[p]
            danger[p[0]][p[1]] = max(danger[p[0]][p[1]], FIRE_DANGER_BY_DISTANCE[d])
            if d == max_d:
                continue
            for n in self.neighbors4(p):
                if n not in dist:
                    dist[n] = d + 1
                    queue.append(n)

        for p in self.positions():
            t = self.type_at(p)
            if t == CellType.WATER:
                danger[p[0]][p[1]] = max(danger[p[0]][p[1]], WATER_CELL_DANGER)
                for n in self.neighbors4(p):
                    if self.type_at(n) != CellType.WATER:
                        danger[n[0]][n[1]] = max(danger[n[0]][n[1]], WATER_ADJACENT_DANGER)
            elif t == CellType.OBSTACLE:
                for n in self.neighbors4(p):
                    danger[n[0]][n[1]] = max(danger[n[0]][n[1]], DEBRIS_ADJACENT_DANGER)

        # Infrastructure cells are hardened shelters.
        for p in self.positions():
            if self.type_at(p) in PROTECTED_TYPES:
                danger[p[0]][p[1]] = min(danger[p[0]][p[1]], 0.1)
        self._danger = danger

    # --------------------------------------------------------- serialisation
    def to_codes(self) -> list[str]:
        return ["".join(CELL_CODES[c] for c in row) for row in self._cells]

    def danger_matrix(self) -> list[list[int]]:
        """Danger as integer percentages (compact for the UI)."""
        return [[int(round(d * 100)) for d in row] for row in self._danger]
