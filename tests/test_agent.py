"""Tests for the rational agent, dynamic replanning and the simulator."""

from __future__ import annotations

import pytest

from app.agents.disaster_agent import AgentPhase, DisasterResponseAgent
from app.agents.priority import compute_priority
from app.environment.events import DisasterEvent, EventError, EventType
from app.environment.mobility import profile_for
from app.environment.simulator import Simulation
from app.models.actions import Action, ActionType, RescueMode
from app.models.entities import CellType, Severity, VictimStatus
from app.planning.planner import MOVEMENT_KINDS, TaskStatus
from app.search import GridSearchProblem
from app.search.astar import astar

SCENARIOS = ["EARTHQUAKE", "URBAN_FIRE", "FLOOD", "DEMO", "CUSTOM"]


def run_until(sim: Simulation, predicate, limit: int = 400) -> None:
    while not predicate(sim) and sim.tick < limit and sim.status.value not in ("COMPLETE", "STALLED"):
        sim.step()


def active_legs(sim: Simulation):
    for uid, agenda in sim.agent.agendas.items():
        for t in agenda:
            if t.kind in MOVEMENT_KINDS and t.status == TaskStatus.ACTIVE and len(t.remaining_path) >= 8:
                yield uid, t


def blockable_cells(sim: Simulation):
    """(unit, leg, cell) where blocking `cell` invalidates the leg but a detour exists."""
    occupied = sim.world.unit_positions() | {v.pos for v in sim.world.victims.values()}
    for uid, leg in active_legs(sim):
        profile = profile_for(sim.world.unit(uid))
        path = leg.remaining_path
        for cell in path[3:-2]:
            if sim.world.grid.type_at(cell) != CellType.ROAD or cell in occupied:
                continue
            trial = sim.agent.belief.copy()
            trial.set_type(cell, CellType.OBSTACLE)
            if astar(GridSearchProblem(trial, path[0], path[-1], profile)).found:
                yield uid, leg, cell


def messages(sim: Simulation, since: int = 0) -> list[str]:
    return [e.message for e in sim.agent.log if e.seq > since]


def check_invariants(sim: Simulation) -> None:
    w = sim.world
    for h in w.hospitals.values():
        assert h.er_occupancy <= h.er_capacity, f"{h.id} ER over capacity"
        assert h.icu_occupancy <= h.icu_capacity, f"{h.id} ICU over capacity"
    for u in w.units().values():
        assert len(u.carrying) <= u.capacity
        assert profile_for(u).passable(w.grid.type_at(u.pos)) or w.grid.type_at(u.pos) in (CellType.FIRE, CellType.WATER, CellType.OBSTACLE)
    # A rescue team never works on two missions at once.
    for tid in w.teams:
        missions = [m for m in sim.agent.missions.values() if tid in m.option.units
                    and any(t.is_open for t in sim.agent.agendas.get(tid, []) if t.mission_id == m.victim_id)]
        assert len(missions) <= 1


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_scenario_completes_with_invariants(scenario):
    sim = Simulation(scenario)
    while sim.status.value not in ("COMPLETE", "STALLED") and sim.tick < 400:
        sim.step()
        check_invariants(sim)
    stats = sim.statistics()
    assert sim.status.value == "COMPLETE", sim.end_reason
    assert stats["rescued_victims"] + stats["deceased_victims"] == stats["total_victims"]
    assert stats["rescued_victims"] >= stats["total_victims"] - 1
    assert sim.state().is_goal


def test_decision_cycle_runs_all_eight_phases_in_order():
    sim = Simulation("EARTHQUAKE")
    sim.step()
    assert [p["phase"] for p in sim.agent.phase_trace] == [p.value for p in AgentPhase]


def test_agent_replans_when_user_blocks_a_road_on_an_active_route():
    sim = Simulation("EARTHQUAKE")
    run_until(sim, lambda s: any(True for _ in active_legs(s)))
    uid, leg, blocked = next(blockable_cells(sim))
    seq = sim.agent.log.last_seq
    replans_before = sim.agent.metrics.replans
    sim.inject(DisasterEvent(EventType.BLOCK_ROAD, target=blocked))

    log = messages(sim, seq)
    assert "ENVIRONMENT CHANGE DETECTED" in log
    assert any(m.startswith("Mission affected") for m in log)
    assert any(m.startswith("Stopping current plan") for m in log)
    assert any(m.startswith("New path generated") for m in log)
    assert any(m.startswith("Mission resumed") for m in log)
    assert sim.agent.metrics.replans > replans_before
    assert blocked not in leg.remaining_path
    assert leg.replans >= 1
    assert sim.agent.replan_events and sim.agent.replan_events[0]["unit_id"] == uid
    # The mission still completes after the disruption.
    run_until(sim, lambda s: False)
    assert sim.status.value == "COMPLETE"
    assert sim.world.unit(uid).pos != blocked


def test_auto_targeted_block_lands_on_an_active_route():
    sim = Simulation("EARTHQUAKE")
    run_until(sim, lambda s: any(True for _ in active_legs(s)))
    routes = {tuple(p) for h in sim.agent.route_hints() for p in h.path}
    report = sim.inject(DisasterEvent(EventType.BLOCK_ROAD))
    assert report.cells[0] in routes
    assert sim.agent.replan_events


def test_hidden_hazards_are_discovered_by_sensors_and_trigger_replanning():
    sim = Simulation("EARTHQUAKE")
    hidden = set(sim.world.hidden_hazards)
    assert hidden and all(sim.agent.belief.type_at(p) == CellType.ROAD for p in hidden)
    run_until(sim, lambda s: s.agent.metrics.hazards_discovered > 0)
    assert sim.agent.metrics.hazards_discovered > 0
    discovered = [p for p in hidden if sim.agent.belief.type_at(p) == CellType.OBSTACLE]
    assert discovered
    assert any("revealed by sensors" in m for m in messages(sim))


def test_unreported_victim_is_discovered_and_rescued():
    sim = Simulation("EARTHQUAKE")
    hidden_victims = [v.id for v in sim.world.victims.values() if not v.reported]
    assert hidden_victims
    run_until(sim, lambda s: False)
    for vid in hidden_victims:
        assert sim.world.victims[vid].reported
        assert sim.world.victims[vid].status == VictimStatus.RESCUED


def test_ambulance_breakdown_causes_reassignment():
    sim = Simulation("EARTHQUAKE")
    run_until(sim, lambda s: any(m.option.ambulance for m in s.agent.missions.values()))
    vid, mission = next((k, m) for k, m in sim.agent.missions.items() if m.option.ambulance)
    amb = mission.option.ambulance
    pos = sim.world.ambulances[amb].pos
    sim.inject(DisasterEvent(EventType.REMOVE_AMBULANCE, params={"unit_id": amb}))
    assert not sim.world.ambulances[amb].available
    assert sim.agent.metrics.reassignments >= 1
    assert all(amb not in m.option.units for m in sim.agent.missions.values())
    run_until(sim, lambda s: False)
    assert sim.world.ambulances[amb].pos == pos  # an unavailable unit never moves again
    assert sim.world.victims[vid].status in (VictimStatus.RESCUED, VictimStatus.DECEASED)


def test_hospital_capacity_reduction_reallocates_destinations():
    sim = Simulation("EARTHQUAKE")
    run_until(sim, lambda s: sum(1 for m in s.agent.missions.values() if m.option.destination == "H1") >= 2)
    inbound = [vid for vid, m in sim.agent.missions.items() if sim.world.victims[vid].destination_id == "H1"]
    h1 = sim.world.hospitals["H1"]
    sim.inject(DisasterEvent(EventType.REDUCE_HOSPITAL_CAPACITY, params={"hospital_id": "H1", "er": 99, "icu": 99}))
    assert h1.er_free == 0 and h1.icu_free == 0
    assert sim.agent.metrics.destination_changes + sim.agent.metrics.reassignments >= 1
    assert sim.agent.last_csp["kind"] == "DESTINATION_REALLOCATION"
    for vid in inbound:
        assert sim.world.victims[vid].destination_id != "H1"
    run_until(sim, lambda s: False)
    assert h1.er_occupancy <= h1.er_capacity and h1.icu_occupancy <= h1.icu_capacity


def test_new_victim_event_creates_a_goal_and_mission():
    sim = Simulation("FLOOD")
    run_until(sim, lambda s: s.tick >= 5)
    report = sim.inject(DisasterEvent(EventType.ADD_VICTIM, params={"severity": "CRITICAL"}))
    vid = report.victim_ids[0]
    assert vid in sim.agent.known_victims
    run_until(sim, lambda s: False)
    assert sim.world.victims[vid].status == VictimStatus.RESCUED


def test_invalid_user_events_are_rejected():
    sim = Simulation("EARTHQUAKE")
    with pytest.raises(EventError):
        sim.inject(DisasterEvent(EventType.BLOCK_ROAD, target=(0, 0)))  # a building
    with pytest.raises(EventError):
        sim.inject(DisasterEvent(EventType.REMOVE_AMBULANCE, params={"unit_id": "A99"}))


def test_transition_model_rejects_illegal_actions():
    sim = Simulation("EARTHQUAKE")
    amb = sim.world.ambulances["A1"]
    r, c = amb.pos
    wall = next(n for n in sim.world.grid.neighbors4(amb.pos) if sim.world.grid.type_at(n) == CellType.BUILDING)
    assert not sim.execute(Action(ActionType.MOVE, "A1", target=wall)).success
    assert not sim.execute(Action(ActionType.MOVE, "A1", target=(r - 5, c))).success
    res = sim.execute(Action(ActionType.RESCUE, "A1", victim_ids=("V01",), mode=RescueMode.LOAD))
    assert not res.success and "not at" in res.message
    assert amb.pos == (r, c)


def test_algorithm_switch_is_used_for_new_routes():
    sim = Simulation("EARTHQUAKE", algorithm="BFS")
    sim.step()
    algos = {t.algorithm for agenda in sim.agent.agendas.values() for t in agenda if t.kind in MOVEMENT_KINDS}
    assert algos == {"BFS"}
    with pytest.raises(ValueError):
        DisasterResponseAgent(sim.world, algorithm="DIJKSTRA")


def test_priority_breakdown_explains_the_score():
    sim = Simulation("EARTHQUAKE")
    grid = sim.agent.belief
    crit = sim.world.victims["V01"]
    low = sim.world.victims["V08"]
    p_crit, breakdown = compute_priority(crit, grid, 0)
    p_low, _ = compute_priority(low, grid, 0)
    assert p_crit > p_low
    assert sum(f["points"] for f in breakdown) == pytest.approx(p_crit, abs=0.2)
    assert {f["factor"] for f in breakdown} >= {"Severity", "Health deficit", "Survival window", "Hazard exposure"}


def test_state_space_snapshot_is_hashable_and_tracks_progress():
    sim = Simulation("EARTHQUAKE")
    s0 = sim.state()
    sim.step()
    s1 = sim.state()
    assert hash(s0) != hash(s1) or s0 != s1
    assert not s1.is_goal
    assert s1.tick == 1
    assert set(dict(s1.resource_positions)) == set(sim.world.units())
    assert s1.to_dict()["remaining_victims"]


def test_severity_never_downgrades_and_critical_victims_go_first():
    sim = Simulation("DEMO")
    sim.step()
    first_missions = {vid for vid in sim.agent.missions}
    crit = {v.id for v in sim.world.victims.values() if v.reported and v.severity == Severity.CRITICAL}
    assert crit <= first_missions


def test_ambulance_breakdown_keeps_the_team_on_a_trapped_critical_victim():
    from app.csp.allocation import METHOD_EXTRACT, METHOD_EXTRACT_ONLY

    sim = Simulation("EARTHQUAKE")
    run_until(sim, lambda s: "V01" in s.agent.missions and s.agent.missions["V01"].option.method == METHOD_EXTRACT)
    mission = sim.agent.missions["V01"]
    team = mission.option.team
    sim.inject(DisasterEvent(EventType.REMOVE_AMBULANCE, params={"unit_id": mission.option.ambulance}))
    new = sim.agent.missions.get("V01")
    assert new is not None, "the critical victim must not be left without a plan"
    if new.option.method == METHOD_EXTRACT_ONLY:
        assert new.option.team == team  # same team continues the extraction it started
    run_until(sim, lambda s: False)
    assert sim.world.victims["V01"].status == VictimStatus.RESCUED


def test_replan_is_an_action_inside_a_tick_and_the_mission_resumes_next_tick():
    sim = Simulation("EARTHQUAKE")
    seen = None
    while sim.status.value not in ("COMPLETE", "STALLED") and sim.tick < 300:
        before = {u.id: u.pos for u in sim.world.units().values()}
        sim.step()
        replans = [a for a in sim.last_actions if a["type"] == "REPLAN"]
        if replans:
            seen = (sim.tick, replans[0]["unit_id"])
            # Replanning consumes the cycle: the unit does not move this tick.
            assert sim.world.unit(seen[1]).pos == before[seen[1]]
            break
    assert seen is not None, "an in-tick replan (e.g. after a sensor discovery) should occur"
    tick, uid = seen
    # Another disruption can force a further replan, but the unit resumes within a few ticks.
    for _ in range(5):
        sim.step()
    resumed = [e for e in sim.agent.log if tick < e.tick <= tick + 5 and e.message.startswith("Mission resumed") and uid in e.message]
    assert resumed


def test_state_is_built_from_the_belief_map_not_ground_truth():
    sim = Simulation("EARTHQUAKE")
    hidden = set(sim.world.hidden_hazards)
    state = sim.state()
    assert hidden and not (hidden & set(state.blocked_roads))


def test_critical_victim_pre_empts_a_less_urgent_ambulance_mission():
    sim = Simulation("EARTHQUAKE")
    run_until(sim, lambda s: any(e.message.startswith("Pre-emption") for e in s.agent.log))
    pre = [e for e in sim.agent.log if e.message.startswith("Pre-emption")]
    assert pre, "with both ALS ambulances busy on non-critical missions, the late critical victim must pre-empt one"
    displaced = pre[0].message.split(" diverted from ")[1].split(" ")[0]
    assert sim.world.victims[displaced].severity != Severity.CRITICAL
    run_until(sim, lambda s: False)
    assert sim.status.value == "COMPLETE"
    assert sim.world.victims[displaced].status == VictimStatus.RESCUED
