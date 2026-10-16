"""Turn simulation objects into JSON-ready dictionaries for the UI."""

from __future__ import annotations

from app.environment.mobility import PROFILES
from app.environment.simulator import Simulation
from app.models.entities import Ambulance, Hospital, Pos, RescueTeam, SafeZone, Victim


def _pos(p: Pos) -> list[int]:
    return [p[0], p[1]]


def victim_dict(v: Victim) -> dict:
    return {
        "id": v.id,
        "pos": _pos(v.pos),
        "severity": v.severity.value,
        "health": round(v.health, 1),
        "health_status": v.health_status,
        "status": v.status.value,
        "priority": v.priority,
        "priority_breakdown": v.priority_breakdown,
        "trapped": v.trapped,
        "extracted": v.extracted,
        "needs_icu": v.needs_icu,
        "rescue_time": v.rescue_time,
        "rescue_progress": v.rescue_progress,
        "required_resources": v.required_resources,
        "carrier_id": v.carrier_id,
        "destination_id": v.destination_id,
        "assigned_units": v.assigned_units,
        "reported": v.reported,
        "reported_tick": v.reported_tick,
        "rescued_tick": v.rescued_tick,
        "deceased_tick": v.deceased_tick,
    }


def ambulance_dict(a: Ambulance) -> dict:
    return {
        "id": a.id,
        "kind": "AMBULANCE",
        "pos": _pos(a.pos),
        "capacity": a.capacity,
        "medical": a.medical.value,
        "capability": a.medical.value,
        "available": a.available,
        "status": a.status.value,
        "carrying": list(a.carrying),
        "distance": a.distance_travelled,
    }


def team_dict(t: RescueTeam) -> dict:
    return {
        "id": t.id,
        "kind": "TEAM",
        "pos": _pos(t.pos),
        "capacity": t.capacity,
        "medical": None,
        "capability": t.capability.value,
        "available": t.available,
        "status": t.status.value,
        "carrying": list(t.carrying),
        "distance": t.distance_travelled,
    }


def hospital_dict(h: Hospital, inbound_er: int, inbound_icu: int) -> dict:
    return {
        "id": h.id,
        "name": h.name,
        "pos": _pos(h.pos),
        "er_capacity": h.er_capacity,
        "er_occupancy": h.er_occupancy,
        "er_free": h.er_free,
        "icu_capacity": h.icu_capacity,
        "icu_occupancy": h.icu_occupancy,
        "icu_free": h.icu_free,
        "inbound_er": inbound_er,
        "inbound_icu": inbound_icu,
    }


def safe_zone_dict(s: SafeZone) -> dict:
    return {"id": s.id, "name": s.name, "pos": _pos(s.pos), "occupancy": s.occupancy, "capacity": s.capacity}


def snapshot(sim: Simulation, session_id: str, since: int = 0) -> dict:
    w = sim.world
    agent = sim.agent
    inbound_er, inbound_icu = agent._inbound(w)
    belief_diff = [
        {"pos": _pos(p), "belief": agent.belief.type_at(p).value, "truth": w.grid.type_at(p).value}
        for p in w.grid.positions()
        if agent.belief.type_at(p) != w.grid.type_at(p)
    ]
    return {
        "session_id": session_id,
        "scenario": sim.info.to_dict(),
        "tick": w.tick,
        "status": sim.status.value,
        "end_reason": sim.end_reason,
        "algorithm": agent.algorithm,
        "grid": {
            "rows": w.grid.rows,
            "cols": w.grid.cols,
            "cells": w.grid.to_codes(),
            "danger": w.grid.danger_matrix(),
            "version": w.grid.version,
        },
        "belief_version": agent.belief_version,
        "belief_diff": belief_diff,
        "victims": [victim_dict(w.victims[k]) for k in sorted(w.victims)],
        "ambulances": [ambulance_dict(w.ambulances[k]) for k in sorted(w.ambulances)],
        "teams": [team_dict(w.teams[k]) for k in sorted(w.teams)],
        "hospitals": [hospital_dict(h, inbound_er[h.id], inbound_icu[h.id]) for h in sorted(w.hospitals.values(), key=lambda h: h.id)],
        "safe_zones": [safe_zone_dict(s) for s in sorted(w.safe_zones.values(), key=lambda s: s.id)],
        "bases": [_pos(p) for p in w.bases],
        "plans": agent.unit_plans(w),
        "mission_tree": agent.root.to_dict(),
        "log": [e.to_dict() for e in agent.log.since(since)],
        "log_seq": agent.log.last_seq,
        "phase_trace": agent.phase_trace,
        "alerts": agent.alerts,
        "replan_events": agent.replan_events,
        "last_search": agent.last_search,
        "search_history": list(agent.search_history)[:12],
        "last_csp": agent.last_csp,
        "stats": sim.statistics(),
        "state": sim.state().to_dict(),
        "events": sim.events[-40:],
        "last_actions": sim.last_actions,
        "upcoming_events": [
            {"tick": t, "type": e.type.value, "label": e.label}
            for t, evs in sorted(sim.schedule.items())
            for e in evs
        ],
    }


def cell_info(sim: Simulation, pos: Pos) -> dict:
    w = sim.world
    if not w.grid.in_bounds(pos):
        raise ValueError(f"cell {pos} is outside the grid")
    truth = w.grid.cell(pos)
    belief_type = sim.agent.belief.type_at(pos)
    costs = {}
    for name, profile in PROFILES.items():
        c = profile.step_cost(w.grid, pos)
        costs[name] = {"accessible": c is not None, "cost": None if c is None else round(c, 2)}
    occupants = [u.id for u in w.units().values() if u.pos == pos]
    occupants += [v.id for v in w.victims.values() if v.pos == pos and (v.is_active or not v.reported)]
    facility = next((h.id for h in w.hospitals.values() if h.pos == pos), None)
    facility = facility or next((s.id for s in w.safe_zones.values() if s.pos == pos), None)
    return {
        **truth.to_dict(),
        "belief_type": belief_type.value,
        "known_to_agent": belief_type == truth.type,
        "profiles": costs,
        "occupants": occupants,
        "facility": facility,
    }
