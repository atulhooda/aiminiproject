"""Dynamic environment events.

Events change the ground-truth world. Each applied event produces an
`EnvironmentReport` - the radio/field report the command centre receives and
which the agent consumes during its PERCEIVE phase. Hidden hazards (unknown to
the agent) are *not* reported; they can only be discovered by unit sensors.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from app.environment.grid import PROTECTED_TYPES
from app.environment.mobility import GROUND_VEHICLE
from app.environment.world import World
from app.models.entities import (
    CellType,
    Pos,
    Severity,
    UnitStatus,
    Victim,
    VictimStatus,
)


class EventType(str, Enum):
    # User / scenario triggered
    BLOCK_ROAD = "BLOCK_ROAD"
    CLEAR_ROAD = "CLEAR_ROAD"
    START_FIRE = "START_FIRE"
    ADD_VICTIM = "ADD_VICTIM"
    REMOVE_AMBULANCE = "REMOVE_AMBULANCE"
    REDUCE_HOSPITAL_CAPACITY = "REDUCE_HOSPITAL_CAPACITY"
    NEW_EMERGENCY = "NEW_EMERGENCY"
    SET_CELL = "SET_CELL"
    FLOOD_CELLS = "FLOOD_CELLS"
    # Natural dynamics / system reports
    FIRE_SPREAD = "FIRE_SPREAD"
    FLOOD_RISE = "FLOOD_RISE"
    VICTIM_DECEASED = "VICTIM_DECEASED"
    SITUATION_REPORT = "SITUATION_REPORT"


USER_EVENT_TYPES = {
    EventType.BLOCK_ROAD,
    EventType.CLEAR_ROAD,
    EventType.START_FIRE,
    EventType.ADD_VICTIM,
    EventType.REMOVE_AMBULANCE,
    EventType.REDUCE_HOSPITAL_CAPACITY,
    EventType.NEW_EMERGENCY,
    EventType.SET_CELL,
    EventType.FLOOD_CELLS,
}

EDITABLE_CELL_TYPES = {CellType.ROAD, CellType.BUILDING, CellType.OBSTACLE, CellType.FIRE, CellType.WATER}


class EventError(ValueError):
    """Raised when an event cannot be applied (invalid target, nothing to do...)."""


@dataclass
class DisasterEvent:
    type: EventType
    target: Pos | None = None
    params: dict = field(default_factory=dict)
    source: str = "USER"  # USER | SCENARIO | NATURAL
    label: str | None = None  # narrative name, e.g. "Aftershock"


@dataclass
class EnvironmentReport:
    tick: int
    event_type: EventType
    source: str
    title: str
    description: str
    cells: list[Pos] = field(default_factory=list)
    victim_ids: list[str] = field(default_factory=list)
    unit_ids: list[str] = field(default_factory=list)
    hospital_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "event_type": self.event_type.value,
            "source": self.source,
            "title": self.title,
            "description": self.description,
            "cells": [list(c) for c in self.cells],
            "victim_ids": self.victim_ids,
            "unit_ids": self.unit_ids,
            "hospital_ids": self.hospital_ids,
        }


@dataclass
class RouteHint:
    """Public information about an active route, used to auto-target events."""

    unit_id: str
    path: list[Pos]  # remaining cells, starting at the unit
    victim_id: str | None = None
    destination_id: str | None = None
    active: bool = True  # the leg the unit is driving right now


VICTIM_TEMPLATES: dict[Severity, dict] = {
    Severity.CRITICAL: {"health": (36, 48), "rescue_time": (3, 4), "icu": True},
    Severity.HIGH: {"health": (50, 64), "rescue_time": (2, 3), "icu": False},
    Severity.MEDIUM: {"health": (65, 80), "rescue_time": (2, 2), "icu": False},
    Severity.LOW: {"health": (85, 95), "rescue_time": (1, 1), "icu": False},
}


# ---------------------------------------------------------------- helpers
def make_victim(
    world: World,
    pos: Pos,
    severity: Severity,
    trapped: bool | None = None,
    reported: bool = True,
) -> Victim:
    tpl = VICTIM_TEMPLATES[severity]
    rng = world.rng
    victim = Victim(
        id=world.next_victim_id(),
        pos=pos,
        severity=severity,
        health=float(rng.randint(*tpl["health"])),
        rescue_time=rng.randint(*tpl["rescue_time"]),
        trapped=rng.random() < 0.4 if trapped is None else trapped,
        needs_icu=tpl["icu"],
        reported=reported,
        reported_tick=world.tick,
        status=VictimStatus.WAITING if reported else VictimStatus.UNREPORTED,
    )
    world.victims[victim.id] = victim
    return victim


def _check_target(world: World, pos: Pos | None) -> Pos:
    if pos is None:
        raise EventError("this event needs a target cell")
    pos = (int(pos[0]), int(pos[1]))
    if not world.grid.in_bounds(pos):
        raise EventError(f"cell {pos} is outside the grid")
    return pos


def _occupied(world: World) -> set[Pos]:
    cells = world.unit_positions() | world.infrastructure_cells()
    cells |= {v.pos for v in world.victims.values() if v.is_active or v.status == VictimStatus.UNREPORTED}
    return cells


def _ground_reachable(world: World, start: Pos, goal: Pos, blocked: Pos | None = None) -> bool:
    """Uninformed reachability check on the true map (used only for targeting)."""
    if start == goal:
        return True
    seen = {start}
    queue = deque([start])
    while queue:
        p = queue.popleft()
        for n in world.grid.neighbors4(p):
            if n in seen or n == blocked:
                continue
            if not GROUND_VEHICLE.passable(world.grid.type_at(n)):
                continue
            if n == goal:
                return True
            seen.add(n)
            queue.append(n)
    return False


def _severity(value, world: World) -> Severity:
    if value is None or value == "RANDOM":
        return world.rng.choices(
            [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW], weights=[3, 3, 3, 1]
        )[0]
    try:
        return Severity(str(value).upper())
    except ValueError as exc:
        raise EventError(f"unknown severity '{value}'") from exc


def _random_road(world: World, avoid: set[Pos]) -> Pos:
    roads = [p for p in world.grid.cells_of_type(CellType.ROAD) if p not in avoid and world.grid.danger_at(p) < 0.3]
    anchors = [h.pos for h in world.hospitals.values()] or world.bases
    world.rng.shuffle(roads)
    for p in roads:
        if any(_ground_reachable(world, a, p) for a in anchors):
            return p
    raise EventError("no free reachable road cell available")


# -------------------------------------------------------------- targeting
def _auto_block_target(world: World, hints: list[RouteHint]) -> Pos | None:
    occupied = _occupied(world)
    ordered = sorted(hints, key=lambda h: (h.active, len(h.path)), reverse=True)
    for hint in ordered:
        path = hint.path
        if len(path) < 6:
            continue
        # Prefer a cell ~40% along the route, but at least 3 steps ahead of the unit.
        ideal = max(3, int(len(path) * 0.4))
        indices = sorted(range(3, len(path) - 2), key=lambda i: abs(i - ideal))
        for i in indices:
            cell = path[i]
            if world.grid.type_at(cell) != CellType.ROAD or cell in occupied:
                continue
            # Only block where a detour exists, so the demo shows re-routing.
            if _ground_reachable(world, path[0], path[-1], blocked=cell):
                return cell
    return None


def _auto_fire_target(world: World, hints: list[RouteHint]) -> Pos | None:
    occupied = _occupied(world)
    for hint in sorted(hints, key=lambda h: (h.active, len(h.path)), reverse=True):
        path = hint.path
        for cell in path[len(path) // 3 : len(path) - 2]:
            for n in world.grid.neighbors4(cell):
                if world.grid.type_at(n) == CellType.BUILDING and n not in occupied:
                    return n
    return None


# ------------------------------------------------------------------ apply
def apply_event(world: World, event: DisasterEvent, hints: list[RouteHint] | None = None) -> EnvironmentReport:
    hints = hints or []
    handler = _HANDLERS.get(event.type)
    if handler is None:
        raise EventError(f"event type {event.type.value} cannot be triggered directly")
    report = handler(world, event, hints)
    if event.label:
        report.title = f"{event.label}: {report.title}"
    return report


def _report(world: World, event: DisasterEvent, title: str, description: str, **kw) -> EnvironmentReport:
    return EnvironmentReport(
        tick=world.tick, event_type=event.type, source=event.source, title=title, description=description, **kw
    )


def _block_road(world: World, event: DisasterEvent, hints: list[RouteHint]) -> EnvironmentReport:
    target = event.target
    if target is None:
        target = _auto_block_target(world, hints)
        if target is None:
            target = _random_road(world, _occupied(world))
    pos = _check_target(world, target)
    if world.grid.type_at(pos) != CellType.ROAD:
        raise EventError(f"cell {pos} is {world.grid.type_at(pos).value}, not a road")
    if pos in _occupied(world):
        raise EventError(f"cell {pos} is occupied by a unit, victim or facility")
    world.grid.set_type(pos, CellType.OBSTACLE)
    return _report(world, event, f"Road {pos} blocked", f"Debris has blocked the road at {pos}.", cells=[pos])


def _clear_road(world: World, event: DisasterEvent, _hints: list[RouteHint]) -> EnvironmentReport:
    pos = _check_target(world, event.target)
    previous = world.grid.type_at(pos)
    if previous not in (CellType.OBSTACLE, CellType.FIRE):
        raise EventError(f"cell {pos} is {previous.value}; only debris or fire can be cleared")
    world.grid.set_type(pos, CellType.ROAD)
    world.hidden_hazards.pop(pos, None)
    return _report(world, event, f"Road {pos} cleared", f"{previous.value.title()} at {pos} cleared; road reopened.", cells=[pos])


def _start_fire(world: World, event: DisasterEvent, hints: list[RouteHint]) -> EnvironmentReport:
    target = event.target or _auto_fire_target(world, hints)
    if target is None:
        buildings = world.grid.cells_of_type(CellType.BUILDING)
        if not buildings:
            raise EventError("no building available to ignite")
        target = world.rng.choice(buildings)
    pos = _check_target(world, target)
    if world.grid.type_at(pos) in PROTECTED_TYPES | {CellType.WATER}:
        raise EventError(f"cell {pos} ({world.grid.type_at(pos).value}) cannot catch fire")
    if pos in world.unit_positions():
        raise EventError(f"a unit is standing on {pos}")
    cells = [pos]
    world.grid.set_type(pos, CellType.FIRE, recompute=False)
    # The blaze immediately engulfs one neighbouring road/building cell.
    occupied = _occupied(world)
    neighbours = [n for n in world.grid.neighbors4(pos) if world.grid.type_at(n) in (CellType.ROAD, CellType.BUILDING) and n not in occupied]
    neighbours.sort(key=lambda n: world.grid.type_at(n) != CellType.ROAD)  # roads first: fires block routes
    for n in neighbours[: int(event.params.get("spread", 1))]:
        world.grid.set_type(n, CellType.FIRE, recompute=False)
        cells.append(n)
    world.grid.recompute_danger()
    return _report(world, event, f"Fire started at {pos}", f"Fire broke out at {pos} ({len(cells)} cells burning).", cells=cells)


def _add_victim(world: World, event: DisasterEvent, _hints: list[RouteHint]) -> EnvironmentReport:
    occupied = _occupied(world)
    pos = _check_target(world, event.target) if event.target is not None else _random_road(world, occupied)
    if world.grid.type_at(pos) != CellType.ROAD:
        raise EventError(f"victims can only be placed on road cells; {pos} is {world.grid.type_at(pos).value}")
    if any(v.pos == pos and v.is_active for v in world.victims.values()):
        raise EventError(f"a victim is already waiting at {pos}")
    severity = _severity(event.params.get("severity"), world)
    trapped = event.params.get("trapped")
    victim = make_victim(world, pos, severity, trapped=None if trapped is None else bool(trapped))
    return _report(
        world,
        event,
        f"New victim {victim.id} reported",
        f"{severity.value} victim {victim.id} at {pos}{' (trapped)' if victim.trapped else ''}.",
        cells=[pos],
        victim_ids=[victim.id],
    )


def _remove_ambulance(world: World, event: DisasterEvent, hints: list[RouteHint]) -> EnvironmentReport:
    unit_id = event.params.get("unit_id")
    if unit_id is None:
        busy = [h.unit_id for h in hints if h.unit_id in world.ambulances]
        empty_busy = [u for u in busy if not world.ambulances[u].carrying and world.ambulances[u].available]
        candidates = empty_busy or [u for u in busy if world.ambulances[u].available]
        candidates = candidates or [a.id for a in world.ambulances.values() if a.available]
        if not candidates:
            raise EventError("no available ambulance to take out of service")
        unit_id = candidates[0]
    amb = world.ambulances.get(unit_id)
    if amb is None:
        raise EventError(f"unknown ambulance '{unit_id}'")
    if not amb.available:
        raise EventError(f"{unit_id} is already out of service")
    amb.available = False
    amb.status = UnitStatus.OUT_OF_SERVICE
    dropped = list(amb.carrying)
    for vid in dropped:
        v = world.victims[vid]
        v.carrier_id = None
        v.pos = amb.pos
        v.extracted = True
        v.status = VictimStatus.WAITING
        v.destination_id = None
        v.rescue_progress = 0
    amb.carrying.clear()
    extra = f" Patients {', '.join(dropped)} left at {amb.pos}." if dropped else ""
    return _report(
        world,
        event,
        f"Ambulance {unit_id} out of service",
        f"{unit_id} suffered a breakdown at {amb.pos} and is unavailable.{extra}",
        unit_ids=[unit_id],
        victim_ids=dropped,
    )


def _reduce_hospital(world: World, event: DisasterEvent, hints: list[RouteHint]) -> EnvironmentReport:
    hid = event.params.get("hospital_id")
    if hid is None:
        counts: dict[str, int] = {}
        for h in hints:
            if h.destination_id in world.hospitals:
                counts[h.destination_id] = counts.get(h.destination_id, 0) + 1
        if counts:
            hid = max(sorted(counts), key=lambda k: counts[k])
        else:
            hid = max(sorted(world.hospitals), key=lambda k: world.hospitals[k].er_free + world.hospitals[k].icu_free)
    hosp = world.hospitals.get(hid)
    if hosp is None:
        raise EventError(f"unknown hospital '{hid}'")
    er_cut = int(event.params.get("er", 3))
    icu_cut = int(event.params.get("icu", hosp.icu_free))
    old = (hosp.er_capacity, hosp.icu_capacity)
    hosp.er_capacity = max(hosp.er_occupancy, hosp.er_capacity - er_cut)
    hosp.icu_capacity = max(hosp.icu_occupancy, hosp.icu_capacity - icu_cut)
    if (hosp.er_capacity, hosp.icu_capacity) == old:
        raise EventError(f"{hid} has no free capacity left to reduce")
    return _report(
        world,
        event,
        f"{hosp.name} capacity reduced",
        f"{hid}: ER {old[0]}->{hosp.er_capacity}, ICU {old[1]}->{hosp.icu_capacity} "
        f"(free now ER {hosp.er_free}, ICU {hosp.icu_free}).",
        hospital_ids=[hid],
    )


def _new_emergency(world: World, event: DisasterEvent, _hints: list[RouteHint]) -> EnvironmentReport:
    occupied = _occupied(world)
    center = _check_target(world, event.target) if event.target is not None else _random_road(world, occupied)
    # Ignite a building next to the incident.
    fire_cells: list[Pos] = []
    ring = sorted(
        (p for p in world.grid.positions() if abs(p[0] - center[0]) + abs(p[1] - center[1]) <= 2),
        key=lambda p: abs(p[0] - center[0]) + abs(p[1] - center[1]),
    )
    for p in ring:
        if world.grid.type_at(p) == CellType.BUILDING and p not in occupied:
            world.grid.set_type(p, CellType.FIRE)
            fire_cells.append(p)
            break
    # Casualties on nearby road cells, away from the flames.
    spots = [
        p
        for p in sorted(
            (p for p in world.grid.positions() if abs(p[0] - center[0]) + abs(p[1] - center[1]) <= 4),
            key=lambda p: abs(p[0] - center[0]) + abs(p[1] - center[1]),
        )
        if world.grid.type_at(p) == CellType.ROAD and p not in occupied and world.grid.danger_at(p) < 0.6
    ]
    victims = []
    for severity, trapped in ((Severity.CRITICAL, True), (Severity.HIGH, False), (Severity.MEDIUM, False)):
        if not spots:
            break
        pos = spots.pop(0)
        victims.append(make_victim(world, pos, severity, trapped=trapped))
    if not victims:
        raise EventError(f"no room for casualties around {center}")
    return _report(
        world,
        event,
        f"Mass-casualty emergency at {center}",
        f"Explosion near {center}: {len(victims)} casualties ({', '.join(v.id for v in victims)})"
        + (f", fire at {fire_cells[0]}." if fire_cells else "."),
        cells=fire_cells + [v.pos for v in victims],
        victim_ids=[v.id for v in victims],
    )


def _set_cell(world: World, event: DisasterEvent, _hints: list[RouteHint]) -> EnvironmentReport:
    pos = _check_target(world, event.target)
    try:
        new_type = CellType(str(event.params.get("cell_type", "")).upper())
    except ValueError as exc:
        raise EventError(f"unknown cell type '{event.params.get('cell_type')}'") from exc
    if new_type not in EDITABLE_CELL_TYPES:
        raise EventError(f"cell type {new_type.value} cannot be painted")
    if pos in world.infrastructure_cells():
        raise EventError(f"cell {pos} is a facility and cannot be edited")
    occupied_by_entity = pos in world.unit_positions() or any(v.pos == pos and v.is_active for v in world.victims.values())
    if occupied_by_entity and new_type != CellType.ROAD:
        raise EventError(f"cell {pos} is occupied by a unit or victim")
    previous = world.grid.set_type(pos, new_type)
    world.hidden_hazards.pop(pos, None)
    return _report(world, event, f"Cell {pos} set to {new_type.value}", f"Map edit: {pos} {previous.value} -> {new_type.value}.", cells=[pos])


def _flood_cells(world: World, event: DisasterEvent, _hints: list[RouteHint]) -> EnvironmentReport:
    cells = [tuple(c) for c in event.params.get("cells", [])] or ([event.target] if event.target else [])
    flooded: list[Pos] = []
    occupied = world.unit_positions() | world.infrastructure_cells()
    for c in cells:
        pos = _check_target(world, c)
        if pos in occupied or world.grid.type_at(pos) in PROTECTED_TYPES:
            continue
        if world.grid.type_at(pos) != CellType.WATER:
            world.grid.set_type(pos, CellType.WATER, recompute=False)
            flooded.append(pos)
    if not flooded:
        raise EventError("no cell could be flooded")
    world.grid.recompute_danger()
    return _report(world, event, f"Flooding: {len(flooded)} cells submerged", f"Water now covers {', '.join(map(str, flooded))}.", cells=flooded)


_HANDLERS = {
    EventType.BLOCK_ROAD: _block_road,
    EventType.CLEAR_ROAD: _clear_road,
    EventType.START_FIRE: _start_fire,
    EventType.ADD_VICTIM: _add_victim,
    EventType.REMOVE_AMBULANCE: _remove_ambulance,
    EventType.REDUCE_HOSPITAL_CAPACITY: _reduce_hospital,
    EventType.NEW_EMERGENCY: _new_emergency,
    EventType.SET_CELL: _set_cell,
    EventType.FLOOD_CELLS: _flood_cells,
}


# ------------------------------------------------------- natural dynamics
def spread_fire(world: World) -> EnvironmentReport | None:
    dyn = world.dynamics
    fires = world.grid.cells_of_type(CellType.FIRE)
    if not fires or len(fires) >= dyn.max_fire_cells:
        return None
    occupied = world.unit_positions() | world.infrastructure_cells()
    candidates: list[Pos] = []
    seen: set[Pos] = set()
    for f in fires:
        for n in world.grid.neighbors4(f):
            if n in seen or n in occupied:
                continue
            seen.add(n)
            t = world.grid.type_at(n)
            if t == CellType.BUILDING and world.rng.random() < dyn.fire_spread_probability:
                candidates.append(n)
            elif t == CellType.ROAD and world.rng.random() < dyn.fire_spread_probability * 0.4:
                candidates.append(n)
    room = dyn.max_fire_cells - len(fires)
    new_cells = candidates[: min(room, 4)]
    if not new_cells:
        return None
    for c in new_cells:
        world.grid.set_type(c, CellType.FIRE, recompute=False)
    world.grid.recompute_danger()
    return EnvironmentReport(
        tick=world.tick,
        event_type=EventType.FIRE_SPREAD,
        source="NATURAL",
        title=f"Fire spread to {len(new_cells)} cell(s)",
        description="Fire front advanced to " + ", ".join(map(str, new_cells)) + ".",
        cells=new_cells,
    )


def rise_flood(world: World) -> EnvironmentReport | None:
    dyn = world.dynamics
    occupied = world.unit_positions() | world.infrastructure_cells()
    occupied |= {v.pos for v in world.victims.values() if v.is_active}
    frontier = sorted(
        p
        for p in dyn.flood_prone
        if world.grid.type_at(p) != CellType.WATER
        and p not in occupied
        and any(world.grid.type_at(n) == CellType.WATER for n in world.grid.neighbors4(p))
    )
    if not frontier:
        return None
    world.rng.shuffle(frontier)
    new_cells = frontier[: dyn.flood_cells_per_rise]
    for c in new_cells:
        world.grid.set_type(c, CellType.WATER, recompute=False)
    world.grid.recompute_danger()
    return EnvironmentReport(
        tick=world.tick,
        event_type=EventType.FLOOD_RISE,
        source="NATURAL",
        title=f"Flood water rising ({len(new_cells)} cell(s))",
        description="Water now covers " + ", ".join(map(str, new_cells)) + ".",
        cells=new_cells,
    )
