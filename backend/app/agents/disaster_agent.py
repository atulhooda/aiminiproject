"""The AI Disaster Response Commander - a rational, model-based, goal-based agent.

Agent type (AIMA): model-based, goal-based agent with utility-guided choices.

    PEAS
    Performance : victims rescued (critical first), survival, rescue time,
                  distance travelled, exposure to danger, no constraint violations
    Environment : dynamic, partially observable disaster grid
    Actuators   : MOVE, RESCUE, TRANSPORT, DELIVER, WAIT (per unit), REPLAN
    Sensors     : field/radio reports, unit sensors (radius 2), unit telemetry,
                  hospital status

Every decision cycle runs the same pipeline:

    PERCEIVE -> UPDATE STATE -> IDENTIFY GOALS -> CHECK CONSTRAINTS -> PLAN
             -> SELECT ACTION -> EXECUTE (by the environment) -> OBSERVE RESULT

The agent keeps an internal *belief map* (its model of the world). Hidden road
damage is unknown until a unit's sensors observe it, so planning happens under
the free-space assumption and the agent must replan online.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
from enum import Enum

from app.agents.decision_log import DecisionLog
from app.agents.priority import compute_priority
from app.ml import risk as ml_risk
from app.csp.allocation import (
    DEFER,
    HOLD,
    METHOD_DIRECT,
    METHOD_EXTRACT_ONLY,
    AllocationOption,
    AllocationProblem,
    DestinationItem,
    RouteOracle,
    VictimNeeds,
    assess_needs,
    build_allocation_problem,
    build_destination_problem,
)
from app.csp.constraints import BinaryConstraint, CapacityConstraint, UnaryConstraint, describe_value
from app.csp.solver import BacktrackingSolver, CSPSolution
from app.environment.events import EnvironmentReport, EventType, RouteHint
from app.environment.mobility import GROUND_VEHICLE, MobilityProfile, profile_for
from app.environment.world import World
from app.models.actions import Action, ActionResult, ActionType, RescueMode
from app.models.entities import (
    Ambulance,
    CellType,
    MedicalLevel,
    Pos,
    Severity,
    TeamCapability,
    Unit,
    VictimStatus,
)
from app.planning.planner import (
    INSTANT_KINDS,
    MOVEMENT_KINDS,
    TRIP_DETOUR_MARGIN,
    TRIP_DETOUR_RATIO,
    HierarchicalPlanner,
    MissionPlan,
    PlanTask,
    TaskKind,
    TaskStatus,
    assign_path,
)
from app.search import ALGORITHM_LABELS, ALGORITHMS, SearchResult
from app.search.online import first_blocked_index, path_cost_on

SENSOR_RADIUS = 2
ATTENTION_WINDOW = 6
CSP_NODE_LIMIT = 5000
DEGRADE_RATIO = 1.35
DEGRADE_MARGIN = 2.0
GOAL_HYSTERESIS = 1.0


class AgentPhase(str, Enum):
    PERCEIVE = "PERCEIVE"
    UPDATE_STATE = "UPDATE_STATE"
    IDENTIFY_GOALS = "IDENTIFY_GOALS"
    CHECK_CONSTRAINTS = "CHECK_CONSTRAINTS"
    PLAN = "PLAN"
    SELECT_ACTION = "SELECT_ACTION"
    EXECUTE = "EXECUTE"
    OBSERVE = "OBSERVE"


@dataclass
class CellChange:
    pos: Pos
    old: CellType
    new: CellType
    source: str  # REPORT | SENSOR
    unit_id: str | None = None


@dataclass
class Percept:
    tick: int
    reports: list[EnvironmentReport]
    cell_changes: list[CellChange]
    new_victims: list[str]
    discovered_victims: list[tuple[str, str]]


@dataclass
class Issue:
    kind: str
    detail: str
    unit_id: str | None = None
    victim_id: str | None = None
    hospital_id: str | None = None
    task: PlanTask | None = None
    blocked_cell: Pos | None = None


@dataclass
class Mission:
    victim_id: str
    option: AllocationOption
    root: PlanTask
    created_tick: int
    attempt: int = 1
    status: str = "ACTIVE"  # ACTIVE | COMPLETED | ABORTED
    end_tick: int | None = None
    abort_reason: str | None = None


@dataclass
class AgentMetrics:
    replans: int = 0
    route_replans: int = 0
    reassignments: int = 0
    destination_changes: int = 0
    searches: int = 0
    nodes_expanded: int = 0
    search_time_ms: float = 0.0
    csp_runs: int = 0
    csp_nodes: int = 0
    csp_time_ms: float = 0.0
    missions_created: int = 0
    missions_completed: int = 0
    missions_aborted: int = 0
    hazards_discovered: int = 0
    victims_discovered: int = 0
    actions_executed: int = 0
    failed_actions: int = 0

    def to_dict(self) -> dict:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def _diamond(center: Pos, radius: int, rows: int, cols: int):
    r0, c0 = center
    for r in range(max(0, r0 - radius), min(rows, r0 + radius + 1)):
        span = radius - abs(r - r0)
        for c in range(max(0, c0 - span), min(cols, c0 + span + 1)):
            yield (r, c)


class DisasterResponseAgent:
    def __init__(self, world: World, algorithm: str = "ASTAR"):
        self.algorithm = self._validate_algorithm(algorithm)
        # ---- internal model (belief state)
        self.belief = world.grid.copy()
        for pos in world.hidden_hazards:
            self.belief.set_type(pos, CellType.ROAD, recompute=False)
        self.belief.recompute_danger()
        self.belief_version = 0
        self.known_victims: set[str] = {vid for vid, v in world.victims.items() if v.reported}
        self.needs: dict[str, VictimNeeds] = {}
        self.goals: list = []
        # ---- plans
        self.planner = HierarchicalPlanner()
        self.root = PlanTask(
            "M0", TaskKind.MISSION,
            "MISSION: Rescue all reported victims (critical first) and deliver them to suitable care",
            status=TaskStatus.ACTIVE,
        )
        self.identify_task = PlanTask("M1", TaskKind.IDENTIFY_VICTIMS, "Identify & prioritise victims", status=TaskStatus.ACTIVE)
        self.check_task = PlanTask("M2", TaskKind.CHECK_GOALS, "Check remaining goals", status=TaskStatus.ACTIVE)
        self.replan_task = PlanTask("M3", TaskKind.REPLAN, "Replan if required", status=TaskStatus.PENDING, note="no replanning needed yet")
        self.root.children = [self.identify_task, self.check_task, self.replan_task]
        self.missions: dict[str, Mission] = {}
        self.mission_history: list[Mission] = []
        self.agendas: dict[str, list[PlanTask]] = {uid: [] for uid in world.units()}
        self.tasks: dict[str, PlanTask] = {}
        self.attempts: dict[str, int] = defaultdict(int)
        # ---- reasoning artefacts exposed to the UI
        self.log = DecisionLog()
        self.metrics = AgentMetrics()
        self.oracle = self._new_oracle()
        self.last_search: dict | None = None
        self.search_history: deque[dict] = deque(maxlen=30)
        self.last_csp: dict | None = None
        self.phase_trace: list[dict] = []
        self.alerts: list[dict] = []
        self.replan_events: list[dict] = []
        self.ai_state = "STANDBY"
        # ---- bookkeeping
        self._tick = world.tick
        self._csp_runs = 0
        self._csp_signature: tuple | None = None
        self._routes_checked_version = -1
        self._agenda_dirty = False
        self._last_action_task: dict[str, str] = {}
        self._resumed_units: set[str] = set()
        self._top_goal: str | None = None
        self._replanned = False
        self._allocated = False
        self._goal_logged = False
        self._first_cycle = True
        self._last_deferred: tuple | None = None
        self._reactive = False
        self._replanned_units: set[str] = set()
        self._pending_resume: set[str] = set()

    # =================================================================
    # Configuration & public helpers
    # =================================================================
    @staticmethod
    def _validate_algorithm(algorithm: str) -> str:
        algo = algorithm.upper()
        if algo not in ALGORITHMS:
            raise ValueError(f"unknown algorithm '{algorithm}'; choose one of {ALGORITHMS}")
        return algo

    def _new_oracle(self) -> RouteOracle:
        return RouteOracle(self.belief, self.algorithm, on_search=self._count_search)

    def _count_search(self, res: SearchResult) -> None:
        self.metrics.searches += 1
        self.metrics.nodes_expanded += res.nodes_expanded
        self.metrics.search_time_ms += res.time_ms

    def preview_priorities(self, world: World) -> None:
        """Score the initially reported victims so the UI can rank them before
        the first decision cycle (no search, no logging)."""
        for vid in self.known_victims:
            v = world.victims[vid]
            v.priority, v.priority_breakdown = compute_priority(v, self.belief, world.tick)

    def set_algorithm(self, algorithm: str) -> None:
        self.algorithm = self._validate_algorithm(algorithm)
        self.oracle = self._new_oracle()
        self._csp_signature = None
        self.log.add(self._tick, "SYSTEM", "INFO", f"Navigation search algorithm set to {ALGORITHM_LABELS[self.algorithm]}")

    @property
    def algorithm_label(self) -> str:
        return ALGORITHM_LABELS[self.algorithm]

    def route_hints(self) -> list[RouteHint]:
        hints: list[RouteHint] = []
        for uid in sorted(self.agendas):
            for t in self.agendas[uid]:
                if t.is_open and t.kind in MOVEMENT_KINDS and not t.needs_route and len(t.remaining_path) > 1:
                    hints.append(
                        RouteHint(
                            unit_id=uid,
                            path=t.remaining_path,
                            victim_id=t.mission_id if t.kind == TaskKind.NAVIGATE else None,
                            destination_id=t.target_id if t.kind == TaskKind.TRANSPORT else None,
                            active=t.status == TaskStatus.ACTIVE,
                        )
                    )
        return hints

    def current_task_labels(self, world: World) -> dict[str, str]:
        out: dict[str, str] = {}
        for uid, unit in sorted(world.units().items()):
            if not unit.available:
                out[uid] = "OUT_OF_SERVICE"
                continue
            task = next((t for t in self.agendas.get(uid, []) if t.is_open and t.kind not in INSTANT_KINDS), None)
            out[uid] = task.label if task else "IDLE"
        return out

    def unit_plans(self, world: World) -> list[dict]:
        """Planned routes and current task per unit (for map rendering)."""
        plans = []
        for uid, unit in sorted(world.units().items()):
            agenda = [t for t in self.agendas.get(uid, []) if t.is_open]
            current = next((t for t in agenda if t.kind not in INSTANT_KINDS), None)
            legs = []
            for t in agenda:
                if t.kind in MOVEMENT_KINDS and t.path:
                    legs.append(
                        {
                            "task_id": t.id,
                            "kind": t.kind.value,
                            "active": t.status == TaskStatus.ACTIVE,
                            "path": [list(p) for p in t.remaining_path],
                            "cost": round(t.path_cost, 2),
                            "replans": t.replans,
                            "label": t.label,
                        }
                    )
            plans.append(
                {
                    "unit_id": uid,
                    "current_task": current.label if current else None,
                    "current_kind": current.kind.value if current else None,
                    "mission": current.mission_id if current else None,
                    "legs": legs,
                    "waiting_for": (
                        [d.label for d in current.depends_on if d.status != TaskStatus.DONE] if current else []
                    ),
                    "holding": bool(current and current.needs_route),
                }
            )
        return plans

    # =================================================================
    # The decision cycle
    # =================================================================
    def decide(self, world: World, reports: list[EnvironmentReport], reactive: bool = False) -> list[Action]:
        """Run PERCEIVE ... SELECT ACTION and return one action per unit.

        `reactive` marks a cycle triggered by an injected event between ticks:
        nothing is executed, so repaired routes simply resume on the next tick.
        In a normal tick a unit whose plan was just repaired spends the tick on
        the REPLAN action.
        """
        self._begin_cycle(world.tick)
        self._reactive = reactive
        percept = self.perceive(world, reports)
        self.update_state(world, percept)
        self.identify_goals(world)
        issues = self.check_constraints(world)
        self.plan(world, issues)
        actions = self.select_actions(world)
        self._first_cycle = False
        self._update_ai_state(world)
        return actions

    def _begin_cycle(self, tick: int) -> None:
        self._tick = tick
        self.phase_trace = []
        self.alerts = []
        self.replan_events = []
        self._replanned = False
        self._allocated = False

    # ----------------------------------------------------------- PERCEIVE
    def perceive(self, world: World, reports: list[EnvironmentReport]) -> Percept:
        changes: list[CellChange] = []
        seen: set[Pos] = set()
        for rep in reports:
            level = "INFO" if rep.event_type == EventType.SITUATION_REPORT else "EVENT"
            self._log(AgentPhase.PERCEIVE, level, f"[{rep.source}] {rep.title}", [rep.description])
            for cell in rep.cells:
                cell = (cell[0], cell[1])
                if cell in seen:
                    continue
                truth, believed = world.grid.type_at(cell), self.belief.type_at(cell)
                if truth != believed:
                    changes.append(CellChange(cell, believed, truth, "REPORT"))
                    seen.add(cell)

        units = [u for _uid, u in sorted(world.units().items()) if u.available]
        for unit in units:  # local sensing - the only way to find hidden hazards
            for cell in _diamond(unit.pos, SENSOR_RADIUS, world.grid.rows, world.grid.cols):
                if cell in seen:
                    continue
                truth, believed = world.grid.type_at(cell), self.belief.type_at(cell)
                if truth != believed:
                    changes.append(CellChange(cell, believed, truth, "SENSOR", unit.id))
                    seen.add(cell)

        new_victims = sorted(vid for vid, v in world.victims.items() if v.reported and vid not in self.known_victims)
        discovered: list[tuple[str, str]] = []
        for vid, v in sorted(world.victims.items()):
            if v.reported or v.status != VictimStatus.UNREPORTED:
                continue
            spotter = next((u.id for u in units if abs(u.pos[0] - v.pos[0]) + abs(u.pos[1] - v.pos[1]) <= SENSOR_RADIUS), None)
            if spotter:
                discovered.append((vid, spotter))

        significant = [r for r in reports if r.event_type != EventType.SITUATION_REPORT]
        if changes or significant or discovered:
            details = [f"{c.pos}: {c.old.value} -> {c.new.value} (" + (f"sensor {c.unit_id}" if c.source == "SENSOR" else "field report") + ")" for c in changes[:8]]
            if len(changes) > 8:
                details.append(f"... and {len(changes) - 8} more cell(s)")
            details += [f"Unreported victim {vid} detected by {uid}" for vid, uid in discovered]
            details += [r.title for r in significant if not r.cells]
            self._log(AgentPhase.PERCEIVE, "ALERT", "ENVIRONMENT CHANGE DETECTED", details)
            headline = significant[0].title if significant else (
                f"{changes[0].new.value} found at {changes[0].pos} by {changes[0].unit_id}" if changes else f"Victim {discovered[0][0]} discovered"
            )
            self._alert("ENV_CHANGE", "ENVIRONMENT CHANGE DETECTED", headline)

        summary = f"{len(reports)} report(s), {len(changes)} map change(s)"
        if discovered:
            summary += f", {len(discovered)} victim(s) discovered"
        self._trace(AgentPhase.PERCEIVE, summary if (reports or changes or discovered) else "no change observed")
        return Percept(world.tick, reports, changes, new_victims, discovered)

    # ------------------------------------------------------- UPDATE STATE
    def update_state(self, world: World, percept: Percept) -> None:
        for ch in percept.cell_changes:
            self.belief.set_type(ch.pos, ch.new, recompute=False)
        if percept.cell_changes:
            self.belief.recompute_danger()
            self.belief_version += 1
            self.oracle = self._new_oracle()
            sensed = [c for c in percept.cell_changes if c.source == "SENSOR"]
            if sensed:
                self.metrics.hazards_discovered += len(sensed)
                self._log(
                    AgentPhase.UPDATE_STATE, "ALERT",
                    f"Unknown terrain revealed by sensors: {len(sensed)} cell(s) differ from the situation report",
                    [f"{c.unit_id} observed {c.new.value} at {c.pos} (map said {c.old.value})" for c in sensed],
                )
            known = self.belief
            self._log(
                AgentPhase.UPDATE_STATE, "INFO",
                f"Belief state updated (map v{self.belief_version}): {len(percept.cell_changes)} cell(s) changed",
                [
                    f"Known blocked roads: {len(known.cells_of_type(CellType.OBSTACLE))}",
                    f"Known fire cells: {len(known.cells_of_type(CellType.FIRE))}",
                    f"Known flooded cells: {len(known.cells_of_type(CellType.WATER))}",
                ],
            )
        elif self.oracle.cache_size > 4000:
            self.oracle = self._new_oracle()

        for vid in percept.new_victims:
            self.known_victims.add(vid)
            v = world.victims[vid]
            self._log(
                AgentPhase.UPDATE_STATE, "INFO",
                f"Victim {vid} added to state: {v.severity.value} at {v.pos}" + (" (trapped)" if v.trapped else ""),
            )
        for vid, uid in percept.discovered_victims:
            v = world.victims[vid]
            v.reported = True
            v.status = VictimStatus.WAITING
            v.reported_tick = world.tick
            self.known_victims.add(vid)
            self.metrics.victims_discovered += 1
            self._log(AgentPhase.UPDATE_STATE, "ALERT", f"Unreported victim {vid} discovered by {uid} at {v.pos} ({v.severity.value})")

        active = sum(1 for vid in self.known_victims if world.victims[vid].is_active)
        self._trace(AgentPhase.UPDATE_STATE, f"belief map v{self.belief_version}; {active} active victim(s) known")

    # ------------------------------------------------------ IDENTIFY GOALS
    def identify_goals(self, world: World) -> list:
        active = [world.victims[vid] for vid in sorted(self.known_victims) if world.victims[vid].is_active]
        anchors = sorted({h.pos for h in world.hospitals.values()} | set(world.bases))
        for v in active:
            v.priority, v.priority_breakdown = compute_priority(v, self.belief, world.tick)
            n = assess_needs(v, self.belief, self.oracle, anchors)
            self.needs[v.id] = n
            v.required_resources = n.describe()
        self._add_ml_risk(world, active)
        self.goals = sorted(active, key=lambda v: (-v.priority, v.id))
        critical = [v for v in active if v.severity == Severity.CRITICAL]

        if self._first_cycle and self.goals:
            self._log(
                AgentPhase.IDENTIFY_GOALS, "DECISION",
                f"Goal formulation: {len(active)} victim(s) to rescue, {len(critical)} critical",
                [f"{v.id} {v.severity.value:<8} priority {v.priority:5.1f}  health {v.health:.0f}%  needs: {', '.join(v.required_resources)}" for v in self.goals[:8]],
            )
        top = self.goals[0] if self.goals else None
        # Track the most urgent *unassigned* goal, with hysteresis so that two
        # victims of near-equal priority do not flip-flop in the log.
        waiting = [v for v in self.goals if v.status == VictimStatus.WAITING]
        candidate = waiting[0] if waiting else None
        current = world.victims.get(self._top_goal) if self._top_goal else None
        if current is not None and current.status != VictimStatus.WAITING:
            current = None
        if candidate and (current is None or (candidate.id != current.id and candidate.priority > current.priority + GOAL_HYSTERESIS)):
            self._log(
                AgentPhase.IDENTIFY_GOALS, "DECISION",
                f"Most urgent unassigned goal: rescue {candidate.id} (priority {candidate.priority:.1f})",
                [f"{f['factor']}: +{f['points']} ({f['detail']})" for f in candidate.priority_breakdown],
            )
            current = candidate
        self._top_goal = current.id if current else None
        self.identify_task.note = f"{len(active)} active · {len(critical)} critical" + (f" · top {top.id}" if top else "")
        self._trace(
            AgentPhase.IDENTIFY_GOALS,
            f"{len(active)} goal(s), {len(critical)} critical" + (f"; top {top.id} ({top.priority:.1f})" if top else ""),
        )
        return self.goals

    def _add_ml_risk(self, world: World, active: list) -> None:
        """Machine-learning step: predict each waiting victim's wait for rescue and
        add priority points to those whose health is projected to fall too low."""
        queue = sorted(
            (v for v in active if v.status in (VictimStatus.WAITING, VictimStatus.ASSIGNED)),
            key=lambda v: (-v.priority, v.id),
        )
        free = sum(1 for a in world.ambulances.values() if a.available and self._is_idle(a.id))
        for v in active:
            v.ml_eta = v.ml_health_at_rescue = None
        for pos, v in enumerate(queue):
            r = ml_risk.assess(v, world, self.belief, pos, free)
            if r is None:
                return
            v.ml_eta, v.ml_health_at_rescue = round(r.eta, 1), round(r.health_at_rescue, 1)
            v.priority = round(v.priority + r.points, 1)
            v.priority_breakdown.append({"factor": "ML risk", "points": round(r.points, 1), "detail": r.detail()})

    # --------------------------------------------------- CHECK CONSTRAINTS
    def check_constraints(self, world: World) -> list[Issue]:
        issues: list[Issue] = []
        checks = 0
        for vid, m in sorted(self.missions.items()):
            v = world.victims[vid]
            checks += 1
            if v.status == VictimStatus.DECEASED:
                issues.append(Issue("VICTIM_LOST", f"victim {vid} died before rescue", victim_id=vid))
                continue
            for uid in m.option.units:
                checks += 1
                if not world.unit(uid).available and any(t.is_open for t in self.agendas.get(uid, []) if t.mission_id == vid):
                    issues.append(Issue("UNIT_UNAVAILABLE", f"{uid} is out of service", unit_id=uid, victim_id=vid))
            needs = self.needs.get(vid)
            if needs and v.carrier_id is None and not v.extracted:
                checks += 1
                team = world.teams.get(m.option.team) if m.option.team else None
                if needs.hazard and (team is None or team.capability != TeamCapability.FIREFIGHTING):
                    issues.append(Issue("CAPABILITY_VIOLATION", f"{vid} is now in a fire danger zone and needs a FIREFIGHTING team", victim_id=vid))
                elif needs.needs_extraction and m.option.method == METHOD_DIRECT:
                    issues.append(Issue("CAPABILITY_VIOLATION", f"{vid} now needs extraction by a rescue team", victim_id=vid))

        inbound_er, inbound_icu = self._inbound(world)
        for hid, h in sorted(world.hospitals.items()):
            checks += 1
            if inbound_icu[hid] > h.icu_free or inbound_er[hid] > h.er_free:
                issues.append(
                    Issue(
                        "HOSPITAL_OVERBOOKED",
                        f"{hid} has {h.er_free} ER / {h.icu_free} ICU beds free but {inbound_er[hid]} ER / {inbound_icu[hid]} ICU patients inbound",
                        hospital_id=hid,
                    )
                )

        if self._agenda_dirty or self._routes_checked_version != self.belief_version:
            for uid in sorted(self.agendas):
                unit = world.unit(uid)
                if not unit.available:
                    continue
                profile = profile_for(unit)
                for task in self.agendas[uid]:
                    if task.kind not in MOVEMENT_KINDS or not task.is_open:
                        continue
                    checks += 1
                    if task.needs_route:
                        issues.append(Issue("NEEDS_ROUTE", f"{uid} still has no route for '{task.label}'", unit_id=uid, task=task, victim_id=task.mission_id))
                        continue
                    path = task.remaining_path
                    idx = first_blocked_index(path, self.belief, profile)
                    if idx is not None:
                        cell = path[idx]
                        issues.append(
                            Issue(
                                "ROUTE_BLOCKED",
                                f"route '{task.label}' crosses {self.belief.type_at(cell).value} at {cell} ({idx} step(s) ahead)",
                                unit_id=uid, task=task, blocked_cell=cell, victim_id=task.mission_id,
                            )
                        )
                    elif task.status == TaskStatus.ACTIVE and len(path) > 1:
                        now = path_cost_on(self.belief, path, profile)
                        planned = sum(task.step_costs[task.path_index:])
                        if now is not None and now > planned * DEGRADE_RATIO + DEGRADE_MARGIN:
                            issues.append(
                                Issue("ROUTE_DEGRADED", f"danger along '{task.label}' rose: cost {planned:.1f} -> {now:.1f}", unit_id=uid, task=task, victim_id=task.mission_id)
                            )
            issues += self._check_trip_detours(world)
            self._routes_checked_version = self.belief_version
            self._agenda_dirty = False

        for issue in issues:
            if issue.kind == "TRIP_DETOUR":
                self._log(AgentPhase.CHECK_CONSTRAINTS, "ALERT", f"Rationality check failed: {issue.detail}")
                continue
            if issue.task is not None:
                unit = world.unit(issue.task.unit_id)
                self._log(
                    AgentPhase.CHECK_CONSTRAINTS, "ALERT",
                    f"Mission affected: {self._unit_label(unit)} -> {self._target_label(issue.task, world)}",
                    [f"Previous plan invalid: {issue.detail}"],
                )
                if issue.kind == "ROUTE_BLOCKED":
                    self._alert("PLAN_INVALID", "Previous plan invalid", f"{unit.id}: {issue.detail}")
            else:
                self._log(AgentPhase.CHECK_CONSTRAINTS, "ALERT", f"Constraint violated ({issue.kind.replace('_', ' ').lower()}): {issue.detail}")
        self._trace(
            AgentPhase.CHECK_CONSTRAINTS,
            f"{checks} check(s): " + (f"{len(issues)} violation(s)" if issues else "all plans valid"),
        )
        return issues

    # ---------------------------------------------------------------- PLAN
    def plan(self, world: World, issues: list[Issue]) -> None:
        before = (self.metrics.replans, self.metrics.missions_created)
        overbooked: list[str] = []
        for issue in issues:
            if issue.kind == "VICTIM_LOST":
                self._abort_mission(world, issue.victim_id, issue.detail, requeue=False)
            elif issue.kind == "UNIT_UNAVAILABLE":
                for vid in [vid for vid, m in self.missions.items() if issue.unit_id in m.option.units]:
                    self._abort_mission(world, vid, f"{issue.unit_id} out of service", requeue=True)
            elif issue.kind == "CAPABILITY_VIOLATION":
                self._abort_mission(world, issue.victim_id, issue.detail, requeue=True)
            elif issue.kind == "HOSPITAL_OVERBOOKED":
                overbooked.append(issue.hospital_id)
            elif issue.kind == "TRIP_DETOUR":
                unit = world.unit(issue.unit_id)
                for t in [t for t in self.agendas.get(issue.unit_id, []) if t.is_open and t.kind == TaskKind.NAVIGATE]:
                    if t.mission_id and t.mission_id not in unit.carrying:
                        self._abort_mission(world, t.mission_id, f"{issue.unit_id} delivers its patients first", requeue=True)
                self._resumed_units.add(issue.unit_id)
        if overbooked:
            affected = sorted(vid for vid in self.missions if world.victims[vid].destination_id in overbooked)
            self._reallocate_destinations(world, affected, f"capacity of {', '.join(overbooked)} reduced")
        for issue in issues:
            if issue.kind in ("ROUTE_BLOCKED", "ROUTE_DEGRADED", "NEEDS_ROUTE") and issue.task is not None and issue.task.is_open:
                if self._issue_resolved(world, issue):
                    continue  # an earlier repair this cycle already fixed it
                self._repair_route(world, issue)
        self._allocate(world)
        if self._preempt_for_critical(world):
            self._allocate(world)

        if self._replanned:
            self.replan_task.status = TaskStatus.DONE
            self.replan_task.note = f"{self.metrics.replans} replan(s) so far · last at tick {self._tick}"
        replans = self.metrics.replans - before[0]
        created = self.metrics.missions_created - before[1]
        parts = []
        if replans:
            parts.append(f"{replans} replan(s)")
        if created:
            parts.append(f"{created} new mission(s)")
        self._trace(AgentPhase.PLAN, ", ".join(parts) if parts else "current plan retained")

    # -------------------------------------------------------- SELECT ACTION
    def select_actions(self, world: World) -> list[Action]:
        actions: list[Action] = []
        for uid, unit in sorted(world.units().items()):
            if not unit.available:
                continue
            task = self._current_task(world, unit)
            if task is None:
                actions.append(Action(ActionType.WAIT, uid, detail="standby"))
                self._last_action_task.pop(uid, None)
                continue
            if uid in self._replanned_units and not self._reactive:
                # Replanning consumes this decision cycle; movement resumes next tick.
                actions.append(Action(ActionType.REPLAN, uid, task_id=task.id, detail=f"adopt new route for '{task.label}'"))
                self._log(AgentPhase.SELECT_ACTION, "DECISION", f"Action selected: REPLAN - {uid} adopts the new route; mission resumes next tick")
                self._last_action_task.pop(uid, None)
                self._resumed_units.discard(uid)
                self._pending_resume.add(uid)
                continue
            action = self._action_for(world, unit, task)
            actions.append(action)
            resumed = uid in self._resumed_units or uid in self._pending_resume
            if self._last_action_task.get(uid) != task.id or resumed:
                prefix = "Mission resumed" if resumed else "Action selected"
                self._log(AgentPhase.SELECT_ACTION, "DECISION", f"{prefix}: {action.type.value} - {task.label}", [action.detail] if action.detail and action.detail != task.label else None)
                self._last_action_task[uid] = task.id
        resumed_now = (self._resumed_units | self._pending_resume) - self._replanned_units if not self._reactive else self._resumed_units
        if resumed_now:
            self._alert("RESUMED", "Mission resumed", ", ".join(sorted(resumed_now)) + " continuing on revised plan")
        if not self._reactive:
            self._pending_resume -= resumed_now
        self._resumed_units.clear()
        self._replanned_units.clear()
        busy = [a for a in actions if a.detail != "standby"]
        counts = Counter(a.type.value for a in busy)
        self._trace(
            AgentPhase.SELECT_ACTION,
            ", ".join(f"{n}x {k}" for k, n in sorted(counts.items())) if busy else "all units on standby",
        )
        return actions

    # ------------------------------------------------- EXECUTE / OBSERVE
    def observe(self, world: World, results: list[ActionResult]) -> None:
        executed = [r for r in results if r.action.detail != "standby"]
        failed = [r for r in results if not r.success]
        self._trace(AgentPhase.EXECUTE, f"{len(executed)} action(s) executed" + (f", {len(failed)} failed" if failed else ""))

        notes: list[str] = []
        for r in results:
            a = r.action
            if not r.success:
                self.metrics.failed_actions += 1
                self._log(AgentPhase.OBSERVE, "ALERT", f"Action failed: {a.describe()} - {r.message}")
                self._agenda_dirty = True
                continue
            task = self.tasks.get(a.task_id) if a.task_id else None
            if a.type == ActionType.WAIT or task is None:
                continue
            self.metrics.actions_executed += 1
            unit = world.unit(a.unit_id)
            if a.type in (ActionType.MOVE, ActionType.TRANSPORT):
                task.path_index = min(task.path_index + 1, len(task.path) - 1)
                if unit.pos == task.target:
                    task.set_status(TaskStatus.DONE)
                    self._log(AgentPhase.OBSERVE, "INFO", f"{unit.id} arrived at {self._target_label(task, world)}")
                    notes.append(f"{unit.id} arrived")
            elif a.type == ActionType.RESCUE:
                victim = world.victims[a.victim_ids[0]]
                task.progress = task.duration if r.completed else victim.rescue_progress
                if r.completed:
                    task.set_status(TaskStatus.DONE)
                    if a.mode == RescueMode.EXTRACT:
                        self._log(AgentPhase.OBSERVE, "SUCCESS", f"{victim.id} extracted from debris by {unit.id}")
                        notes.append(f"{victim.id} extracted")
                        mission = self.missions.get(victim.id)
                        if mission is not None and mission.option.method == METHOD_EXTRACT_ONLY:
                            self._complete_extraction(world, victim.id)
                    else:
                        self._log(AgentPhase.OBSERVE, "SUCCESS", f"{victim.id} rescued and on board {unit.id}")
                        notes.append(f"{victim.id} on board {unit.id}")
            elif a.type in (ActionType.DELIVER_TO_HOSPITAL, ActionType.DELIVER_TO_SAFE_ZONE):
                task.set_status(TaskStatus.DONE)
                for vid in a.victim_ids:
                    self._complete_mission(world, vid, a.destination_id)
                    notes.append(f"{vid} delivered")
        self._flush_instant(world)

        remaining = [vid for vid in self.known_victims if world.victims[vid].is_active]
        self.check_task.note = f"{len(remaining)} victim(s) remaining · {len(self.missions)} mission(s) in progress"
        if not remaining and not self.missions:
            self.check_task.status = TaskStatus.DONE
            if not self._goal_logged:
                self._log(AgentPhase.OBSERVE, "SUCCESS", "All known victims resolved - mission goal satisfied")
                self._goal_logged = True
        else:
            self.check_task.status = TaskStatus.ACTIVE
            self._goal_logged = False
        self._update_ai_state(world)
        self._trace(AgentPhase.OBSERVE, "; ".join(notes) if notes else f"{len(remaining)} victim(s) remaining")

    def _issue_resolved(self, world: World, issue: Issue) -> bool:
        task = issue.task
        assert task is not None
        if issue.kind == "NEEDS_ROUTE":
            return not task.needs_route
        if issue.kind == "ROUTE_BLOCKED":
            profile = profile_for(world.unit(task.unit_id))
            return not task.needs_route and first_blocked_index(task.remaining_path, self.belief, profile) is None
        return False

    def _check_trip_detours(self, world: World) -> list[Issue]:
        """Patients already on board must not ride along on a long detour to a
        second pickup: compare the remaining trip with driving straight to the
        hospital (shared trips are planned optimistically and the map changes)."""
        issues: list[Issue] = []
        for uid, unit in sorted(world.ambulances.items()):
            if not unit.available or not unit.carrying:
                continue
            agenda = [t for t in self.agendas.get(uid, []) if t.is_open]
            pickups = [t for t in agenda if t.kind == TaskKind.NAVIGATE and t.mission_id not in unit.carrying]
            transport = next((t for t in agenda if t.kind == TaskKind.TRANSPORT), None)
            if not pickups or transport is None:
                continue
            profile = profile_for(unit)
            costs = [path_cost_on(self.belief, t.remaining_path, profile) for t in pickups + [transport]]
            if any(c is None for c in costs):
                continue  # a blocked leg is a job for route repair, not a detour
            trip = sum(costs)
            direct = self.oracle.cost(unit.pos, transport.target, profile)
            if direct is not None and trip > direct * TRIP_DETOUR_RATIO + TRIP_DETOUR_MARGIN:
                waiting = sorted({t.mission_id for t in pickups if t.mission_id})
                issues.append(
                    Issue(
                        "TRIP_DETOUR",
                        f"{uid} carries {', '.join(unit.carrying)} but the pickup detour via {', '.join(waiting)} costs "
                        f"{trip:.0f} vs {direct:.0f} straight to {transport.target_id}",
                        unit_id=uid,
                    )
                )
        return issues

    # =================================================================
    # Plan repair
    # =================================================================
    def _repair_route(self, world: World, issue: Issue) -> None:
        task = issue.task
        assert task is not None
        unit = world.unit(task.unit_id)
        profile = profile_for(unit)
        active = task.status == TaskStatus.ACTIVE
        start = unit.pos if active or not task.path else task.path[0]
        goal = task.target
        target = self._target_label(task, world)
        if issue.kind == "ROUTE_BLOCKED":
            self._log(
                AgentPhase.PLAN, "REPLAN",
                f"Stopping current plan for {unit.id}. Replanning..." if active else f"Upcoming leg '{task.label}' invalid. Replanning...",
            )
        elif issue.kind == "ROUTE_DEGRADED":
            self._log(AgentPhase.PLAN, "REPLAN", f"Route of {unit.id} became more dangerous - evaluating alternatives")
        self._log(AgentPhase.PLAN, "SEARCH", f"{self.algorithm_label} started: {unit.id} {start} -> {target} {goal}")
        old = task.remaining_path
        res = self._route(start, goal, profile, f"replan {task.label}", unit_id=unit.id)
        if not res.found:
            self._log(AgentPhase.PLAN, "ALERT", f"No route from {start} to {goal} for {unit.id} ({res.nodes_expanded} nodes explored)")
            self._escalate_route_failure(world, task, unit)
            return
        old_cost = path_cost_on(self.belief, old, profile)
        if issue.kind == "ROUTE_DEGRADED" and old_cost is not None and res.cost >= old_cost - 1e-6:
            task.step_costs = [profile.step_cost(self.belief, p) or 0.0 for p in task.path[1:]]
            self._log(AgentPhase.PLAN, "INFO", f"Current route of {unit.id} is still the best option (cost {old_cost:.1f})")
            return
        assign_path(task, res, self.belief, profile)
        task.replans += 1
        task.sync_mirrors()
        self.metrics.replans += 1
        self.metrics.route_replans += 1
        self._replanned = True
        self.replan_events.append(
            {
                "unit_id": unit.id,
                "task_id": task.id,
                "reason": issue.kind,
                "blocked_cell": list(issue.blocked_cell) if issue.blocked_cell else None,
                "old_path": [list(p) for p in old],
                "new_path": [list(p) for p in res.path],
            }
        )
        details = [f"Previous route: {max(0, len(old) - 1)} steps" + (f", cost now {old_cost:.1f}" if old_cost is not None else " (blocked)")]
        details.append(f"New route: {res.steps} steps, cost {res.cost:.1f}")
        self._log(
            AgentPhase.PLAN, "SUCCESS",
            f"New path generated for {unit.id} ({res.nodes_expanded} nodes expanded, {res.time_ms:.2f} ms)",
            details,
        )
        dest_note = ""
        if task.target_id in world.hospitals:
            h = world.hospitals[task.target_id]
            dest_note = f"; {h.id} beds ER {h.er_free} / ICU {h.icu_free}"
        self._log(
            AgentPhase.CHECK_CONSTRAINTS, "INFO", "Checking constraints for revised plan... satisfied",
            [f"{unit.id} available and assigned to a single task", f"route valid on belief map v{self.belief_version}{dest_note}"],
        )
        self._resumed_units.add(unit.id)
        self._replanned_units.add(unit.id)

    def _escalate_route_failure(self, world: World, task: PlanTask, unit: Unit) -> None:
        if task.kind == TaskKind.NAVIGATE:
            self._abort_mission(world, task.mission_id, f"{unit.id} cannot reach {task.mission_id}", requeue=True)
            return
        # Transport leg: try another destination for the patients on this leg.
        victims = [vid for vid in task.victim_ids if vid in self.missions]
        if victims:
            self._reallocate_destinations(world, victims, f"route to {task.target_id} lost")
        if task.is_open and (task.needs_route or first_blocked_index(task.remaining_path, self.belief, profile_for(unit)) is not None):
            task.needs_route = True
            self._log(AgentPhase.PLAN, "ALERT", f"{unit.id} holding position: no reachable destination yet; will retry when the map changes")

    def _abort_mission(self, world: World, vid: str | None, reason: str, requeue: bool) -> None:
        if vid is None or vid not in self.missions:
            return
        v = world.victims[vid]
        m = self.missions[vid]
        carrier = world.unit(v.carrier_id) if v.carrier_id else None
        if requeue and carrier is not None and carrier.available:
            # The patient is already on board: re-route instead of abandoning them.
            self._reallocate_destinations(world, [vid], reason)
            return
        self.missions.pop(vid)
        m.status = "ABORTED"
        m.abort_reason = reason
        m.end_tick = world.tick
        for t in m.root.walk():
            if t is m.root:
                continue
            if t.mirror_of is not None:
                primary = t.mirror_of
                if t in primary.mirrors:
                    primary.mirrors.remove(t)
                if vid in primary.victim_ids:
                    primary.victim_ids.remove(vid)
                if primary.is_open:
                    if not primary.victim_ids:
                        primary.set_status(TaskStatus.CANCELLED)
                    elif primary.kind == TaskKind.DELIVER:
                        primary.label = f"Deliver {'+'.join(primary.victim_ids)} to {world.destination(primary.target_id).name}"
                        primary.sync_mirrors()
                    elif primary.kind == TaskKind.TRANSPORT:
                        primary.label = f"Transport {'+'.join(primary.victim_ids)} -> {primary.target_id}"
                        primary.sync_mirrors()
                if t.status != TaskStatus.DONE:
                    t.status = TaskStatus.CANCELLED
            elif t.is_open:
                t.status = TaskStatus.CANCELLED
        m.root.status = TaskStatus.CANCELLED
        m.root.note = f"aborted at tick {world.tick}: {reason}"
        for uid in list(self.agendas):
            self.agendas[uid] = [t for t in self.agendas[uid] if t.status != TaskStatus.CANCELLED]
        for uid in m.option.units:
            # Whatever these units do next is a new job, not a resumed one.
            self._resumed_units.discard(uid)
            self._pending_resume.discard(uid)
        if v.is_active:
            v.assigned_units = []
            v.destination_id = None
            if v.carrier_id is None:
                v.status = VictimStatus.WAITING
        self.metrics.missions_aborted += 1
        if requeue:
            self.metrics.reassignments += 1
            self.metrics.replans += 1
            self._replanned = True
        self._csp_signature = None
        self._agenda_dirty = True
        self._log(
            AgentPhase.PLAN, "REPLAN",
            f"Mission for {vid} aborted: {reason}." + (" Victim returned to the goal queue for re-assignment." if requeue and v.is_active else ""),
        )

    def _reallocate_destinations(self, world: World, vids: list[str], reason: str) -> None:
        items: list[DestinationItem] = []
        for vid in vids:
            m = self.missions.get(vid)
            if m is None or m.option.carrier is None or m.option.destination is None:
                continue
            v = world.victims[vid]
            carrier = world.unit(m.option.carrier)
            if not carrier.available:
                continue
            loaded = v.carrier_id == carrier.id
            items.append(DestinationItem(v, carrier, carrier.pos if loaded else v.pos, loaded))
        hospital_items = [it for it in items if it.victim.needs_hospital]
        if not hospital_items:
            return
        exclude = {it.victim.id for it in hospital_items}
        er_free, icu_free = self._free_beds(world, exclude=exclude)
        self._log(
            AgentPhase.PLAN, "CSP",
            f"Destination re-allocation CSP started: {len(hospital_items)} patient(s) ({reason})",
            [f"Variables: {', '.join(sorted(exclude))}", "Domain: hospitals + HOLD", "Constraints: bed availability, ICU, reachability, capacity, same-vehicle"],
        )
        hospitals = [world.hospitals[h] for h in sorted(world.hospitals)]
        problem = build_destination_problem(hospital_items, hospitals, er_free, icu_free, self.oracle, require_loaded=True)
        solution = self._solve(problem)
        phase1 = None
        if not solution.satisfiable:
            phase1 = solution
            self._log(AgentPhase.PLAN, "ALERT", f"Destination CSP unsatisfiable ({solution.failure_reason}); relaxing 'deliver-loaded-patient'")
            problem = build_destination_problem(hospital_items, hospitals, er_free, icu_free, self.oracle, require_loaded=False)
            solution = self._solve(problem)
        self.last_csp = self._csp_report(problem, solution, phase1)
        self._log_csp_summary(solution)
        if not solution.satisfiable or solution.assignment is None:
            return
        for it in hospital_items:
            vid = it.victim.id
            if vid not in self.missions:
                continue
            new = solution.assignment[vid]
            if new == HOLD:
                if it.loaded:
                    for t in self.agendas.get(it.carrier.id, []):
                        if t.is_open and t.kind == TaskKind.TRANSPORT and vid in t.victim_ids:
                            t.needs_route = True
                    self._log(AgentPhase.PLAN, "ALERT", f"No hospital can take {vid} now: {it.carrier.id} holds position")
                else:
                    self._abort_mission(world, vid, "no suitable hospital bed available", requeue=True)
                continue
            if new != it.victim.destination_id:
                self._retarget(world, self.missions[vid], str(new))

    def _retarget(self, world: World, mission: Mission, new_hid: str) -> None:
        vid = mission.victim_id
        v = world.victims[vid]
        old = v.destination_id
        h = world.hospitals[new_hid]
        v.destination_id = new_hid
        mission.option = replace(mission.option, destination=new_hid)
        carrier = world.unit(mission.option.carrier)
        profile = profile_for(carrier)
        for task in self.agendas.get(carrier.id, []):
            if not task.is_open or vid not in task.victim_ids or task.kind not in (TaskKind.TRANSPORT, TaskKind.DELIVER):
                continue
            if task.target_id == new_hid:
                continue
            task.target, task.target_id = h.pos, new_hid
            if task.kind == TaskKind.DELIVER:
                task.label = f"Deliver {'+'.join(task.victim_ids)} to {h.name}"
            else:
                task.label = f"Transport {'+'.join(task.victim_ids)} -> {new_hid}"
                start = carrier.pos if task.status == TaskStatus.ACTIVE or not task.path else task.path[0]
                old_path = task.remaining_path
                res = self._route(start, h.pos, profile, f"re-route to {new_hid}", unit_id=carrier.id)
                if res.found:
                    assign_path(task, res, self.belief, profile)
                    task.replans += 1
                    self.replan_events.append(
                        {"unit_id": carrier.id, "task_id": task.id, "reason": "DESTINATION_CHANGED", "blocked_cell": None,
                         "old_path": [list(p) for p in old_path], "new_path": [list(p) for p in res.path]}
                    )
                else:
                    task.needs_route = True
            task.sync_mirrors()
        for t in mission.root.walk():
            if t.kind == TaskKind.SELECT_DESTINATION:
                t.label = f"Select hospital {new_hid} ({h.name})"
                t.note = f"re-allocated from {old} by CSP"
        self.metrics.destination_changes += 1
        self.metrics.replans += 1
        self._replanned = True
        self._resumed_units.add(carrier.id)
        self._log(AgentPhase.PLAN, "REPLAN", f"Destination of {vid} changed: {old} -> {new_hid} ({h.name})")

    # =================================================================
    # Resource allocation (CSP) + hierarchical planning
    # =================================================================
    def _preempt_for_critical(self, world: World) -> bool:
        """A critical victim that no idle unit can serve may take an ALS ambulance
        away from a less urgent mission, as long as that ambulance has no patient
        on board. The displaced victim returns to the goal queue."""
        waiting = [v for v in self.goals if v.status == VictimStatus.WAITING and v.severity == Severity.CRITICAL and v.id not in self.missions]
        if not waiting:
            return False
        idle_als = [a for a in world.ambulances.values() if a.available and a.medical == MedicalLevel.ALS and self._is_idle(a.id)]
        if idle_als:
            return False  # the allocation CSP already had a compatible ambulance to work with
        _er, icu_free = self._free_beds(world)
        preempted = False
        for victim in waiting:
            needs = self.needs.get(victim.id)
            if needs is None or not needs.ground_accessible or (needs.needs_icu and not any(icu_free.values())):
                continue
            if needs.needs_extraction and not self._idle_extractor(world, victim, needs):
                continue  # an ambulance alone would not help: pre-empting would only thrash
            candidates = []
            for vid, m in self.missions.items():
                amb = world.ambulances.get(m.option.ambulance) if m.option.ambulance else None
                if amb is None or not amb.available or amb.medical != MedicalLevel.ALS or amb.carrying:
                    continue
                if world.victims[vid].severity == Severity.CRITICAL:
                    continue
                cost = self.oracle.cost(amb.pos, victim.pos, GROUND_VEHICLE)
                if cost is not None:
                    candidates.append((cost, amb.id, vid))
            if not candidates:
                continue
            cost, amb_id, displaced = min(candidates)
            self._log(
                AgentPhase.PLAN, "REPLAN",
                f"Pre-emption: {amb_id} diverted from {displaced} ({world.victims[displaced].severity.value}) "
                f"to critical victim {victim.id} ({cost:.0f} away)",
                ["No idle ALS ambulance can serve the critical victim; the displaced victim returns to the goal queue"],
            )
            for mvid in [k for k, m in self.missions.items() if m.option.ambulance == amb_id]:
                self._abort_mission(world, mvid, f"pre-empted: {amb_id} reassigned to critical victim {victim.id}", requeue=True)
            preempted = True
            break  # re-allocate now; further pre-emptions happen next cycle if still needed
        return preempted

    def _idle_extractor(self, world: World, victim, needs: VictimNeeds) -> bool:
        """Is there an idle rescue team able to extract this victim?"""
        for team in world.teams.values():
            if not team.available or not self._is_idle(team.id):
                continue
            if needs.hazard and team.capability != TeamCapability.FIREFIGHTING:
                continue
            if self.oracle.cost(team.pos, victim.pos, profile_for(team)) is not None:
                return True
        return False

    def _waiting_and_idle(self, world: World) -> tuple[list, list[str]]:
        waiting = [v for v in self.goals if v.status == VictimStatus.WAITING and v.id not in self.missions]
        idle = sorted(uid for uid, u in world.units().items() if u.available and self._is_idle(uid))
        return waiting, idle

    def _allocation_signature(self, world: World, waiting: list, idle: list[str]) -> tuple:
        """Everything the allocation CSP depends on; re-solve only when it changes."""
        return (
            tuple(v.id for v in waiting),
            tuple(idle),
            self.belief_version,
            tuple(sorted((h.id, h.er_free, h.icu_free) for h in world.hospitals.values())),
            tuple(sorted(v.id for v in waiting if v.extracted)),
        )

    def is_stalled(self, world: World) -> bool:
        """True when nothing can progress until the environment changes: either
        every running mission is holding without a route, or no mission is
        running and the last allocation attempt already saw the current
        situation, so waiting victims cannot be served right now."""
        if self.missions:
            busy = [uid for uid in self.agendas if not self._is_idle(uid) and world.unit(uid).available]
            if not busy or not all(self._is_holding(uid) for uid in busy):
                return False
            waiting, _idle = self._waiting_and_idle(world)
            return not waiting or self._allocation_exhausted(world)
        return self._allocation_exhausted(world)

    def _is_holding(self, uid: str) -> bool:
        task = next((t for t in self.agendas.get(uid, []) if t.is_open and t.kind not in INSTANT_KINDS), None)
        return bool(task and task.needs_route)

    def _allocation_exhausted(self, world: World) -> bool:
        waiting, idle = self._waiting_and_idle(world)
        if not waiting:
            return False
        if not idle:
            return True
        return self._allocation_signature(world, waiting, idle) == self._csp_signature

    def _allocate(self, world: World) -> None:
        waiting, idle = self._waiting_and_idle(world)
        if not waiting or not idle:
            return
        if self._allocation_signature(world, waiting, idle) == self._csp_signature:
            return
        # Bounded rationality: solve the CSP over an attention window of the
        # highest-priority victims; if units are still idle afterwards, move the
        # window down the priority list.
        pool = list(waiting)
        reports: list[dict] = []
        while pool and idle:
            window, pool = pool[:ATTENTION_WINDOW], pool[ATTENTION_WINDOW:]
            used, report = self._allocate_window(world, window, idle)
            if report is not None:
                reports.append(report)
            idle = [u for u in idle if u not in used]
        if reports:
            # Show the highest-priority window that actually assigned something.
            assigned = [r for r in reports if any(v["assigned"] not in (None, "DEFER") for v in r["variables"])]
            self.last_csp = (assigned or reports)[0]
        if pool:
            self._log(AgentPhase.PLAN, "INFO", f"Deferred (no idle units left): {', '.join(v.id for v in pool)}")
        # Remember what the allocator has already seen so it only re-solves on change.
        self._csp_signature = self._allocation_signature(world, *self._waiting_and_idle(world))

    def _allocate_window(self, world: World, window: list, idle: list[str]) -> tuple[set[str], dict | None]:
        """Solve one allocation CSP and commit its plans; returns (units used, CSP report)."""
        er_free, icu_free = self._free_beds(world)
        seq_before = self.log.last_seq
        self._log(
            AgentPhase.PLAN, "CSP",
            f"Resource allocation CSP started: {len(window)} victim variable(s), {len(idle)} idle unit(s)",
            [f"Variables (by priority): {', '.join(f'{v.id}({v.priority:.0f})' for v in window)}", f"Idle units: {', '.join(idle)}"],
        )
        self.oracle.reset_counters()
        build_args = dict(
            victims=window,
            needs=self.needs,
            ambulances=[world.ambulances[a] for a in sorted(world.ambulances)],
            teams=[world.teams[t] for t in sorted(world.teams)],
            hospitals=[world.hospitals[h] for h in sorted(world.hospitals)],
            safe_zones=[world.safe_zones[s] for s in sorted(world.safe_zones)],
            idle_units=set(idle),
            er_free=er_free,
            icu_free=icu_free,
            oracle=self.oracle,
        )
        problem = build_allocation_problem(**build_args, require_critical=True)
        solution = self._solve(problem)
        phase1 = None
        covered = list(problem.coverage_vars)  # highest priority first
        if not solution.satisfiable and covered:
            phase1 = solution
            self._log(
                AgentPhase.PLAN, "ALERT",
                f"Phase 1 (hard 'critical-coverage') has no solution: {solution.failure_reason}",
                ["Not every critical victim can be served at once - relaxing coverage for the lowest-priority ones first"],
            )
        # Minimal relaxation: give up coverage one critical victim at a time,
        # lowest priority first, until the CSP becomes satisfiable.
        while not solution.satisfiable and covered:
            dropped = covered.pop()
            self._log(AgentPhase.PLAN, "CSP", f"Relaxing 'critical-coverage' for {dropped}; still required for {', '.join(covered) or 'none'}")
            problem = build_allocation_problem(**build_args, require_critical=True, coverage=covered)
            solution = self._solve(problem)
        report = self._csp_report(problem, solution, phase1)
        self._log_csp_summary(solution)
        self._log(
            AgentPhase.PLAN, "SEARCH",
            f"Route estimates for constraint checking: {self.oracle.searches} {self.algorithm_label} searches "
            f"({self.oracle.nodes_expanded} nodes, {self.oracle.time_ms:.1f} ms)",
        )
        if not solution.satisfiable or solution.assignment is None:
            self._log(AgentPhase.PLAN, "ALERT", f"Resource allocation failed: {solution.failure_reason}")
            return set(), report

        chosen = [(problem.victims[var], solution.assignment[var]) for var in problem.var_order if solution.assignment[var] is not DEFER]
        deferred = [var for var in problem.var_order if solution.assignment[var] is DEFER]
        if not chosen and tuple(deferred) == self._last_deferred:
            # Same outcome as last time: keep the log readable with a one-line summary.
            self.log.truncate_after(seq_before)
            self._log(
                AgentPhase.PLAN, "CSP",
                f"Allocation CSP re-solved ({solution.stats.nodes} nodes, {solution.stats.time_ms:.1f} ms): "
                f"{', '.join(deferred)} still deferred - no compatible idle unit",
            )
            return set(), None
        self._last_deferred = tuple(deferred) if not chosen else None
        for victim, opt in chosen:
            self._log(
                AgentPhase.PLAN, "DECISION",
                f"Assign {victim.id} ({victim.severity.value}, priority {victim.priority:.1f}) -> {opt.label()}",
                [f"method {opt.method}; utility {problem.utility(victim.id, opt):.0f}"],
            )
        if deferred:
            reasons = []
            for var in deferred:
                row = next((r for r in report["variables"] if r["var"] == var), None)
                if row and row["domain_after_ac3"] == 1:
                    top = ", ".join(f"{k} x{n}" for k, n in list(row["prunings"].items())[:3])
                    reasons.append(f"{var}: no feasible option ({top})")
                else:
                    reasons.append(f"{var}: resources taken by higher-utility assignments")
            self._log(AgentPhase.PLAN, "INFO", f"Deferred this round: {', '.join(deferred)}", reasons)
        if not chosen:
            return set(), report
        self._allocated = True
        used: set[str] = set()
        plans = self.planner.plan_round(chosen, world, self.belief, self._planner_route)
        for p in plans:
            if p.failed:
                level = "INFO" if p.failed.startswith("shared trip rejected") else "ALERT"
                self._log(AgentPhase.PLAN, level, f"HTN decomposition for {', '.join(p.option_by_victim)}: {p.failed}")
                continue
            self._commit(world, p)
            for opt in p.option_by_victim.values():
                used.update(opt.units)
        return used, report

    def _commit(self, world: World, plan: MissionPlan) -> None:
        for vid, root in plan.roots.items():
            opt = plan.option_by_victim[vid]
            self.attempts[vid] += 1
            if self.attempts[vid] > 1:
                root.label += f" (attempt {self.attempts[vid]})"
            mission = Mission(vid, opt, root, world.tick, attempt=self.attempts[vid])
            self.missions[vid] = mission
            self.mission_history.append(mission)
            self.root.children.insert(len(self.root.children) - 2, root)
            v = world.victims[vid]
            v.status = VictimStatus.ASSIGNED
            v.assigned_units = opt.units
            v.destination_id = opt.destination
            for t in root.walk():
                self.tasks[t.id] = t
            self.metrics.missions_created += 1
            self._log(AgentPhase.PLAN, "DECISION", f"HTN decomposition: {root.label} via {opt.method}", [c.label for c in root.children])
        for uid, tasks in plan.agendas.items():
            self.agendas[uid] = [t for t in self.agendas.get(uid, []) if t.is_open] + tasks
            for t in tasks:
                self.tasks[t.id] = t
        self._agenda_dirty = True

    def _solve(self, problem: AllocationProblem) -> CSPSolution:
        solver = BacktrackingSolver(
            problem.csp, utility=problem.utility, node_limit=CSP_NODE_LIMIT, var_order_hint=problem.var_order,
            record_limit=3000, bound=problem.bound,
        )
        solution = solver.solve()
        self.metrics.csp_runs += 1
        self.metrics.csp_nodes += solution.stats.nodes
        self.metrics.csp_time_ms += solution.stats.time_ms
        return solution

    def _log_csp_summary(self, solution: CSPSolution) -> None:
        st = solution.stats
        node_counts = sorted(solution.removal_counts.get("NODE", {}).items(), key=lambda kv: -kv[1])
        self._log(
            AgentPhase.PLAN, "CSP",
            f"Constraint propagation: node consistency removed {st.node_consistency_removals} value(s); "
            f"AC-3 removed {st.ac3_removals} ({st.ac3_revisions} arc revisions)",
            [f"{name}: -{n}" for name, n in node_counts[:7]],
        )
        verdict = "optimal" if solution.optimal else ("best found within budget" if solution.satisfiable else "no solution")
        self._log(
            AgentPhase.PLAN, "CSP",
            f"Backtracking search: {st.nodes} nodes, {st.backtracks} backtracks, {st.fc_prunings} forward-checking "
            f"prunings, {st.bound_prunings} bound prunings, {st.time_ms:.1f} ms - {verdict}",
        )

    def _csp_report(self, problem: AllocationProblem, solution: CSPSolution, phase1: CSPSolution | None) -> dict:
        self._csp_runs += 1
        by_var: dict[str, Counter] = defaultdict(Counter)
        for r in solution.removals:
            by_var[r.var][r.constraint] += 1
        variables = []
        for var in problem.var_order:
            v = problem.victims[var]
            value = solution.assignment.get(var) if solution.assignment else None
            sizes = solution.domain_sizes.get(var, {})
            variables.append(
                {
                    "var": var,
                    "severity": v.severity.value,
                    "priority": v.priority,
                    "domain_initial": sizes.get("initial"),
                    "domain_after_node": sizes.get("after_node"),
                    "domain_after_ac3": sizes.get("after_ac3"),
                    "assigned": describe_value(value) if value is not None else None,
                    "method": getattr(value, "method", None) or (str(value) if value is not None else None),
                    "utility": round(problem.utility(var, value), 1) if value is not None else None,
                    "prunings": dict(by_var[var].most_common(6)),
                    "coverage_required": var in problem.coverage_vars,
                }
            )
        cons = problem.csp.constraints
        return {
            "run": self._csp_runs,
            "tick": self._tick,
            "kind": problem.kind,
            "result": "SATISFIED" if solution.satisfiable else "UNSATISFIABLE",
            "optimal": solution.optimal,
            "score": None if solution.score is None else round(solution.score, 1),
            "failure_reason": solution.failure_reason,
            "relaxed": phase1 is not None,
            "phase1": None
            if phase1 is None
            else {"result": "UNSATISFIABLE", "reason": phase1.failure_reason, "stats": phase1.stats.to_dict(), "removal_counts": phase1.removal_counts},
            "variables": variables,
            "constraints": {
                "total": len(cons),
                "unary": sorted({c.name for c in cons if isinstance(c, UnaryConstraint)}),
                "binary": sum(1 for c in cons if isinstance(c, BinaryConstraint)),
                "global": [c.to_dict() | {"scope": len(c.scope)} for c in cons if isinstance(c, CapacityConstraint)],
            },
            "removal_counts": solution.removal_counts,
            "stats": solution.stats.to_dict(),
            "removals_sample": [r.to_dict() for r in solution.removals if r.stage == "AC3"][:15]
            + [r.to_dict() for r in solution.removals if r.stage == "NODE"][:25],
        }

    # =================================================================
    # Action selection helpers
    # =================================================================
    def _current_task(self, world: World, unit: Unit) -> PlanTask | None:
        for task in self.agendas.get(unit.id, []):
            if not task.is_open:
                continue
            if task.kind in INSTANT_KINDS:
                self._complete_instant(world, task)
                continue
            if task.kind in MOVEMENT_KINDS:
                if task.needs_route:
                    return task
                if task.status == TaskStatus.PENDING:
                    task.set_status(TaskStatus.ACTIVE)
                    if not task.path or task.path[0] != unit.pos:
                        self._refresh_leg(world, unit, task)
                        if task.needs_route:
                            return task
                if task.path_index >= len(task.path) or task.path[task.path_index] != unit.pos:
                    if unit.pos in task.path:
                        task.path_index = task.path.index(unit.pos)
                    else:
                        self._refresh_leg(world, unit, task)
                        if task.needs_route:
                            return task
                if unit.pos == task.target:
                    task.set_status(TaskStatus.DONE)
                    continue
                return task
            if task.status == TaskStatus.PENDING:
                task.set_status(TaskStatus.ACTIVE)
            return task
        return None

    def _refresh_leg(self, world: World, unit: Unit, task: PlanTask) -> None:
        profile = profile_for(unit)
        res = self._route(unit.pos, task.target, profile, f"{task.label} (from current position)", unit_id=unit.id)
        if res.found:
            assign_path(task, res, self.belief, profile)
        else:
            task.needs_route = True
            self._agenda_dirty = True
            self._log(AgentPhase.SELECT_ACTION, "ALERT", f"{unit.id} cannot start '{task.label}': no route from {unit.pos}")

    def _action_for(self, world: World, unit: Unit, task: PlanTask) -> Action:
        if task.needs_route:
            return Action(ActionType.WAIT, unit.id, task_id=task.id, detail="holding: no route available")
        pending = [d for d in task.depends_on if d.status != TaskStatus.DONE]
        if pending:
            return Action(ActionType.WAIT, unit.id, task_id=task.id, detail=f"waiting for: {pending[0].label}")
        if task.kind in MOVEMENT_KINDS:
            nxt = task.path[task.path_index + 1]
            kind = ActionType.TRANSPORT if unit.carrying else ActionType.MOVE
            return Action(kind, unit.id, target=nxt, victim_ids=tuple(unit.carrying), task_id=task.id, detail=f"towards {task.target}")
        if task.kind == TaskKind.EXTRACT:
            return Action(ActionType.RESCUE, unit.id, target=task.target, victim_ids=tuple(task.victim_ids),
                          mode=RescueMode.EXTRACT, duration=task.duration, task_id=task.id, detail=task.label)
        if task.kind == TaskKind.RESCUE:
            return Action(ActionType.RESCUE, unit.id, target=task.target, victim_ids=tuple(task.victim_ids),
                          mode=RescueMode.LOAD, duration=task.duration, task_id=task.id, detail=task.label)
        if task.kind == TaskKind.DELIVER:
            kind = ActionType.DELIVER_TO_HOSPITAL if task.target_id in world.hospitals else ActionType.DELIVER_TO_SAFE_ZONE
            return Action(kind, unit.id, target=task.target, victim_ids=tuple(task.victim_ids),
                          destination_id=task.target_id, task_id=task.id, detail=task.label)
        return Action(ActionType.WAIT, unit.id, task_id=task.id, detail=task.label)

    def _complete_instant(self, world: World, task: PlanTask) -> None:
        task.set_status(TaskStatus.DONE)
        if task.kind == TaskKind.UPDATE_RESOURCES and task.unit_id:
            unit = world.unit(task.unit_id)
            if not any(t.is_open and t.kind not in INSTANT_KINDS for t in self.agendas.get(unit.id, [])):
                self._log(AgentPhase.OBSERVE, "INFO", f"Resources updated: {unit.id} released and available at {unit.pos}")

    def _flush_instant(self, world: World) -> None:
        for uid in sorted(self.agendas):
            for task in self.agendas[uid]:
                if not task.is_open:
                    continue
                if task.kind in INSTANT_KINDS:
                    self._complete_instant(world, task)
                    continue
                break
            self.agendas[uid] = [t for t in self.agendas[uid] if t.is_open]

    def _complete_extraction(self, world: World, vid: str) -> None:
        """A partial (EXTRACT_ONLY) mission is done: the victim is free and waits
        for an ambulance, which the next allocation round will assign."""
        m = self.missions.pop(vid)
        v = world.victims[vid]
        m.status = "COMPLETED"
        m.end_tick = world.tick
        m.root.set_status(TaskStatus.DONE)
        m.root.note = f"extracted at tick {world.tick} - transport goes back to the goal queue"
        v.status = VictimStatus.WAITING
        v.assigned_units = []
        v.destination_id = None
        self.metrics.missions_completed += 1
        self._csp_signature = None
        self._log(AgentPhase.OBSERVE, "INFO", f"Sub-goal achieved: {vid} is free; transport will be allocated in the next round")

    def _complete_mission(self, world: World, vid: str, dest_id: str | None) -> None:
        m = self.missions.pop(vid, None)
        if m is None:
            return
        v = world.victims[vid]
        m.status = "COMPLETED"
        m.end_tick = world.tick
        m.root.set_status(TaskStatus.DONE)
        elapsed = (v.rescued_tick or world.tick) - v.reported_tick
        dest = world.destination(dest_id).name if dest_id else "safety"
        m.root.note = f"delivered to {dest} at tick {world.tick} ({elapsed} ticks after report)"
        self.metrics.missions_completed += 1
        self._csp_signature = None
        self._log(AgentPhase.OBSERVE, "SUCCESS", f"Victim {vid} delivered to {dest} - rescued {elapsed} ticks after report")

    # =================================================================
    # Utilities
    # =================================================================
    def _planner_route(self, start: Pos, goal: Pos, profile: MobilityProfile, label: str) -> SearchResult:
        return self._route(start, goal, profile, label, log=label != "trip ordering")

    def _route(self, start: Pos, goal: Pos, profile: MobilityProfile, purpose: str, unit_id: str | None = None, log: bool = True) -> SearchResult:
        res = self.oracle.route(start, goal, profile)
        if log:
            self.last_search = {**res.to_dict(include_trace=True), "purpose": purpose, "unit_id": unit_id, "tick": self._tick, "profile": profile.name}
            self.search_history.appendleft({**res.to_dict(include_trace=False), "purpose": purpose, "tick": self._tick})
            if res.found:
                self._log(
                    AgentPhase.PLAN, "SEARCH",
                    f"{self.algorithm_label}: {purpose} - {res.steps} steps, cost {res.cost:.1f}, "
                    f"{res.nodes_expanded} nodes expanded, {res.time_ms:.2f} ms",
                )
        return res

    def _is_idle(self, uid: str) -> bool:
        return not any(t.is_open and t.kind not in INSTANT_KINDS for t in self.agendas.get(uid, []))

    def _inbound(self, world: World) -> tuple[Counter, Counter]:
        er: Counter = Counter()
        icu: Counter = Counter()
        for vid in self.missions:
            v = world.victims[vid]
            if v.destination_id in world.hospitals and v.status != VictimStatus.RESCUED:
                (icu if v.needs_icu else er)[v.destination_id] += 1
        return er, icu

    def _free_beds(self, world: World, exclude: set[str] | None = None) -> tuple[dict[str, int], dict[str, int]]:
        exclude = exclude or set()
        er: Counter = Counter()
        icu: Counter = Counter()
        for vid in self.missions:
            if vid in exclude:
                continue
            v = world.victims[vid]
            if v.destination_id in world.hospitals and v.status != VictimStatus.RESCUED:
                (icu if v.needs_icu else er)[v.destination_id] += 1
        er_free = {hid: max(0, h.er_free - er[hid]) for hid, h in world.hospitals.items()}
        icu_free = {hid: max(0, h.icu_free - icu[hid]) for hid, h in world.hospitals.items()}
        return er_free, icu_free

    def _unit_label(self, unit: Unit) -> str:
        return f"Ambulance {unit.id}" if isinstance(unit, Ambulance) else f"Team {unit.id}"

    def _target_label(self, task: PlanTask, world: World) -> str:
        if task.target_id:
            return f"{'Hospital' if task.target_id in world.hospitals else 'Safe zone'} {task.target_id}"
        if task.mission_id:
            return f"Victim {task.mission_id}"
        return str(task.target)

    def _update_ai_state(self, world: World) -> None:
        waiting = any(world.victims[vid].status == VictimStatus.WAITING for vid in self.known_victims)
        if self._replanned:
            self.ai_state = "REPLANNING"
        elif self._allocated:
            self.ai_state = "ALLOCATING RESOURCES"
        elif self.missions:
            self.ai_state = "EXECUTING PLAN"
        elif waiting:
            self.ai_state = "AWAITING RESOURCES"
        elif world.tick > 0:
            self.ai_state = "GOALS SATISFIED"
        else:
            self.ai_state = "STANDBY"

    def _log(self, phase: AgentPhase | str, level: str, message: str, details: list[str] | None = None) -> None:
        name = phase.value if isinstance(phase, AgentPhase) else phase
        self.log.add(self._tick, name, level, message, details)

    def _trace(self, phase: AgentPhase, summary: str) -> None:
        self.phase_trace.append({"phase": phase.value, "summary": summary})

    def _alert(self, code: str, title: str, message: str) -> None:
        self.alerts.append({"code": code, "title": title, "message": message, "tick": self._tick})
