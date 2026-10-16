"""Tests for the hierarchical (HTN) mission planner."""

from __future__ import annotations

import json

from helpers import build_world, is_valid_path, small_city
from app.csp.allocation import (
    METHOD_DIRECT,
    METHOD_EVACUATE,
    METHOD_EXTRACT,
    AllocationOption,
    RouteOracle,
)
from app.environment.mobility import GROUND_VEHICLE, profile_for
from app.models.entities import CellType, MedicalLevel, Severity, TeamCapability
from app.planning.planner import HierarchicalPlanner, TaskKind, TaskStatus


def world_and_route():
    b = small_city()
    b.hospital("H1", "General", (1, 3), er=4, icu=2)
    b.safe_zone("S1", "Park", [(8, 8)], entry=(8, 8))
    b.ambulance("A1", (12, 0), MedicalLevel.ALS)
    b.ambulance("A2", (12, 12), MedicalLevel.BLS, capacity=2)
    b.team("T1", (0, 12), TeamCapability.URBAN_SAR)
    b.victim("V01", (7, 4), Severity.CRITICAL, 40, 3)
    b.victim("V02", (2, 10), Severity.HIGH, 55, 3, trapped=True)
    b.victim("V03", (7, 10), Severity.LOW, 90, 1)
    b.victim("V04", (12, 5), Severity.MEDIUM, 70, 2)
    b.victim("V05", (9, 12), Severity.MEDIUM, 71, 2)
    world = build_world(b)
    oracle = RouteOracle(world.grid, "ASTAR")

    def route(start, goal, profile, _label):
        return oracle.route(start, goal, profile)

    return world, route


def kinds(tasks):
    return [t.kind for t in tasks]


def test_ambulance_direct_decomposition():
    world, route = world_and_route()
    planner = HierarchicalPlanner()
    v = world.victims["V01"]
    [plan] = planner.plan_round([(v, AllocationOption(METHOD_DIRECT, ambulance="A1", destination="H1"))], world, world.grid, route)
    assert plan.failed is None
    root = plan.roots["V01"]
    assert root.kind == TaskKind.RESCUE_VICTIM
    assert kinds(root.children) == [
        TaskKind.ASSIGN_RESOURCES, TaskKind.NAVIGATE, TaskKind.RESCUE, TaskKind.SELECT_DESTINATION,
        TaskKind.TRANSPORT, TaskKind.DELIVER, TaskKind.UPDATE_RESOURCES,
    ]
    agenda = plan.agendas["A1"]
    assert kinds(agenda) == [TaskKind.NAVIGATE, TaskKind.RESCUE, TaskKind.TRANSPORT, TaskKind.DELIVER, TaskKind.UPDATE_RESOURCES]
    nav, rescue, transport, deliver, _update = agenda
    assert nav.path[0] == world.ambulances["A1"].pos and nav.path[-1] == v.pos
    assert transport.path[0] == v.pos and transport.path[-1] == world.hospitals["H1"].pos
    assert is_valid_path(nav.path, world.grid, GROUND_VEHICLE)
    assert is_valid_path(transport.path, world.grid, GROUND_VEHICLE)
    assert rescue.duration == v.rescue_time
    assert deliver.target_id == "H1"
    # Decisions already taken by the CSP are recorded as completed sub-goals.
    assert root.children[0].status == TaskStatus.DONE and root.children[3].status == TaskStatus.DONE


def test_extract_and_transport_synchronises_team_and_ambulance():
    world, route = world_and_route()
    planner = HierarchicalPlanner()
    v = world.victims["V02"]
    [plan] = planner.plan_round(
        [(v, AllocationOption(METHOD_EXTRACT, ambulance="A1", team="T1", destination="H1"))], world, world.grid, route
    )
    team_agenda, amb_agenda = plan.agendas["T1"], plan.agendas["A1"]
    assert kinds(team_agenda) == [TaskKind.NAVIGATE, TaskKind.EXTRACT, TaskKind.UPDATE_RESOURCES]
    extract = team_agenda[1]
    load = amb_agenda[1]
    assert load.kind == TaskKind.RESCUE and load.depends_on == [extract]
    assert extract.duration == v.rescue_time and load.duration == 1
    assert is_valid_path(team_agenda[0].path, world.grid, profile_for(world.teams["T1"]))


def test_team_evacuation_to_safe_zone():
    world, route = world_and_route()
    planner = HierarchicalPlanner()
    v = world.victims["V03"]
    [plan] = planner.plan_round([(v, AllocationOption(METHOD_EVACUATE, team="T1", destination="S1"))], world, world.grid, route)
    agenda = plan.agendas["T1"]
    assert kinds(agenda) == [TaskKind.NAVIGATE, TaskKind.RESCUE, TaskKind.TRANSPORT, TaskKind.DELIVER, TaskKind.UPDATE_RESOURCES]
    assert agenda[2].path[-1] == world.safe_zones["S1"].pos
    assert "safe zone" in plan.roots["V03"].children[3].label


def test_shared_trip_merges_pickups_into_one_agenda():
    world, route = world_and_route()
    planner = HierarchicalPlanner()
    a = (world.victims["V04"], AllocationOption(METHOD_DIRECT, ambulance="A2", destination="H1"))
    b = (world.victims["V05"], AllocationOption(METHOD_DIRECT, ambulance="A2", destination="H1"))
    [plan] = planner.plan_round([a, b], world, world.grid, route)
    agenda = plan.agendas["A2"]
    assert kinds(agenda) == [
        TaskKind.NAVIGATE, TaskKind.RESCUE, TaskKind.NAVIGATE, TaskKind.RESCUE,
        TaskKind.TRANSPORT, TaskKind.DELIVER, TaskKind.UPDATE_RESOURCES,
    ]
    transport = agenda[4]
    assert sorted(transport.victim_ids) == ["V04", "V05"]
    # Legs chain together: each leg starts where the previous one ended.
    assert agenda[2].path[0] == agenda[0].path[-1]
    assert transport.path[0] == agenda[2].path[-1]
    # Both victims' sub-trees show the shared transport (as mirrors).
    for vid in ("V04", "V05"):
        mirrored = [t for t in plan.roots[vid].children if t.kind == TaskKind.TRANSPORT]
        assert len(mirrored) == 1 and mirrored[0].mirror_of is transport
    transport.set_status(TaskStatus.DONE)
    assert all(m.status == TaskStatus.DONE for m in transport.mirrors)


def test_planning_failure_is_reported_not_raised():
    world, route = world_and_route()
    for p in [(6, 4), (8, 4), (7, 3), (7, 5)]:
        world.grid.set_type(p, CellType.OBSTACLE)  # wall the victim in
    planner = HierarchicalPlanner()
    v = world.victims["V01"]
    [plan] = planner.plan_round([(v, AllocationOption(METHOD_DIRECT, ambulance="A1", destination="H1"))], world, world.grid, route)
    assert plan.failed and "no route" in plan.failed
    assert plan.roots == {}


def test_plan_tree_serialises_to_json():
    world, route = world_and_route()
    planner = HierarchicalPlanner()
    v = world.victims["V02"]
    [plan] = planner.plan_round(
        [(v, AllocationOption(METHOD_EXTRACT, ambulance="A1", team="T1", destination="H1"))], world, world.grid, route
    )
    data = plan.roots["V02"].to_dict()
    text = json.dumps(data)
    assert "Extract V02" in text
    nav = next(c for c in data["children"] if c["kind"] == "NAVIGATE")
    assert nav["steps"] > 0 and nav["algorithm"] == "ASTAR"


def test_shared_trip_is_rejected_when_the_first_patient_would_ride_a_long_detour():
    import dataclasses

    world, route = world_and_route()
    a, b = world.victims["V04"], world.victims["V05"]

    def route_with_detour(start, goal, profile, label):
        res = route(start, goal, profile, label)
        if {start, goal} == {a.pos, b.pos}:  # the leg between the two pick-ups is now very long
            res = dataclasses.replace(res, cost=res.cost + 100)
        return res

    planner = HierarchicalPlanner()
    plans = planner.plan_round(
        [(a, AllocationOption(METHOD_DIRECT, ambulance="A2", destination="H1")),
         (b, AllocationOption(METHOD_DIRECT, ambulance="A2", destination="H1"))],
        world, world.grid, route_with_detour,
    )
    ok = [p for p in plans if p.failed is None]
    rejected = [p for p in plans if p.failed]
    assert len(ok) == 1 and len(rejected) == 1
    assert "shared trip rejected" in rejected[0].failed
    agenda = ok[0].agendas["A2"]
    assert [t.kind for t in agenda].count(TaskKind.NAVIGATE) == 1  # one pick-up, straight to hospital
