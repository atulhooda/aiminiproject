"""Predefined disaster scenarios and the custom scenario generator.

All scenarios are deterministic for a given seed, so runs are reproducible.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

from app.environment.events import DisasterEvent, EventType
from app.environment.grid import Grid
from app.environment.mobility import GROUND_VEHICLE
from app.environment.world import Dynamics, World
from app.models.entities import (
    Ambulance,
    CellType,
    Hospital,
    MedicalLevel,
    Pos,
    RescueTeam,
    SafeZone,
    Severity,
    TeamCapability,
    Victim,
    VictimStatus,
)

AVENUES = (2, 7, 12, 17, 22)


@dataclass
class ScenarioInfo:
    id: str
    name: str
    description: str
    challenges: list[str]
    recommended_algorithm: str = "ASTAR"
    seed: int = 0
    demo: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "challenges": self.challenges,
            "recommended_algorithm": self.recommended_algorithm,
            "seed": self.seed,
            "demo": self.demo,
        }


@dataclass
class BuiltScenario:
    world: World
    info: ScenarioInfo
    schedule: dict[int, list[DisasterEvent]] = field(default_factory=dict)


class ScenarioBuilder:
    """Small DSL for laying out a city grid and its entities."""

    def __init__(self, rows: int, cols: int, seed: int):
        self.rows, self.cols = rows, cols
        self.rng = random.Random(seed)
        self.cells = [[CellType.BUILDING] * cols for _ in range(rows)]
        self.victims: dict[str, Victim] = {}
        self.ambulances: dict[str, Ambulance] = {}
        self.teams: dict[str, RescueTeam] = {}
        self.hospitals: dict[str, Hospital] = {}
        self.safe_zones: dict[str, SafeZone] = {}
        self.bases: list[Pos] = []
        self.hidden: dict[Pos, CellType] = {}
        self.schedule: dict[int, list[DisasterEvent]] = {}
        self.dynamics = Dynamics()

    # ---- terrain
    def set(self, pos: Pos, cell_type: CellType) -> None:
        self.cells[pos[0]][pos[1]] = cell_type

    def get(self, pos: Pos) -> CellType:
        return self.cells[pos[0]][pos[1]]

    def avenues(self, rows=AVENUES, cols=AVENUES) -> None:
        for r in rows:
            if r < self.rows:
                for c in range(self.cols):
                    self.set((r, c), CellType.ROAD)
        for c in cols:
            if c < self.cols:
                for r in range(self.rows):
                    self.set((r, c), CellType.ROAD)

    def alleys(self, rows=AVENUES, cols=AVENUES, probability: float = 0.6) -> None:
        """Carve a short alley through some city blocks to create alternative routes."""
        bounds_r = [-1, *rows, self.rows]
        bounds_c = [-1, *cols, self.cols]
        for r0, r1 in zip(bounds_r, bounds_r[1:]):
            for c0, c1 in zip(bounds_c, bounds_c[1:]):
                if r1 - r0 < 4 or c1 - c0 < 4 or r0 < 0 or c0 < 0 or r1 >= self.rows or c1 >= self.cols:
                    continue
                if self.rng.random() > probability:
                    continue
                if self.rng.random() < 0.5:
                    c = self.rng.randint(c0 + 2, c1 - 2)
                    for r in range(r0 + 1, r1):
                        self.set((r, c), CellType.ROAD)
                else:
                    r = self.rng.randint(r0 + 2, r1 - 2)
                    for c in range(c0 + 1, c1):
                        self.set((r, c), CellType.ROAD)

    def fill(self, cells: list[Pos], cell_type: CellType) -> None:
        for p in cells:
            self.set(p, cell_type)

    def hidden_hazard(self, pos: Pos, true_type: CellType = CellType.OBSTACLE) -> None:
        """Hazard present in reality but missing from the initial situation report."""
        self.set(pos, true_type)
        self.hidden[pos] = true_type

    # ---- facilities
    def hospital(self, hid: str, name: str, pos: Pos, er: int, icu: int) -> None:
        self.set(pos, CellType.HOSPITAL)
        self.hospitals[hid] = Hospital(hid, name, pos, er_capacity=er, icu_capacity=icu)

    def safe_zone(self, sid: str, name: str, cells: list[Pos], entry: Pos) -> None:
        self.fill(cells, CellType.SAFE_ZONE)
        self.safe_zones[sid] = SafeZone(sid, name, entry)

    def base(self, *cells: Pos) -> None:
        for p in cells:
            self.set(p, CellType.RESCUE_BASE)
            self.bases.append(p)

    # ---- units & victims
    def ambulance(self, aid: str, pos: Pos, medical: MedicalLevel, capacity: int = 1) -> None:
        self.ambulances[aid] = Ambulance(aid, pos, capacity=capacity, medical=medical)

    def team(self, tid: str, pos: Pos, capability: TeamCapability) -> None:
        self.teams[tid] = RescueTeam(tid, pos, capability=capability)

    def victim(
        self,
        vid: str,
        pos: Pos,
        severity: Severity,
        health: float,
        rescue_time: int,
        trapped: bool = False,
        reported: bool = True,
    ) -> None:
        if self.get(pos) not in (CellType.ROAD, CellType.FIRE, CellType.WATER):
            raise ValueError(f"victim {vid} placed on {self.get(pos).value} at {pos}")
        self.victims[vid] = Victim(
            id=vid,
            pos=pos,
            severity=severity,
            health=health,
            rescue_time=rescue_time,
            trapped=trapped,
            needs_icu=severity == Severity.CRITICAL,
            reported=reported,
            status=VictimStatus.WAITING if reported else VictimStatus.UNREPORTED,
        )

    def at(self, tick: int, event: DisasterEvent) -> None:
        event.source = "SCENARIO"
        self.schedule.setdefault(tick, []).append(event)

    def build(self, info: ScenarioInfo) -> BuiltScenario:
        world = World(
            grid=Grid(self.cells),
            victims=self.victims,
            ambulances=self.ambulances,
            teams=self.teams,
            hospitals=self.hospitals,
            safe_zones=self.safe_zones,
            bases=self.bases,
            rng=self.rng,
            dynamics=self.dynamics,
            hidden_hazards=dict(self.hidden),
        )
        return BuiltScenario(world, info, self.schedule)


def _rect(r0: int, r1: int, c0: int, c1: int) -> list[Pos]:
    return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


# ------------------------------------------------------------------ EARTHQUAKE
def _earthquake(seed: int, demo: bool = False) -> BuiltScenario:
    b = ScenarioBuilder(25, 25, seed)
    b.avenues()
    b.alleys(probability=0.55)
    b.base((23, 3), (23, 4))
    b.base((1, 11))
    b.hospital("H1", "St. Mary's General", (11, 13), er=6, icu=2)
    b.hospital("H2", "Northside Clinic", (3, 21), er=4, icu=2)
    b.safe_zone("S1", "Central Park", _rect(13, 14, 3, 4), entry=(13, 3))
    # Collapsed structures already reported (known rubble).
    for p in [(7, 9), (12, 5), (17, 14), (2, 15), (22, 9), (9, 7), (12, 20), (4, 12)]:
        b.set(p, CellType.OBSTACLE)
    # Damage nobody has reported yet - only unit sensors will find it.
    b.hidden_hazard((12, 9))
    b.hidden_hazard((17, 4))
    b.hidden_hazard((9, 17))

    b.ambulance("A1", (23, 3), MedicalLevel.ALS)
    b.ambulance("A2", (11, 12), MedicalLevel.ALS)
    b.ambulance("A3", (22, 4), MedicalLevel.BLS, capacity=2)
    b.team("T1", (23, 4), TeamCapability.URBAN_SAR)
    b.team("T2", (22, 3), TeamCapability.URBAN_SAR)
    b.team("T3", (2, 11), TeamCapability.FIREFIGHTING)

    b.victim("V01", (7, 15), Severity.CRITICAL, 44, 4, trapped=True)
    b.victim("V02", (17, 20), Severity.CRITICAL, 40, 3)
    b.victim("V03", (14, 12), Severity.HIGH, 56, 3, trapped=True)
    b.victim("V04", (4, 7), Severity.HIGH, 61, 2)
    b.victim("V05", (20, 12), Severity.MEDIUM, 72, 2)
    b.victim("V06", (9, 2), Severity.MEDIUM, 70, 2)
    b.victim("V07", (17, 9), Severity.LOW, 88, 1)
    b.victim("V08", (2, 4), Severity.LOW, 91, 1)
    b.victim("V09", (12, 16), Severity.HIGH, 58, 2, reported=False)

    b.dynamics = Dynamics(fire_spread_interval=6, fire_spread_probability=0.25, max_fire_cells=14)
    if demo:
        b.at(9, DisasterEvent(EventType.BLOCK_ROAD, label="Aftershock"))
        b.at(24, DisasterEvent(EventType.START_FIRE, target=(11, 10), label="Gas main rupture"))
        b.at(34, DisasterEvent(EventType.ADD_VICTIM, target=(19, 17), params={"severity": "CRITICAL", "trapped": True}, label="Building collapse"))
        b.at(48, DisasterEvent(EventType.REDUCE_HOSPITAL_CAPACITY, params={"hospital_id": "H1", "er": 3, "icu": 1}, label="Power failure"))
        info = ScenarioInfo(
            "DEMO",
            "Demo: Earthquake Response",
            "Scripted presentation run: magnitude 7.1 earthquake. Watch the agent prioritise victims, solve the "
            "allocation CSP, route with A*, then detect an aftershock road block and replan autonomously.",
            [
                "Aftershock blocks a road on an active route at tick 9",
                "Gas main rupture starts a fire at tick 24",
                "New critical victim at tick 34",
                "Hospital H1 loses capacity at tick 48",
                "Hidden road damage discovered by sensors",
            ],
            seed=seed,
            demo=True,
        )
    else:
        b.at(16, DisasterEvent(EventType.BLOCK_ROAD, label="Aftershock"))
        b.at(30, DisasterEvent(EventType.ADD_VICTIM, target=(19, 17), params={"severity": "CRITICAL", "trapped": True}, label="Aftershock casualty"))
        b.at(26, DisasterEvent(EventType.START_FIRE, target=(6, 19), label="Gas main rupture"))
        info = ScenarioInfo(
            "EARTHQUAKE",
            "Earthquake",
            "Magnitude 7.1 earthquake: collapsed buildings, debris-blocked roads, trapped victims and only three ambulances.",
            [
                "8 roads blocked by debris, 3 more undiscovered",
                "Trapped victims need rescue-team extraction before transport",
                "Limited ambulances: 2 ALS + 1 BLS (2 seats)",
                "Aftershocks block further roads during the operation",
                "One unreported victim waiting to be found",
            ],
            seed=seed,
        )
    return b.build(info)


# ------------------------------------------------------------------ URBAN FIRE
def _urban_fire(seed: int) -> BuiltScenario:
    b = ScenarioBuilder(25, 25, seed)
    b.avenues()
    b.alleys(probability=0.6)
    b.base((23, 3), (23, 4))
    b.base((1, 11))
    b.hospital("H1", "St. Mary's General", (11, 13), er=6, icu=2)
    b.hospital("H2", "Northside Clinic", (3, 21), er=5, icu=1)
    b.hospital("H3", "Riverside Trauma Center", (21, 23), er=4, icu=2)
    b.safe_zone("S1", "Central Park", _rect(13, 14, 3, 4), entry=(13, 3))
    b.safe_zone("S2", "Stadium Grounds", _rect(3, 4, 3, 4), entry=(3, 3))
    for p in _rect(5, 6, 9, 10) + [(8, 9)]:
        b.set(p, CellType.FIRE)
    for p in _rect(14, 15, 15, 16) + [(16, 15)]:
        b.set(p, CellType.FIRE)
    for p in _rect(19, 20, 5, 6):
        b.set(p, CellType.FIRE)

    b.ambulance("A1", (23, 3), MedicalLevel.ALS)
    b.ambulance("A2", (11, 12), MedicalLevel.ALS)
    b.ambulance("A3", (22, 4), MedicalLevel.BLS, capacity=2)
    b.ambulance("A4", (2, 21), MedicalLevel.BLS)
    b.team("T1", (2, 11), TeamCapability.FIREFIGHTING)
    b.team("T2", (23, 4), TeamCapability.FIREFIGHTING)
    b.team("T3", (22, 3), TeamCapability.URBAN_SAR)

    b.victim("V01", (7, 10), Severity.CRITICAL, 42, 3)
    b.victim("V02", (12, 15), Severity.CRITICAL, 45, 3, trapped=True)
    b.victim("V03", (17, 6), Severity.HIGH, 55, 3)
    b.victim("V04", (2, 17), Severity.HIGH, 60, 2)
    b.victim("V05", (22, 15), Severity.MEDIUM, 74, 2)
    b.victim("V06", (7, 20), Severity.MEDIUM, 69, 2, trapped=True)
    b.victim("V07", (12, 8), Severity.LOW, 86, 1)
    b.victim("V08", (17, 22), Severity.LOW, 90, 1)

    b.dynamics = Dynamics(fire_spread_interval=5, fire_spread_probability=0.3, max_fire_cells=42)
    b.at(18, DisasterEvent(EventType.START_FIRE, label="Fire jumps the avenue"))
    b.at(32, DisasterEvent(EventType.ADD_VICTIM, params={"severity": "HIGH"}, label="Smoke inhalation"))
    info = ScenarioInfo(
        "URBAN_FIRE",
        "Urban Fire",
        "Three structure fires spreading through the city. Victims near the flames need firefighting teams; roads close as the fire advances.",
        [
            "Fire spreads every 5 ticks and can block roads",
            "Victims inside danger zones need FIREFIGHTING teams",
            "Danger-aware A* keeps units away from the flames",
            "Two evacuation safe zones for walking wounded",
        ],
        seed=seed,
    )
    return b.build(info)


# ----------------------------------------------------------------------- FLOOD
def _flood(seed: int) -> BuiltScenario:
    b = ScenarioBuilder(25, 25, seed)
    b.avenues()
    b.alleys(probability=0.5)
    # River through columns 9-10, crossed by bridges on rows 7 and 17.
    for r in range(25):
        for c in (9, 10):
            if r not in (7, 17):
                b.set((r, c), CellType.WATER)
    # Flooded district in the south-east with a dry island in the middle.
    for p in _rect(17, 22, 17, 22):
        b.set(p, CellType.WATER)
    for p in _rect(19, 20, 19, 20):
        b.set(p, CellType.ROAD)
    b.base((23, 3), (23, 4))
    b.base((1, 13))
    b.hospital("H1", "West Bank Hospital", (11, 3), er=6, icu=2)
    b.hospital("H2", "Northside Clinic", (3, 21), er=5, icu=2)
    b.safe_zone("S1", "Hilltop Shelter", _rect(3, 4, 14, 15), entry=(3, 14))
    b.safe_zone("S2", "School Gym", _rect(13, 14, 3, 4), entry=(13, 3))

    b.ambulance("A1", (23, 3), MedicalLevel.ALS)
    b.ambulance("A2", (2, 20), MedicalLevel.ALS)
    b.ambulance("A3", (22, 4), MedicalLevel.BLS, capacity=2)
    b.team("T1", (23, 4), TeamCapability.WATER_RESCUE)
    b.team("T2", (2, 13), TeamCapability.WATER_RESCUE)
    b.team("T3", (22, 3), TeamCapability.URBAN_SAR)

    b.victim("V01", (19, 19), Severity.CRITICAL, 46, 3)  # isolated on the island
    b.victim("V02", (20, 20), Severity.MEDIUM, 70, 2)  # isolated on the island
    b.victim("V03", (12, 14), Severity.HIGH, 57, 2)
    b.victim("V04", (7, 13), Severity.CRITICAL, 43, 3, trapped=True)
    b.victim("V05", (2, 6), Severity.HIGH, 60, 2)
    b.victim("V06", (22, 12), Severity.MEDIUM, 75, 2)
    b.victim("V07", (12, 22), Severity.LOW, 89, 1)
    b.victim("V08", (17, 2), Severity.LOW, 92, 1)

    prone = set()
    for r in range(25):
        for c in (8, 11):
            if b.get((r, c)) == CellType.ROAD:
                prone.add((r, c))
    for c in range(11, 17):
        if b.get((17, c)) == CellType.ROAD:
            prone.add((17, c))
    b.dynamics = Dynamics(flood_interval=7, flood_cells_per_rise=2, flood_prone=prone)
    b.at(22, DisasterEvent(EventType.FLOOD_CELLS, params={"cells": [[17, 9], [17, 10]]}, label="Southern bridge submerged"))
    info = ScenarioInfo(
        "FLOOD",
        "Flood",
        "River flooding: a submerged district, two bridges, rising water and isolated victims only boat teams can reach.",
        [
            "Water rises every 7 ticks along the river banks",
            "Southern bridge goes under at tick 22",
            "Island victims are unreachable by ambulance: boat teams evacuate them",
            "Limited safe routes across the river",
        ],
        seed=seed,
    )
    return b.build(info)


# ---------------------------------------------------------------------- CUSTOM
@dataclass
class CustomConfig:
    rows: int = 25
    cols: int = 25
    seed: int = 42
    victims: int = 8
    critical_ratio: float = 0.3
    ambulances: int = 3
    teams: int = 3
    hospitals: int = 2
    obstacle_density: float = 0.06
    fire_seeds: int = 1
    fire_spread: bool = True
    hidden_hazards: int = 2
    flood: bool = False

    def validate(self) -> None:
        if not (12 <= self.rows <= 40 and 12 <= self.cols <= 40):
            raise ValueError("grid size must be between 12 and 40")
        if not (1 <= self.victims <= 25):
            raise ValueError("victims must be between 1 and 25")
        if not (1 <= self.ambulances <= 8 and 0 <= self.teams <= 8 and 1 <= self.hospitals <= 4):
            raise ValueError("1-8 ambulances, 0-8 teams and 1-4 hospitals are supported")
        if not (0 <= self.obstacle_density <= 0.25):
            raise ValueError("obstacle density must be between 0 and 0.25")
        if not (0 <= self.critical_ratio <= 1):
            raise ValueError("critical ratio must be between 0 and 1")
        if not (0 <= self.fire_seeds <= 6 and 0 <= self.hidden_hazards <= 10):
            raise ValueError("0-6 fire seeds and 0-10 hidden hazards are supported")


def _custom(cfg: CustomConfig) -> BuiltScenario:
    cfg.validate()
    b = ScenarioBuilder(cfg.rows, cfg.cols, cfg.seed)
    rng = b.rng
    step = 5
    rows = tuple(range(2, cfg.rows - 1, step))
    cols = tuple(range(2, cfg.cols - 1, step))
    b.avenues(rows, cols)
    b.alleys(rows, cols, probability=0.6)

    def frontage(avoid: set[Pos]) -> list[Pos]:
        """Building cells touching a road - candidate spots for facilities."""
        spots = []
        for r in range(1, cfg.rows - 1):
            for c in range(1, cfg.cols - 1):
                if b.get((r, c)) != CellType.BUILDING or (r, c) in avoid:
                    continue
                if any(b.get(n) == CellType.ROAD for n in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))):
                    spots.append((r, c))
        return spots

    used: set[Pos] = set()
    base = min(frontage(used), key=lambda p: (cfg.rows - p[0]) + p[1])  # south-west corner
    b.base(base)
    used.add(base)
    spots = frontage(used)
    rng.shuffle(spots)
    names = ["City General", "Northside Clinic", "Riverside Trauma", "St. Luke's"]
    placed = 0
    for p in spots:
        if placed >= cfg.hospitals:
            break
        if all(abs(p[0] - q[0]) + abs(p[1] - q[1]) >= 8 for q in used):
            b.hospital(f"H{placed + 1}", names[placed], p, er=rng.randint(4, 7), icu=rng.randint(1, 3))
            used.add(p)
            placed += 1
    if placed == 0:
        raise ValueError("could not place hospitals on this map")
    sz = next(p for p in frontage(used) if all(abs(p[0] - q[0]) + abs(p[1] - q[1]) >= 5 for q in used))
    b.safe_zone("S1", "Relief Camp", [sz], entry=sz)
    used.add(sz)

    base_road = next(n for n in ((base[0] - 1, base[1]), (base[0] + 1, base[1]), (base[0], base[1] - 1), (base[0], base[1] + 1))
                     if 0 <= n[0] < cfg.rows and 0 <= n[1] < cfg.cols and b.get(n) == CellType.ROAD)
    for i in range(cfg.ambulances):
        b.ambulance(f"A{i + 1}", base if i % 2 == 0 else base_road, MedicalLevel.ALS if i % 2 == 0 else MedicalLevel.BLS, capacity=1 if i % 2 == 0 else 2)
    caps = [TeamCapability.URBAN_SAR, TeamCapability.FIREFIGHTING, TeamCapability.WATER_RESCUE]
    for i in range(cfg.teams):
        b.team(f"T{i + 1}", base_road, caps[i % len(caps)])

    roads = [p for p in _all(cfg) if b.get(p) == CellType.ROAD]
    rng.shuffle(roads)
    protected = {base_road} | {n for p in used for n in ((p[0] - 1, p[1]), (p[0] + 1, p[1]), (p[0], p[1] - 1), (p[0], p[1] + 1))}
    anchors = [base_road] + [h.pos for h in b.hospitals.values()] + [sz]

    def connected() -> bool:
        grid = Grid(b.cells)
        seen = {anchors[0]}
        queue = deque([anchors[0]])
        while queue:
            p = queue.popleft()
            for n in grid.neighbors4(p):
                if n not in seen and GROUND_VEHICLE.passable(grid.type_at(n)):
                    seen.add(n)
                    queue.append(n)
        return all(a in seen for a in anchors)

    n_obstacles = int(len(roads) * cfg.obstacle_density)
    for p in roads[:n_obstacles * 2]:
        if n_obstacles <= 0:
            break
        if p in protected:
            continue
        b.set(p, CellType.OBSTACLE)
        if connected():
            n_obstacles -= 1
        else:
            b.set(p, CellType.ROAD)

    free_roads = [p for p in roads if b.get(p) == CellType.ROAD and p not in protected]
    rng.shuffle(free_roads)
    hidden = 0
    for p in free_roads[: cfg.hidden_hazards * 3]:
        if hidden >= cfg.hidden_hazards:
            break
        b.hidden_hazard(p)
        if connected():
            hidden += 1
        else:
            b.set(p, CellType.ROAD)
            b.hidden.pop(p, None)

    buildings = [p for p in _all(cfg) if b.get(p) == CellType.BUILDING and p not in used]
    rng.shuffle(buildings)
    for p in buildings[: cfg.fire_seeds]:
        b.set(p, CellType.FIRE)

    if cfg.flood:
        c = cfg.cols // 2
        for r in range(cfg.rows):
            if b.get((r, c)) == CellType.BUILDING:
                b.set((r, c), CellType.WATER)
        b.dynamics.flood_prone = {(r, cc) for r in range(cfg.rows) for cc in (c - 1, c + 1) if b.get((r, cc)) == CellType.ROAD}
        b.dynamics.flood_interval = 8

    victim_spots = [p for p in roads if b.get(p) == CellType.ROAD and p not in protected]
    n_critical = round(cfg.victims * cfg.critical_ratio)
    others = [Severity.HIGH, Severity.MEDIUM, Severity.MEDIUM, Severity.LOW]
    health = {Severity.CRITICAL: (38, 48), Severity.HIGH: (50, 64), Severity.MEDIUM: (65, 80), Severity.LOW: (85, 95)}
    for i in range(min(cfg.victims, len(victim_spots))):
        sev = Severity.CRITICAL if i < n_critical else others[i % len(others)]
        b.victim(
            f"V{i + 1:02d}", victim_spots[i], sev, float(rng.randint(*health[sev])),
            rng.randint(2, 4) if sev in (Severity.CRITICAL, Severity.HIGH) else rng.randint(1, 2),
            trapped=rng.random() < 0.35,
        )
    if cfg.fire_spread and cfg.fire_seeds:
        b.dynamics.fire_spread_interval = 6
        b.dynamics.max_fire_cells = 8 + 6 * cfg.fire_seeds
    info = ScenarioInfo(
        "CUSTOM",
        "Custom Scenario",
        f"User-configured {cfg.rows}x{cfg.cols} disaster zone (seed {cfg.seed}).",
        [
            f"{cfg.victims} victims ({n_critical} critical)",
            f"{cfg.ambulances} ambulances, {cfg.teams} rescue teams, {placed} hospitals",
            f"obstacle density {cfg.obstacle_density:.0%}, {hidden} hidden hazards, {cfg.fire_seeds} fire seed(s)",
        ],
        seed=cfg.seed,
    )
    return b.build(info)


def _all(cfg: CustomConfig) -> list[Pos]:
    return [(r, c) for r in range(cfg.rows) for c in range(cfg.cols)]


# -------------------------------------------------------------------- registry
SCENARIOS: dict[str, dict] = {
    "EARTHQUAKE": {"name": "Earthquake", "seed": 7},
    "URBAN_FIRE": {"name": "Urban Fire", "seed": 11},
    "FLOOD": {"name": "Flood", "seed": 5},
    "DEMO": {"name": "Demo: Earthquake Response", "seed": 7},
    "CUSTOM": {"name": "Custom Scenario", "seed": 42},
}


def build_scenario(scenario_id: str, seed: int | None = None, custom: dict | None = None) -> BuiltScenario:
    sid = scenario_id.upper()
    if sid not in SCENARIOS:
        raise ValueError(f"unknown scenario '{scenario_id}'; choose one of {sorted(SCENARIOS)}")
    seed = SCENARIOS[sid]["seed"] if seed is None else seed
    if sid == "EARTHQUAKE":
        return _earthquake(seed)
    if sid == "DEMO":
        return _earthquake(seed, demo=True)
    if sid == "URBAN_FIRE":
        return _urban_fire(seed)
    if sid == "FLOOD":
        return _flood(seed)
    cfg = CustomConfig(**(custom or {}))
    if custom is None or "seed" not in custom:
        cfg.seed = seed
    return _custom(cfg)


def list_scenarios() -> list[dict]:
    out = []
    for sid in SCENARIOS:
        if sid == "CUSTOM":
            out.append(
                ScenarioInfo(
                    "CUSTOM", "Custom Scenario",
                    "Configure grid size, victims, resources, obstacles, fires, hidden hazards and flooding.",
                    ["Fully configurable", "Paint terrain on the map while paused"], seed=42,
                ).to_dict()
            )
        else:
            out.append(build_scenario(sid).info.to_dict())
    return out
