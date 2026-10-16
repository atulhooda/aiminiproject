"""Mobility profiles: which terrain a unit can traverse and at what cost.

The danger-aware step cost used by every search algorithm is

    cost(n -> m) = terrain_cost(m) + DANGER_WEIGHT * danger(m)

Every passable terrain costs at least 1, so the Manhattan distance is an
admissible (and consistent) heuristic for A*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.environment.grid import Grid
from app.models.entities import Ambulance, CellType, Pos, RescueTeam, TeamCapability, Unit

DANGER_WEIGHT = 6.0
MIN_STEP_COST = 1.0

_BASE_ROADS: dict[CellType, float] = {
    CellType.ROAD: 1.0,
    CellType.VICTIM: 1.0,
    CellType.HOSPITAL: 1.0,
    CellType.RESCUE_BASE: 1.0,
    CellType.SAFE_ZONE: 1.5,
}


@dataclass(frozen=True)
class MobilityProfile:
    name: str
    label: str
    terrain_cost: dict[CellType, float] = field(hash=False)

    def passable(self, cell_type: CellType) -> bool:
        return cell_type in self.terrain_cost

    def step_cost(self, grid: Grid, pos: Pos, danger_aware: bool = True) -> float | None:
        """Cost of entering `pos`, or None if this profile cannot enter it."""
        base = self.terrain_cost.get(grid.type_at(pos))
        if base is None:
            return None
        if danger_aware:
            return base + DANGER_WEIGHT * grid.danger_at(pos)
        return base


GROUND_VEHICLE = MobilityProfile("GROUND_VEHICLE", "Ground vehicle (ambulance)", dict(_BASE_ROADS))
URBAN_SAR_TEAM = MobilityProfile(
    "URBAN_SAR", "Urban SAR team (climbs debris)", {**_BASE_ROADS, CellType.OBSTACLE: 4.0}
)
FIREFIGHTING_TEAM = MobilityProfile(
    "FIREFIGHTING",
    "Firefighting team (enters fire)",
    {**_BASE_ROADS, CellType.OBSTACLE: 4.0, CellType.FIRE: 4.0},
)
WATER_RESCUE_TEAM = MobilityProfile(
    "WATER_RESCUE", "Water rescue team (boat)", {**_BASE_ROADS, CellType.WATER: 2.0}
)

PROFILES: dict[str, MobilityProfile] = {
    p.name: p for p in (GROUND_VEHICLE, URBAN_SAR_TEAM, FIREFIGHTING_TEAM, WATER_RESCUE_TEAM)
}

_TEAM_PROFILES = {
    TeamCapability.URBAN_SAR: URBAN_SAR_TEAM,
    TeamCapability.FIREFIGHTING: FIREFIGHTING_TEAM,
    TeamCapability.WATER_RESCUE: WATER_RESCUE_TEAM,
}


def profile_for(unit: Unit) -> MobilityProfile:
    if isinstance(unit, Ambulance):
        return GROUND_VEHICLE
    if isinstance(unit, RescueTeam):
        return _TEAM_PROFILES[unit.capability]
    raise TypeError(f"unknown unit type: {type(unit).__name__}")
