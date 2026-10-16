"""Core domain entities of the disaster-response world.

Everything the agent reasons about (cells, victims, ambulances, rescue teams,
hospitals, safe zones) is defined here as plain dataclasses so that the AI
modules (search, CSP, planning, agent) stay independent of the web layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

Pos = tuple[int, int]
"""Grid coordinate as (row, col)."""


class CellType(str, Enum):
    ROAD = "ROAD"
    BUILDING = "BUILDING"
    OBSTACLE = "OBSTACLE"  # debris / collapsed structure blocking a road
    FIRE = "FIRE"
    WATER = "WATER"  # flood water
    HOSPITAL = "HOSPITAL"
    VICTIM = "VICTIM"  # road cell occupied by a reported victim (overlay type)
    RESCUE_BASE = "RESCUE_BASE"
    SAFE_ZONE = "SAFE_ZONE"


# Single-character codes used to ship the grid compactly to the UI and to
# describe hand-made maps in tests.
CELL_CODES: dict[CellType, str] = {
    CellType.ROAD: ".",
    CellType.BUILDING: "#",
    CellType.OBSTACLE: "X",
    CellType.FIRE: "F",
    CellType.WATER: "~",
    CellType.HOSPITAL: "H",
    CellType.VICTIM: "V",
    CellType.RESCUE_BASE: "B",
    CellType.SAFE_ZONE: "S",
}
CODE_TO_CELL: dict[str, CellType] = {code: cell for cell, code in CELL_CODES.items()}


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
}

# Health points lost per tick while waiting (before multipliers).
SEVERITY_DECAY: dict[Severity, float] = {
    Severity.CRITICAL: 0.32,
    Severity.HIGH: 0.18,
    Severity.MEDIUM: 0.09,
    Severity.LOW: 0.03,
}


class VictimStatus(str, Enum):
    UNREPORTED = "UNREPORTED"  # exists in the world, not yet known to the agent
    WAITING = "WAITING"  # known, no resources assigned
    ASSIGNED = "ASSIGNED"  # resources travelling to the victim
    BEING_RESCUED = "BEING_RESCUED"  # extraction / stabilisation on scene
    IN_TRANSIT = "IN_TRANSIT"  # loaded in a carrier
    RESCUED = "RESCUED"  # delivered to a hospital or safe zone
    DECEASED = "DECEASED"


ACTIVE_VICTIM_STATUSES = {
    VictimStatus.WAITING,
    VictimStatus.ASSIGNED,
    VictimStatus.BEING_RESCUED,
    VictimStatus.IN_TRANSIT,
}


class MedicalLevel(str, Enum):
    ALS = "ALS"  # Advanced Life Support - can carry critical patients
    BLS = "BLS"  # Basic Life Support


class TeamCapability(str, Enum):
    URBAN_SAR = "URBAN_SAR"  # urban search & rescue, can climb debris
    FIREFIGHTING = "FIREFIGHTING"  # can enter fire zones
    WATER_RESCUE = "WATER_RESCUE"  # boat team, can cross flood water


class UnitStatus(str, Enum):
    IDLE = "IDLE"
    EN_ROUTE = "EN_ROUTE"
    ON_SCENE = "ON_SCENE"
    TRANSPORTING = "TRANSPORTING"
    WAITING = "WAITING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


@dataclass
class Victim:
    id: str
    pos: Pos
    severity: Severity
    health: float  # 0..100
    rescue_time: int  # ticks of on-scene work (extraction or stabilisation)
    trapped: bool = False
    needs_icu: bool = False
    reported: bool = True
    reported_tick: int = 0
    status: VictimStatus = VictimStatus.WAITING
    extracted: bool = False
    rescue_progress: int = 0
    carrier_id: str | None = None
    destination_id: str | None = None
    assigned_units: list[str] = field(default_factory=list)
    rescued_tick: int | None = None
    deceased_tick: int | None = None
    priority: float = 0.0
    priority_breakdown: list[dict] = field(default_factory=list)
    required_resources: list[str] = field(default_factory=list)  # maintained by the agent

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_VICTIM_STATUSES

    @property
    def needs_hospital(self) -> bool:
        return self.severity != Severity.LOW

    @property
    def health_status(self) -> str:
        if self.status == VictimStatus.DECEASED:
            return "DECEASED"
        if self.status == VictimStatus.RESCUED:
            return "SAFE"
        if self.health < 25:
            return "CRITICAL CONDITION"
        if self.health < 50:
            return "DETERIORATING"
        if self.health < 75:
            return "INJURED"
        return "STABLE"


@dataclass
class Ambulance:
    id: str
    pos: Pos
    capacity: int
    medical: MedicalLevel
    available: bool = True
    status: UnitStatus = UnitStatus.IDLE
    carrying: list[str] = field(default_factory=list)
    distance_travelled: int = 0

    @property
    def kind(self) -> str:
        return "AMBULANCE"

    @property
    def free_seats(self) -> int:
        return self.capacity - len(self.carrying)


@dataclass
class RescueTeam:
    id: str
    pos: Pos
    capability: TeamCapability
    available: bool = True
    status: UnitStatus = UnitStatus.IDLE
    carrying: list[str] = field(default_factory=list)
    distance_travelled: int = 0
    capacity: int = 1

    @property
    def kind(self) -> str:
        return "TEAM"


Unit = Ambulance | RescueTeam


@dataclass
class Hospital:
    id: str
    name: str
    pos: Pos
    er_capacity: int
    icu_capacity: int
    er_occupancy: int = 0
    icu_occupancy: int = 0

    @property
    def er_free(self) -> int:
        return max(0, self.er_capacity - self.er_occupancy)

    @property
    def icu_free(self) -> int:
        return max(0, self.icu_capacity - self.icu_occupancy)


@dataclass
class SafeZone:
    id: str
    name: str
    pos: Pos  # entry cell
    capacity: int = 50
    occupancy: int = 0
