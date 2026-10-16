"""Goal-based hierarchical (HTN-style) mission planner.

The top-level goal MISSION ("rescue every reported victim, critical first, and
deliver them to suitable care") is decomposed into one compound task
RESCUE_VICTIM(v) per victim. Each compound task is refined by a *method*; the
method and its parameters (which ambulance / team / hospital) are chosen by the
CSP resource allocator:

  AMBULANCE_DIRECT(v, A, H)
      Assign -> Navigate(A->v) -> Rescue(stabilise+load) -> Select hospital
      -> Transport(A->H) -> Deliver -> Update resources
  EXTRACT_AND_TRANSPORT(v, T, A, H)
      Assign -> Navigate(T->v) -> Extract(T) -> Release T
             -> Navigate(A->v) -> Load (after Extract) -> Select hospital
             -> Transport(A->H) -> Deliver -> Update resources
  TEAM_EVACUATE(v, T, D)
      Assign -> Navigate(T->v) -> Rescue(extract+carry) -> Select destination
      -> Transport(T->D) -> Deliver -> Update resources
  EXTRACT_ONLY(v, T)                      (partial plan when no ambulance is free)
      Assign -> Navigate(T->v) -> Extract -> Release T; the victim returns to
      the goal queue, extracted, for transport in a later allocation round

Patients that share a multi-seat ambulance are merged into one trip: the
ambulance picks them up in the cheapest order and the shared Transport /
Deliver / Update tasks appear (as mirrors) in every victim's sub-tree.

Primitive tasks are also queued, in execution order, on each unit's agenda.
Movement tasks get concrete paths from the agent's search algorithm.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from app.csp.allocation import (
    METHOD_DIRECT,
    METHOD_EVACUATE,
    METHOD_EXTRACT,
    METHOD_EXTRACT_ONLY,
    AllocationOption,
)
from app.environment.grid import Grid
from app.environment.mobility import MobilityProfile, profile_for
from app.environment.world import World
from app.models.entities import Pos, Severity, Unit, Victim
from app.search.base import SearchResult


class TaskKind(str, Enum):
    MISSION = "MISSION"
    IDENTIFY_VICTIMS = "IDENTIFY_VICTIMS"
    RESCUE_VICTIM = "RESCUE_VICTIM"
    ASSIGN_RESOURCES = "ASSIGN_RESOURCES"
    NAVIGATE = "NAVIGATE"
    EXTRACT = "EXTRACT"
    RESCUE = "RESCUE"
    SELECT_DESTINATION = "SELECT_DESTINATION"
    TRANSPORT = "TRANSPORT"
    DELIVER = "DELIVER"
    UPDATE_RESOURCES = "UPDATE_RESOURCES"
    CHECK_GOALS = "CHECK_GOALS"
    REPLAN = "REPLAN"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


MOVEMENT_KINDS = {TaskKind.NAVIGATE, TaskKind.TRANSPORT}
ON_SCENE_KINDS = {TaskKind.EXTRACT, TaskKind.RESCUE}
INSTANT_KINDS = {TaskKind.ASSIGN_RESOURCES, TaskKind.SELECT_DESTINATION, TaskKind.UPDATE_RESOURCES}
OPEN_STATUSES = {TaskStatus.PENDING, TaskStatus.ACTIVE}

# A patient already on board must not ride along on a pickup detour longer than
# TRIP_DETOUR_RATIO x (direct cost to the hospital) + TRIP_DETOUR_MARGIN.
TRIP_DETOUR_RATIO = 2.0
TRIP_DETOUR_MARGIN = 12.0


@dataclass(eq=False)
class PlanTask:
    id: str
    kind: TaskKind
    label: str
    status: TaskStatus = TaskStatus.PENDING
    mission_id: str | None = None
    unit_id: str | None = None
    victim_ids: list[str] = field(default_factory=list)
    target: Pos | None = None
    target_id: str | None = None
    path: list[Pos] = field(default_factory=list)
    path_index: int = 0
    path_cost: float = 0.0
    step_costs: list[float] = field(default_factory=list)
    algorithm: str | None = None
    nodes_expanded: int = 0
    duration: int = 0
    progress: int = 0
    depends_on: list["PlanTask"] = field(default_factory=list)
    children: list["PlanTask"] = field(default_factory=list)
    mirrors: list["PlanTask"] = field(default_factory=list)
    mirror_of: "PlanTask | None" = None
    replans: int = 0
    needs_route: bool = False
    note: str = ""

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def remaining_path(self) -> list[Pos]:
        return self.path[self.path_index :] if self.status == TaskStatus.ACTIVE else list(self.path)

    def set_status(self, status: TaskStatus) -> None:
        self.status = status
        for m in self.mirrors:
            m.status = status

    def sync_mirrors(self) -> None:
        for m in self.mirrors:
            m.status = self.status
            m.label = self.label
            m.target = self.target
            m.target_id = self.target_id
            m.replans = self.replans
            m.path_cost = self.path_cost
            m.note = self.note

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind.value,
            "label": self.label,
            "status": self.status.value,
            "unit_id": self.unit_id,
            "victim_ids": list(self.victim_ids),
            "target": list(self.target) if self.target else None,
            "replans": self.replans,
            "note": self.note,
            "shared": self.mirror_of is not None,
            "children": [c.to_dict() for c in self.children],
        }
        if self.kind in MOVEMENT_KINDS:
            data["path_cost"] = round(self.path_cost, 2)
            data["steps"] = max(0, len(self.path) - 1)
            data["algorithm"] = self.algorithm
        if self.kind in ON_SCENE_KINDS:
            data["duration"] = self.duration
            data["progress"] = self.progress
        return data


class PlanningError(RuntimeError):
    pass


RouteFn = Callable[[Pos, Pos, MobilityProfile, str], SearchResult]


@dataclass
class MissionPlan:
    option_by_victim: dict[str, AllocationOption]
    roots: dict[str, PlanTask]
    agendas: dict[str, list[PlanTask]]
    method: str
    failed: str | None = None


class HierarchicalPlanner:
    def __init__(self) -> None:
        self._ids = itertools.count(1)

    # ------------------------------------------------------------ helpers
    def task(self, kind: TaskKind, label: str, **kw) -> PlanTask:
        return PlanTask(id=f"T{next(self._ids)}", kind=kind, label=label, **kw)

    def _movement(
        self,
        kind: TaskKind,
        unit: Unit,
        start: Pos,
        goal: Pos,
        label: str,
        mission_id: str,
        grid: Grid,
        route: RouteFn,
        target_id: str | None = None,
    ) -> PlanTask:
        profile = profile_for(unit)
        res = route(start, goal, profile, label)
        if not res.found:
            raise PlanningError(f"no route for {unit.id} from {start} to {goal}")
        task = self.task(kind, label, mission_id=mission_id, unit_id=unit.id, target=goal, target_id=target_id)
        assign_path(task, res, grid, profile)
        return task

    def _mirror(self, primary: PlanTask, mission_id: str) -> PlanTask:
        m = self.task(
            primary.kind,
            primary.label,
            status=primary.status,
            mission_id=mission_id,
            unit_id=primary.unit_id,
            victim_ids=primary.victim_ids,
            target=primary.target,
            target_id=primary.target_id,
            path_cost=primary.path_cost,
            mirror_of=primary,
        )
        primary.mirrors.append(m)
        return m

    # ----------------------------------------------------------- planning
    def plan_round(
        self,
        assignments: list[tuple[Victim, AllocationOption]],
        world: World,
        grid: Grid,
        route: RouteFn,
    ) -> list[MissionPlan]:
        """Decompose every (victim, method) pair chosen by the CSP into tasks."""
        trips: dict[str, list[tuple[Victim, AllocationOption]]] = {}
        singles: list[tuple[Victim, AllocationOption]] = []
        for victim, opt in assignments:
            if opt.ambulance and victim.severity != Severity.CRITICAL:
                trips.setdefault(opt.ambulance, []).append((victim, opt))
            else:
                singles.append((victim, opt))
        for amb_id in list(trips):
            if len(trips[amb_id]) == 1:
                singles.append(trips.pop(amb_id)[0])

        plans: list[MissionPlan] = []
        for victim, opt in singles:
            plans.append(self._safe(lambda v=victim, o=opt: self._single(v, o, world, grid, route), {victim.id: opt}))
        for amb_id, group in trips.items():
            opts = {v.id: o for v, o in group}
            try:
                plans.extend(self._shared_trip(group, world, grid, route))
            except PlanningError as exc:
                plans.append(MissionPlan(opts, {}, {}, group[0][1].method, failed=str(exc)))
        return plans

    def _safe(self, build: Callable[[], MissionPlan], opts: dict[str, AllocationOption]) -> MissionPlan:
        try:
            return build()
        except PlanningError as exc:
            method = next(iter(opts.values())).method
            return MissionPlan(opts, {}, {}, method, failed=str(exc))

    # ---------------------------------------------------- single-victim
    def _single(self, v: Victim, opt: AllocationOption, world: World, grid: Grid, route: RouteFn) -> MissionPlan:
        root = self.task(
            TaskKind.RESCUE_VICTIM,
            f"Rescue Victim {v.id} [{v.severity.value}]",
            status=TaskStatus.ACTIVE,
            mission_id=v.id,
            victim_ids=[v.id],
            target=v.pos,
            note=f"method {opt.method}",
        )
        agendas: dict[str, list[PlanTask]] = {}
        if opt.method == METHOD_EXTRACT_ONLY:
            team = world.teams[opt.team]
            assign = self.task(
                TaskKind.ASSIGN_RESOURCES, f"Assign Team {team.id} ({team.capability.value}) - extraction only",
                status=TaskStatus.DONE, mission_id=v.id, note="no ambulance free: partial plan chosen by CSP",
            )
            nav = self._movement(TaskKind.NAVIGATE, team, team.pos, v.pos, f"Navigate {team.id} -> {v.id}", v.id, grid, route)
            extract = self.task(
                TaskKind.EXTRACT, f"Extract {v.id} ({team.id})", mission_id=v.id, unit_id=team.id,
                victim_ids=[v.id], target=v.pos, duration=v.rescue_time,
            )
            release = self.task(TaskKind.UPDATE_RESOURCES, f"Release {team.id} · {v.id} awaits an ambulance", mission_id=v.id, unit_id=team.id)
            root.children += [assign, nav, extract, release]
            root.note = f"method {opt.method} · transport planned in a later round"
            agendas[team.id] = [nav, extract, release]
            return MissionPlan({v.id: opt}, {v.id: root}, agendas, opt.method)

        dest = world.destination(opt.destination)
        is_hospital = opt.destination in world.hospitals

        if opt.method in (METHOD_DIRECT, METHOD_EXTRACT):
            amb = world.ambulances[opt.ambulance]
            team = world.teams[opt.team] if opt.team else None
            who = f"Ambulance {amb.id} ({amb.medical.value})" + (f" + Team {team.id} ({team.capability.value})" if team else "")
            assign = self.task(TaskKind.ASSIGN_RESOURCES, f"Assign {who}", status=TaskStatus.DONE, mission_id=v.id, note="chosen by CSP")
            root.children.append(assign)
            extract = None
            if team is not None:
                nav_t = self._movement(TaskKind.NAVIGATE, team, team.pos, v.pos, f"Navigate {team.id} -> {v.id}", v.id, grid, route)
                extract = self.task(
                    TaskKind.EXTRACT, f"Extract {v.id} ({team.id})", mission_id=v.id, unit_id=team.id,
                    victim_ids=[v.id], target=v.pos, duration=v.rescue_time,
                )
                release = self.task(TaskKind.UPDATE_RESOURCES, f"Release {team.id}", mission_id=v.id, unit_id=team.id)
                root.children += [nav_t, extract, release]
                agendas[team.id] = [nav_t, extract, release]
            nav_a = self._movement(TaskKind.NAVIGATE, amb, amb.pos, v.pos, f"Navigate {amb.id} -> {v.id}", v.id, grid, route)
            load = self.task(
                TaskKind.RESCUE,
                f"Load {v.id} into {amb.id}" if extract else f"Stabilise & load {v.id}",
                mission_id=v.id, unit_id=amb.id, victim_ids=[v.id], target=v.pos,
                duration=1 if extract else v.rescue_time,
                depends_on=[extract] if extract else [],
            )
            select = self._select_destination(v, dest.id, dest.name, is_hospital)
            transport = self._movement(TaskKind.TRANSPORT, amb, v.pos, dest.pos, f"Transport {v.id} -> {dest.id}", v.id, grid, route, target_id=dest.id)
            transport.victim_ids = [v.id]
            deliver = self._deliver(amb.id, [v.id], dest.id, dest.name, dest.pos, v.id)
            update = self.task(TaskKind.UPDATE_RESOURCES, f"Release {amb.id} · update {dest.id} beds", mission_id=v.id, unit_id=amb.id)
            root.children += [nav_a, load, select, transport, deliver, update]
            agendas[amb.id] = [nav_a, load, transport, deliver, update]
        elif opt.method == METHOD_EVACUATE:
            team = world.teams[opt.team]
            assign = self.task(
                TaskKind.ASSIGN_RESOURCES, f"Assign Team {team.id} ({team.capability.value})",
                status=TaskStatus.DONE, mission_id=v.id, note="chosen by CSP",
            )
            nav = self._movement(TaskKind.NAVIGATE, team, team.pos, v.pos, f"Navigate {team.id} -> {v.id}", v.id, grid, route)
            rescue = self.task(
                TaskKind.RESCUE, f"Rescue {v.id} (extract & carry)", mission_id=v.id, unit_id=team.id,
                victim_ids=[v.id], target=v.pos, duration=v.rescue_time,
            )
            select = self._select_destination(v, dest.id, dest.name, is_hospital)
            transport = self._movement(TaskKind.TRANSPORT, team, v.pos, dest.pos, f"Escort {v.id} -> {dest.id}", v.id, grid, route, target_id=dest.id)
            transport.victim_ids = [v.id]
            deliver = self._deliver(team.id, [v.id], dest.id, dest.name, dest.pos, v.id)
            update = self.task(TaskKind.UPDATE_RESOURCES, f"Release {team.id}", mission_id=v.id, unit_id=team.id)
            root.children += [assign, nav, rescue, select, transport, deliver, update]
            agendas[team.id] = [nav, rescue, transport, deliver, update]
        else:
            raise PlanningError(f"no decomposition method for {opt.method}")
        return MissionPlan({v.id: opt}, {v.id: root}, agendas, opt.method)

    def _select_destination(self, v: Victim, dest_id: str, name: str, is_hospital: bool) -> PlanTask:
        if is_hospital:
            reason = "ICU bed reserved" if v.needs_icu else "ER bed reserved"
            label = f"Select hospital {dest_id} ({name})"
        else:
            reason = "evacuation point"
            label = f"Select safe zone {dest_id} ({name})"
        return self.task(TaskKind.SELECT_DESTINATION, label, status=TaskStatus.DONE, mission_id=v.id, target_id=dest_id, note=reason)

    def _deliver(self, unit_id: str, victims: list[str], dest_id: str, name: str, pos: Pos, mission_id: str) -> PlanTask:
        return self.task(
            TaskKind.DELIVER, f"Deliver {'+'.join(victims)} to {name}", mission_id=mission_id, unit_id=unit_id,
            victim_ids=list(victims), target=pos, target_id=dest_id,
        )

    # ------------------------------------------------------ shared trips
    def _shared_trip(
        self, group: list[tuple[Victim, AllocationOption]], world: World, grid: Grid, route: RouteFn
    ) -> list[MissionPlan]:
        amb = world.ambulances[group[0][1].ambulance]
        dest_id = group[0][1].destination
        dest = world.destination(dest_id)
        profile = profile_for(amb)

        # Choose the cheapest pick-up order (exhaustive over permutations).
        best_order, best_cost, best_legs = None, float("inf"), []
        for order in itertools.permutations(group):
            stops = [amb.pos] + [v.pos for v, _ in order] + [dest.pos]
            legs: list[float] = []
            for a, b in zip(stops, stops[1:]):
                res = route(a, b, profile, "trip ordering")
                if not res.found:
                    legs = []
                    break
                legs.append(res.cost)
            if legs and sum(legs) < best_cost:
                best_order, best_cost, best_legs = order, sum(legs), legs
        if best_order is None:
            raise PlanningError(f"no feasible pick-up order for {amb.id}")

        # Merging is only worth it if the first patient is not dragged on a long detour.
        first = best_order[0][0]
        direct = route(first.pos, dest.pos, profile, "trip ordering")
        onboard_cost = sum(best_legs[1:])
        if direct.found and onboard_cost > direct.cost * TRIP_DETOUR_RATIO + TRIP_DETOUR_MARGIN:
            # Split the trip: the highest-priority patient keeps the ambulance.
            keep_victim, keep_opt = max(group, key=lambda vo: (vo[0].priority, vo[0].id))
            reason = (
                f"shared trip rejected: {first.id} would ride {onboard_cost:.0f} instead of {direct.cost:.0f} - "
                f"{amb.id} takes {keep_victim.id} (highest priority) alone; the other pick-up waits for the next round"
            )
            plans = [self._single(keep_victim, keep_opt, world, grid, route)]
            for victim, opt in group:
                if victim.id != keep_victim.id:
                    plans.append(MissionPlan({victim.id: opt}, {}, {}, opt.method, failed=reason))
            return plans

        ids = [v.id for v, _ in best_order]
        roots: dict[str, PlanTask] = {}
        agendas: dict[str, list[PlanTask]] = {amb.id: []}
        prev = amb.pos
        for victim, opt in best_order:
            root = self.task(
                TaskKind.RESCUE_VICTIM, f"Rescue Victim {victim.id} [{victim.severity.value}]",
                status=TaskStatus.ACTIVE, mission_id=victim.id, victim_ids=[victim.id], target=victim.pos,
                note=f"method {opt.method} · shared trip {'+'.join(ids)}",
            )
            roots[victim.id] = root
            root.children.append(
                self.task(TaskKind.ASSIGN_RESOURCES, f"Assign Ambulance {amb.id} ({amb.medical.value}, shared trip)",
                          status=TaskStatus.DONE, mission_id=victim.id, note="chosen by CSP")
            )
            extract = None
            if opt.team:
                team = world.teams[opt.team]
                nav_t = self._movement(TaskKind.NAVIGATE, team, team.pos, victim.pos, f"Navigate {team.id} -> {victim.id}", victim.id, grid, route)
                extract = self.task(TaskKind.EXTRACT, f"Extract {victim.id} ({team.id})", mission_id=victim.id, unit_id=team.id,
                                    victim_ids=[victim.id], target=victim.pos, duration=victim.rescue_time)
                release = self.task(TaskKind.UPDATE_RESOURCES, f"Release {team.id}", mission_id=victim.id, unit_id=team.id)
                root.children += [nav_t, extract, release]
                agendas[team.id] = [nav_t, extract, release]
            nav = self._movement(TaskKind.NAVIGATE, amb, prev, victim.pos, f"Navigate {amb.id} -> {victim.id}", victim.id, grid, route)
            load = self.task(
                TaskKind.RESCUE, f"Load {victim.id} into {amb.id}" if extract else f"Stabilise & load {victim.id}",
                mission_id=victim.id, unit_id=amb.id, victim_ids=[victim.id], target=victim.pos,
                duration=1 if extract else victim.rescue_time, depends_on=[extract] if extract else [],
            )
            root.children += [nav, load, self._select_destination(victim, dest.id, dest.name, dest_id in world.hospitals)]
            agendas[amb.id] += [nav, load]
            prev = victim.pos

        transport = self._movement(TaskKind.TRANSPORT, amb, prev, dest.pos, f"Transport {'+'.join(ids)} -> {dest.id}", ids[-1], grid, route, target_id=dest.id)
        transport.victim_ids = list(ids)
        deliver = self._deliver(amb.id, ids, dest.id, dest.name, dest.pos, ids[-1])
        update = self.task(TaskKind.UPDATE_RESOURCES, f"Release {amb.id} · update {dest.id} beds", mission_id=ids[-1], unit_id=amb.id)
        update.victim_ids = list(ids)
        agendas[amb.id] += [transport, deliver, update]
        for vid in ids:
            roots[vid].children += [self._mirror(transport, vid), self._mirror(deliver, vid), self._mirror(update, vid)]
        options = {v.id: o for v, o in best_order}
        return [MissionPlan(options, roots, agendas, group[0][1].method)]


def assign_path(task: PlanTask, res: SearchResult, grid: Grid, profile: MobilityProfile) -> None:
    """Attach a search result's path to a movement task."""
    task.path = list(res.path)
    task.path_index = 0
    task.path_cost = res.cost
    task.algorithm = res.algorithm
    task.nodes_expanded = res.nodes_expanded
    task.step_costs = [profile.step_cost(grid, p) or 0.0 for p in res.path[1:]]
    task.needs_route = False
    task.sync_mirrors()
