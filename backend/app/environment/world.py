"""The ground-truth world the agent acts in."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.environment.grid import Grid
from app.models.entities import (
    Ambulance,
    CellType,
    Hospital,
    Pos,
    RescueTeam,
    SafeZone,
    Unit,
    Victim,
)


@dataclass
class Dynamics:
    """Natural environment processes that run without user input."""

    fire_spread_interval: int | None = None  # ticks between spread attempts
    fire_spread_probability: float = 0.25
    max_fire_cells: int = 40
    flood_interval: int | None = None
    flood_cells_per_rise: int = 2
    flood_prone: set[Pos] = field(default_factory=set)


@dataclass
class World:
    grid: Grid
    victims: dict[str, Victim]
    ambulances: dict[str, Ambulance]
    teams: dict[str, RescueTeam]
    hospitals: dict[str, Hospital]
    safe_zones: dict[str, SafeZone]
    bases: list[Pos]
    rng: random.Random
    dynamics: Dynamics = field(default_factory=Dynamics)
    # Cells whose true terrain differs from the initial situation report:
    # position -> true type. The agent starts believing these are open road.
    hidden_hazards: dict[Pos, CellType] = field(default_factory=dict)
    tick: int = 0
    victim_counter: int = 0

    def __post_init__(self) -> None:
        numbers = [int(v.id[1:]) for v in self.victims.values() if v.id[1:].isdigit()]
        self.victim_counter = max(numbers, default=0)

    # ------------------------------------------------------------- lookups
    def units(self) -> dict[str, Unit]:
        return {**self.ambulances, **self.teams}

    def unit(self, unit_id: str) -> Unit:
        unit = self.ambulances.get(unit_id) or self.teams.get(unit_id)
        if unit is None:
            raise KeyError(f"unknown unit '{unit_id}'")
        return unit

    def destination(self, dest_id: str) -> Hospital | SafeZone:
        dest = self.hospitals.get(dest_id) or self.safe_zones.get(dest_id)
        if dest is None:
            raise KeyError(f"unknown destination '{dest_id}'")
        return dest

    def destination_pos(self, dest_id: str) -> Pos:
        return self.destination(dest_id).pos

    def victims_at(self, pos: Pos) -> list[Victim]:
        return [v for v in self.victims.values() if v.pos == pos and v.is_active and v.carrier_id is None]

    def unit_positions(self) -> set[Pos]:
        return {u.pos for u in self.units().values()}

    def infrastructure_cells(self) -> set[Pos]:
        cells = {h.pos for h in self.hospitals.values()} | {s.pos for s in self.safe_zones.values()}
        return cells | set(self.bases)

    def next_victim_id(self) -> str:
        self.victim_counter += 1
        return f"V{self.victim_counter:02d}"
