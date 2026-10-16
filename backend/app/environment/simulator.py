"""Discrete-time simulation engine.

One tick of the simulation:

    1. advance time; apply scheduled scenario events
    2. run natural dynamics (fire spread, rising flood water)
    3. update victims (deterioration, death, severity escalation)
    4. agent decision cycle: PERCEIVE ... SELECT ACTION  -> one action per unit
    5. EXECUTE every action through the transition model T(s, a)
    6. agent OBSERVES the results
    7. update the mission status

User events can be injected between ticks; the agent reacts to them
immediately (perceive -> replan) without advancing time.
"""

from __future__ import annotations

from enum import Enum

from app.agents.disaster_agent import DisasterResponseAgent
from app.agents.priority import DANGER_DECAY_FACTOR
from app.environment.events import (
    DisasterEvent,
    EnvironmentReport,
    EventError,
    EventType,
    apply_event,
    rise_flood,
    spread_fire,
)
from app.environment.mobility import profile_for
from app.environment.scenarios import build_scenario
from app.models.actions import Action, ActionResult, ActionType, RescueMode
from app.models.entities import (
    SEVERITY_DECAY,
    Ambulance,
    MedicalLevel,
    Severity,
    UnitStatus,
    VictimStatus,
)
from app.models.state import WorldState, capture_state

TIME_LIMIT = 600
TRANSIT_DECAY = {"ALS": 0.15, "BLS": 0.4, "TEAM": 0.5}
ON_SCENE_DECAY = 0.8


class SimulationStatus(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    STALLED = "STALLED"


class Simulation:
    def __init__(
        self,
        scenario_id: str = "EARTHQUAKE",
        seed: int | None = None,
        algorithm: str = "ASTAR",
        custom: dict | None = None,
    ):
        self.scenario_id = scenario_id.upper()
        self.seed = seed
        self.custom = custom
        self.algorithm = DisasterResponseAgent._validate_algorithm(algorithm)
        self.reset()

    # ------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        built = build_scenario(self.scenario_id, seed=self.seed, custom=self.custom)
        self.world = built.world
        self.info = built.info
        self.schedule: dict[int, list[DisasterEvent]] = built.schedule
        self.agent = DisasterResponseAgent(self.world, self.algorithm)
        self.agent.preview_priorities(self.world)
        self.status = SimulationStatus.READY
        self.end_reason: str | None = None
        self.events: list[dict] = []  # every environment report so far
        self.last_reports: list[dict] = []
        self.last_actions: list[dict] = []
        self.agent.log.add(0, "SYSTEM", "INFO", f"Scenario loaded: {self.info.name}", [self.info.description])

    def set_algorithm(self, algorithm: str) -> None:
        self.agent.set_algorithm(algorithm)
        self.algorithm = self.agent.algorithm

    @property
    def tick(self) -> int:
        return self.world.tick

    # ------------------------------------------------------------------ step
    def step(self) -> None:
        if self.status == SimulationStatus.COMPLETE:
            return
        w = self.world
        w.tick += 1
        self.status = SimulationStatus.RUNNING
        reports: list[EnvironmentReport] = []
        if w.tick == 1:
            reports.append(self._situation_report())

        for event in self.schedule.pop(w.tick, []):
            try:
                reports.append(apply_event(w, event, self.agent.route_hints()))
            except EventError as exc:
                self.agent.log.add(w.tick, "SYSTEM", "INFO", f"Scheduled event skipped: {exc}")

        dyn = w.dynamics
        if dyn.fire_spread_interval and w.tick % dyn.fire_spread_interval == 0:
            rep = spread_fire(w)
            if rep:
                reports.append(rep)
        if dyn.flood_interval and w.tick % dyn.flood_interval == 0:
            rep = rise_flood(w)
            if rep:
                reports.append(rep)
        reports += self._update_victims()

        actions = self.agent.decide(w, reports)
        results = [self.execute(a) for a in actions]
        self.agent.observe(w, results)

        self._record(reports)
        self.last_actions = [r.action.to_dict() | {"success": r.success, "message": r.message} for r in results]
        self._update_status()

    def inject(self, event: DisasterEvent) -> EnvironmentReport:
        """Apply a user event now and let the agent react immediately."""
        report = apply_event(self.world, event, self.agent.route_hints())
        self.agent.decide(self.world, [report], reactive=True)  # perceive & replan; actions run on the next tick
        self._record([report])
        self.last_actions = []
        if self.status in (SimulationStatus.COMPLETE, SimulationStatus.STALLED):
            self.status = SimulationStatus.RUNNING
            self.end_reason = None
        self._update_status()
        return report

    # ------------------------------------------------------ transition model
    def execute(self, action: Action) -> ActionResult:
        """T(s, a): apply one primitive action to the world."""
        w = self.world
        unit = w.unit(action.unit_id)
        if not unit.available:
            return ActionResult(action, False, message=f"{unit.id} is out of service")

        if action.type == ActionType.WAIT:
            unit.status = UnitStatus.IDLE if action.detail == "standby" else UnitStatus.WAITING
            return ActionResult(action, True)

        if action.type == ActionType.REPLAN:
            # The unit holds position for one cycle while it switches to the new plan.
            return ActionResult(action, True)

        if action.type in (ActionType.MOVE, ActionType.TRANSPORT):
            to = action.target
            if to is None or abs(to[0] - unit.pos[0]) + abs(to[1] - unit.pos[1]) != 1:
                return ActionResult(action, False, message=f"{to} is not adjacent to {unit.pos}")
            cell = w.grid.type_at(to)
            if not profile_for(unit).passable(cell):
                return ActionResult(action, False, message=f"cannot enter {cell.value} at {to}")
            unit.pos = to
            unit.distance_travelled += 1
            for vid in unit.carrying:
                w.victims[vid].pos = to
            unit.status = UnitStatus.TRANSPORTING if unit.carrying else UnitStatus.EN_ROUTE
            return ActionResult(action, True)

        if action.type == ActionType.RESCUE:
            victim = w.victims.get(action.victim_ids[0]) if action.victim_ids else None
            if victim is None or not victim.is_active:
                return ActionResult(action, False, message="victim is no longer awaiting rescue")
            if victim.pos != unit.pos:
                return ActionResult(action, False, message=f"{unit.id} is not at {victim.id}'s location")
            if victim.carrier_id is not None:
                return ActionResult(action, False, message=f"{victim.id} is already on board {victim.carrier_id}")
            unit.status = UnitStatus.ON_SCENE
            victim.status = VictimStatus.BEING_RESCUED
            if action.mode == RescueMode.EXTRACT:
                victim.rescue_progress += 1
                if victim.rescue_progress >= action.duration:
                    victim.extracted = True
                    victim.rescue_progress = 0
                    return ActionResult(action, True, completed=True)
                return ActionResult(action, True)
            # Ambulance crews cannot free trapped victims; rescue teams extract while loading.
            if victim.trapped and not victim.extracted and isinstance(unit, Ambulance):
                return ActionResult(action, False, message=f"{victim.id} is still trapped")
            if len(unit.carrying) >= unit.capacity:
                return ActionResult(action, False, message=f"{unit.id} is full")
            victim.rescue_progress += 1
            if victim.rescue_progress >= action.duration:
                victim.rescue_progress = 0
                victim.extracted = True
                victim.carrier_id = unit.id
                victim.status = VictimStatus.IN_TRANSIT
                unit.carrying.append(victim.id)
                return ActionResult(action, True, completed=True)
            return ActionResult(action, True)

        if action.type in (ActionType.DELIVER_TO_HOSPITAL, ActionType.DELIVER_TO_SAFE_ZONE):
            dest = w.destination(action.destination_id)
            if unit.pos != dest.pos:
                return ActionResult(action, False, message=f"{unit.id} is not at {dest.id}")
            delivered = [vid for vid in action.victim_ids if vid in unit.carrying]
            if not delivered:
                return ActionResult(action, False, message="no matching patient on board")
            for vid in delivered:
                v = w.victims[vid]
                unit.carrying.remove(vid)
                v.carrier_id = None
                v.pos = dest.pos
                v.status = VictimStatus.RESCUED
                v.rescued_tick = w.tick
                if action.destination_id in w.hospitals:
                    h = w.hospitals[action.destination_id]
                    if v.needs_icu:
                        h.icu_occupancy += 1
                    else:
                        h.er_occupancy += 1
                else:
                    w.safe_zones[action.destination_id].occupancy += 1
            unit.status = UnitStatus.IDLE
            return ActionResult(action, True, completed=True, effects=[f"{vid} delivered" for vid in delivered])

        return ActionResult(action, False, message=f"unsupported action {action.type.value}")

    # ------------------------------------------------------------- helpers
    def _situation_report(self) -> EnvironmentReport:
        w = self.world
        reported = [v for v in w.victims.values() if v.reported]
        return EnvironmentReport(
            tick=w.tick,
            event_type=EventType.SITUATION_REPORT,
            source="SCENARIO",
            title=f"Initial situation report: {self.info.name}",
            description=(
                f"{len(reported)} victims reported ({sum(v.severity == Severity.CRITICAL for v in reported)} critical); "
                f"{len(w.ambulances)} ambulances, {len(w.teams)} rescue teams, {len(w.hospitals)} hospitals available."
            ),
        )

    def _update_victims(self) -> list[EnvironmentReport]:
        w = self.world
        reports: list[EnvironmentReport] = []
        for vid in sorted(w.victims):
            v = w.victims[vid]
            if v.status in (VictimStatus.RESCUED, VictimStatus.DECEASED):
                continue
            if v.carrier_id:
                carrier = w.unit(v.carrier_id)
                if isinstance(carrier, Ambulance):
                    factor = TRANSIT_DECAY["ALS" if carrier.medical == MedicalLevel.ALS else "BLS"]
                else:
                    factor = TRANSIT_DECAY["TEAM"]
                danger = 0.0
            else:
                factor = ON_SCENE_DECAY if v.status == VictimStatus.BEING_RESCUED else 1.0
                danger = w.grid.danger_at(v.pos)
            v.health = max(0.0, v.health - SEVERITY_DECAY[v.severity] * factor * (1 + DANGER_DECAY_FACTOR * danger))
            if v.health <= 0:
                v.status = VictimStatus.DECEASED
                v.deceased_tick = w.tick
                if v.carrier_id:
                    w.unit(v.carrier_id).carrying.remove(v.id)
                    v.carrier_id = None
                if v.reported:
                    reports.append(
                        EnvironmentReport(w.tick, EventType.VICTIM_DECEASED, "NATURAL", f"Victim {v.id} deceased",
                                          f"{v.id} ({v.severity.value}) died at {v.pos}.", victim_ids=[v.id])
                    )
                continue
            if v.reported and v.status == VictimStatus.WAITING:
                escalated = None
                if v.severity == Severity.MEDIUM and v.health < 45:
                    escalated = Severity.HIGH
                elif v.severity == Severity.HIGH and v.health < 28:
                    escalated = Severity.CRITICAL
                if escalated:
                    old = v.severity
                    v.severity = escalated
                    v.needs_icu = v.needs_icu or escalated == Severity.CRITICAL
                    reports.append(
                        EnvironmentReport(w.tick, EventType.SITUATION_REPORT, "NATURAL", f"{v.id} deteriorated to {escalated.value}",
                                          f"{v.id} condition worsened: {old.value} -> {escalated.value} (health {v.health:.0f}%).",
                                          victim_ids=[v.id])
                    )
        return reports

    def _record(self, reports: list[EnvironmentReport]) -> None:
        dicts = [r.to_dict() for r in reports]
        self.last_reports = dicts
        self.events.extend(d for d in dicts if d["event_type"] != EventType.SITUATION_REPORT.value or d["victim_ids"])
        self.events = self.events[-200:]

    def _update_status(self) -> None:
        w = self.world
        active = [v for v in w.victims.values() if v.reported and v.is_active]
        if w.tick >= TIME_LIMIT:
            self.status = SimulationStatus.COMPLETE
            self.end_reason = f"time limit of {TIME_LIMIT} ticks reached"
        elif not active and not self.agent.missions and not self.schedule:
            if w.tick > 0:
                self.status = SimulationStatus.COMPLETE
                self.end_reason = "all known victims resolved"
        elif active and not self.schedule and w.tick > 0 and self.agent.is_stalled(w):
            self.status = SimulationStatus.STALLED
            self.end_reason = "remaining victims cannot be served with the available resources"
        elif w.tick > 0:
            self.status = SimulationStatus.RUNNING
            self.end_reason = None

    # ------------------------------------------------------------- queries
    def state(self) -> WorldState:
        # The state is the agent's representation: terrain comes from its belief map.
        return capture_state(self.world, self.agent.current_task_labels(self.world), self.agent.belief)

    def statistics(self) -> dict:
        w = self.world
        agent = self.agent
        known = [v for v in w.victims.values() if v.reported]
        rescued = [v for v in known if v.status == VictimStatus.RESCUED]
        deceased = [v for v in known if v.status == VictimStatus.DECEASED]
        active = [v for v in known if v.is_active]
        rescue_times = [v.rescued_tick - v.reported_tick for v in rescued if v.rescued_tick is not None]
        units = w.units()
        busy = {uid for uid in units if units[uid].available and not agent._is_idle(uid)}
        current = None
        if agent.missions:
            vid = max(agent.missions, key=lambda k: (w.victims[k].priority, k))
            labels = agent.current_task_labels(w)
            unit_tasks = [f"{u}: {labels.get(u)}" for u in agent.missions[vid].option.units]
            current = f"Rescue {vid} [{w.victims[vid].severity.value}] - " + "; ".join(unit_tasks)
        return {
            "tick": w.tick,
            "active_victims": len(active),
            "rescued_victims": len(rescued),
            "deceased_victims": len(deceased),
            "critical_victims": sum(1 for v in active if v.severity == Severity.CRITICAL),
            "unreported_victims": sum(1 for v in w.victims.values() if not v.reported and v.status == VictimStatus.UNREPORTED),
            "total_victims": len(known),
            "active_ambulances": sum(1 for a in w.ambulances if a in busy),
            "available_ambulances": sum(1 for a in w.ambulances.values() if a.available),
            "total_ambulances": len(w.ambulances),
            "active_teams": sum(1 for t in w.teams if t in busy),
            "available_teams": sum(1 for t in w.teams.values() if t.available),
            "total_teams": len(w.teams),
            "hospital_capacity": {
                "er_free": sum(h.er_free for h in w.hospitals.values()),
                "er_total": sum(h.er_capacity for h in w.hospitals.values()),
                "icu_free": sum(h.icu_free for h in w.hospitals.values()),
                "icu_total": sum(h.icu_capacity for h in w.hospitals.values()),
            },
            "current_mission": current,
            "ai_state": agent.ai_state,
            "replanning_count": agent.metrics.replans,
            "total_distance": sum(u.distance_travelled for u in units.values()),
            "total_rescue_time": sum(rescue_times),
            "avg_rescue_time": round(sum(rescue_times) / len(rescue_times), 1) if rescue_times else None,
            "missions_active": len(agent.missions),
            "agent": agent.metrics.to_dict(),
        }
