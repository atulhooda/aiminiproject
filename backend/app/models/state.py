"""State-space representation of the whole disaster-response problem.

A state of the high-level problem is the tuple

    s = (resource positions, remaining victims, blocked roads, hazards,
         available resources, hospital capacity, current rescue tasks, time)

`WorldState` is an immutable, hashable snapshot of exactly that tuple. The
simulator's action execution is the transition model T(s, a) -> s', and the
goal test is "no reported victim remains active" (each is rescued or lost).
Terrain facts (blocked roads, hazards) come from the agent's belief map, so the
state never contains hazards the agent has not perceived yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.entities import CellType, Pos, VictimStatus


@dataclass(frozen=True)
class WorldState:
    tick: int
    resource_positions: tuple[tuple[str, Pos], ...]
    available_resources: frozenset[str]
    remaining_victims: tuple[tuple[str, str], ...]  # (victim id, status)
    blocked_roads: frozenset[Pos]
    hazard_cells: frozenset[Pos]  # fire + flood water
    hospital_capacity: tuple[tuple[str, int, int], ...]  # (id, er_free, icu_free)
    rescue_tasks: tuple[tuple[str, str], ...]  # (unit id, current task label)

    @property
    def is_goal(self) -> bool:
        return not self.remaining_victims

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "resource_positions": {uid: list(p) for uid, p in self.resource_positions},
            "available_resources": sorted(self.available_resources),
            "remaining_victims": {vid: status for vid, status in self.remaining_victims},
            "blocked_roads": sorted(list(p) for p in self.blocked_roads),
            "hazard_cells": len(self.hazard_cells),
            "hospital_capacity": {hid: {"er_free": er, "icu_free": icu} for hid, er, icu in self.hospital_capacity},
            "rescue_tasks": {uid: task for uid, task in self.rescue_tasks},
            "is_goal": self.is_goal,
        }


def capture_state(world, current_tasks: dict[str, str], grid=None) -> WorldState:
    """Abstract the world into a state of the problem's state space.

    `grid` is the terrain the state is built from - the agent's belief map in the
    simulator (defaults to the world's ground truth)."""
    grid = grid if grid is not None else world.grid
    units = {**world.ambulances, **world.teams}
    remaining = tuple(
        sorted(
            (v.id, v.status.value)
            for v in world.victims.values()
            if v.reported and v.status not in (VictimStatus.RESCUED, VictimStatus.DECEASED)
        )
    )
    return WorldState(
        tick=world.tick,
        resource_positions=tuple(sorted((uid, u.pos) for uid, u in units.items())),
        available_resources=frozenset(uid for uid, u in units.items() if u.available),
        remaining_victims=remaining,
        blocked_roads=frozenset(grid.cells_of_type(CellType.OBSTACLE)),
        hazard_cells=frozenset(grid.cells_of_type(CellType.FIRE, CellType.WATER)),
        hospital_capacity=tuple(
            sorted((h.id, h.er_free, h.icu_free) for h in world.hospitals.values())
        ),
        rescue_tasks=tuple(sorted(current_tasks.items())),
    )
