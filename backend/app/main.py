"""FastAPI application: REST API for the simulation, Algorithm Lab and static UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.environment.events import USER_EVENT_TYPES, DisasterEvent, EventError, EventType
from app.environment.grid import Grid
from app.environment.mobility import PROFILES
from app.environment.scenarios import build_scenario, list_scenarios
from app.models.schemas import (
    AlgorithmRequest,
    BenchmarkRequest,
    CompareRequest,
    CreateSimulationRequest,
    EventRequest,
    LabSource,
    OnlineRequest,
    ReplayRequest,
    StepRequest,
)
from app.search import ALGORITHM_LABELS, ALGORITHMS
from app.services import algorithm_lab
from app.services.serializers import cell_info, snapshot
from app.services.session_manager import SessionManager, SessionNotFound

app = FastAPI(
    title="AI Disaster Response Commander",
    description="Classical-AI rescue planning: intelligent agent, state-space search, CSP and hierarchical planning.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions = SessionManager()


def _sim(sid: str):
    try:
        return sessions.get(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail=f"simulation '{sid}' not found (it may have expired)") from None


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "sessions": len(sessions)}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "algorithms": [{"id": a, "label": ALGORITHM_LABELS[a]} for a in ALGORITHMS],
        "heuristics": algorithm_lab.available_heuristics(),
        "profiles": [{"id": p.name, "label": p.label} for p in PROFILES.values()],
        "event_types": sorted(e.value for e in USER_EVENT_TYPES),
        "scenarios": list_scenarios(),
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    return list_scenarios()


# ----------------------------------------------------------- simulations
@app.post("/api/simulations")
def create_simulation(req: CreateSimulationRequest) -> dict:
    try:
        sid, sim = sessions.create(
            req.scenario, req.seed, req.algorithm, req.custom.model_dump() if req.custom else None
        )
    except (ValueError, StopIteration) as exc:
        raise _bad_request(exc) from exc
    return snapshot(sim, sid)


@app.post("/api/simulations/replay")
def replay_simulation(req: ReplayRequest) -> dict:
    """Recreate a lost simulation (server restart, or a request that reached a
    different serverless instance) by replaying the client's journal."""
    try:
        sid, sim = sessions.create(req.scenario, req.seed, req.algorithm, req.custom.model_dump() if req.custom else None)
    except (ValueError, StopIteration) as exc:
        raise _bad_request(exc) from exc
    with sessions.lock(sid):
        for entry in req.journal:
            kind = entry.get("kind")
            if kind == "steps":
                for _ in range(max(0, min(int(entry.get("n", 0)), 5000))):
                    sim.step()
            elif kind == "algorithm":
                try:
                    sim.set_algorithm(str(entry.get("algorithm", "")))
                except ValueError:
                    pass
            elif kind == "event":
                try:
                    etype = EventType(str(entry.get("type", "")).upper())
                    target = entry.get("target")
                    if etype in USER_EVENT_TYPES:
                        sim.inject(DisasterEvent(etype, tuple(target) if target else None, entry.get("params") or {}, source="USER"))
                except (ValueError, EventError):
                    pass  # the original request failed the same way
        return snapshot(sim, sid, 0)


@app.get("/api/simulations/{sid}")
def get_simulation(sid: str, since: int = Query(0, ge=0)) -> dict:
    sim = _sim(sid)
    with sessions.lock(sid):
        return snapshot(sim, sid, since)


@app.post("/api/simulations/{sid}/step")
def step_simulation(sid: str, req: StepRequest) -> dict:
    sim = _sim(sid)
    with sessions.lock(sid):
        for _ in range(req.steps):
            sim.step()
            if sim.status.value in ("COMPLETE", "STALLED"):
                break
        return snapshot(sim, sid, req.since)


@app.post("/api/simulations/{sid}/reset")
def reset_simulation(sid: str) -> dict:
    sim = _sim(sid)
    with sessions.lock(sid):
        sim.reset()
        return snapshot(sim, sid, 0)


@app.post("/api/simulations/{sid}/algorithm")
def set_algorithm(sid: str, req: AlgorithmRequest) -> dict:
    sim = _sim(sid)
    with sessions.lock(sid):
        try:
            sim.set_algorithm(req.algorithm)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return snapshot(sim, sid, req.since)


@app.post("/api/simulations/{sid}/events")
def trigger_event(sid: str, req: EventRequest) -> dict:
    sim = _sim(sid)
    try:
        etype = EventType(req.type.upper())
    except ValueError as exc:
        raise _bad_request(ValueError(f"unknown event type '{req.type}'")) from exc
    if etype not in USER_EVENT_TYPES:
        raise _bad_request(ValueError(f"event type {etype.value} cannot be triggered by the user"))
    event = DisasterEvent(etype, target=tuple(req.target) if req.target else None, params=req.params, source="USER")
    with sessions.lock(sid):
        try:
            report = sim.inject(event)
        except (EventError, ValueError) as exc:
            raise _bad_request(exc) from exc
        data = snapshot(sim, sid, req.since)
        data["report"] = report.to_dict()
        return data


@app.get("/api/simulations/{sid}/cells/{row}/{col}")
def get_cell(sid: str, row: int, col: int) -> dict:
    sim = _sim(sid)
    with sessions.lock(sid):
        try:
            return cell_info(sim, (row, col))
        except ValueError as exc:
            raise _bad_request(exc) from exc


@app.delete("/api/simulations/{sid}")
def delete_simulation(sid: str) -> dict:
    try:
        sessions.delete(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="simulation not found") from None
    return {"deleted": sid}


# ------------------------------------------------------------ algorithm lab
def _lab_grid(src: LabSource) -> Grid:
    if src.session_id:
        sim = _sim(src.session_id)
        with sessions.lock(src.session_id):
            return sim.agent.belief.copy()
    try:
        return build_scenario(src.scenario, seed=src.seed).world.grid
    except ValueError as exc:
        raise _bad_request(exc) from exc


@app.get("/api/lab/map")
def lab_map(scenario: str = "EARTHQUAKE", seed: int | None = None, session_id: str | None = None) -> dict:
    try:
        if session_id:
            sim = _sim(session_id)
            with sessions.lock(session_id):
                return algorithm_lab.lab_map(scenario, grid=sim.agent.belief.copy(), world=sim.world)
        return algorithm_lab.lab_map(scenario, seed=seed)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@app.post("/api/lab/compare")
def lab_compare(req: CompareRequest) -> dict:
    grid = _lab_grid(req)
    try:
        return algorithm_lab.compare(grid, tuple(req.start), tuple(req.goal), req.profile, req.danger_aware, req.heuristic)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@app.post("/api/lab/benchmark")
def lab_benchmark(req: BenchmarkRequest) -> dict:
    grid = _lab_grid(req)
    try:
        return algorithm_lab.benchmark(grid, req.trials, req.bench_seed, req.profile, req.danger_aware, req.heuristic)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@app.post("/api/lab/online")
def lab_online(req: OnlineRequest) -> dict:
    grid = _lab_grid(req)
    try:
        return algorithm_lab.online_comparison(grid, tuple(req.start), tuple(req.goal), req.profile, req.sensor_radius)
    except ValueError as exc:
        raise _bad_request(exc) from exc


# ------------------------------------------------------------- static UI
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        target = _DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(_DIST / "index.html")
