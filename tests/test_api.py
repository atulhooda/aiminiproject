"""End-to-end tests of the REST API."""

from __future__ import annotations

import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_meta_lists_algorithms_and_scenarios(client):
    data = client.get("/api/meta").json()
    assert [a["id"] for a in data["algorithms"]] == ["BFS", "GREEDY", "ASTAR"]
    assert {s["id"] for s in data["scenarios"]} == {"EARTHQUAKE", "URBAN_FIRE", "FLOOD", "DEMO", "CUSTOM"}
    assert "BLOCK_ROAD" in data["event_types"]


def test_simulation_lifecycle_and_event_reaction(client):
    snap = client.post("/api/simulations", json={"scenario": "EARTHQUAKE"}).json()
    sid = snap["session_id"]
    assert snap["tick"] == 0 and snap["status"] == "READY"
    assert snap["grid"]["rows"] == 25 and len(snap["grid"]["cells"]) == 25

    seq = snap["log_seq"]
    for _ in range(6):
        snap = client.post(f"/api/simulations/{sid}/step", json={"since": seq}).json()
        assert all(e["seq"] > seq for e in snap["log"])
        seq = snap["log_seq"]
    assert snap["tick"] == 6
    assert snap["last_csp"]["result"] == "SATISFIED"
    assert snap["last_search"]["explored"]
    assert any(p["legs"] for p in snap["plans"])

    resp = client.post(f"/api/simulations/{sid}/events", json={"type": "BLOCK_ROAD", "since": seq})
    assert resp.status_code == 200
    data = resp.json()
    assert data["report"]["event_type"] == "BLOCK_ROAD"
    assert any(a["title"] == "ENVIRONMENT CHANGE DETECTED" for a in data["alerts"])
    assert data["replan_events"]

    bad = client.post(f"/api/simulations/{sid}/events", json={"type": "BLOCK_ROAD", "target": [0, 0]})
    assert bad.status_code == 400
    assert client.post(f"/api/simulations/{sid}/events", json={"type": "FIRE_SPREAD"}).status_code == 400

    cell = client.get(f"/api/simulations/{sid}/cells/2/2").json()
    assert {"type", "danger", "traversal_cost", "accessible", "profiles"} <= set(cell)

    assert client.post(f"/api/simulations/{sid}/algorithm", json={"algorithm": "GREEDY"}).json()["algorithm"] == "GREEDY"
    assert client.post(f"/api/simulations/{sid}/algorithm", json={"algorithm": "DFS"}).status_code == 400
    assert client.post(f"/api/simulations/{sid}/reset").json()["tick"] == 0
    assert client.delete(f"/api/simulations/{sid}").status_code == 200
    assert client.get(f"/api/simulations/{sid}").status_code == 404


def test_custom_scenario_validation(client):
    ok = client.post("/api/simulations", json={"scenario": "CUSTOM", "custom": {"rows": 18, "cols": 22, "victims": 5}})
    assert ok.status_code == 200 and ok.json()["grid"]["cols"] == 22
    bad = client.post("/api/simulations", json={"scenario": "CUSTOM", "custom": {"rows": 5}})
    assert bad.status_code == 422


def test_algorithm_lab_endpoints(client):
    m = client.get("/api/lab/map", params={"scenario": "URBAN_FIRE"}).json()
    body = {"scenario": "URBAN_FIRE", "start": m["suggested_start"], "goal": m["suggested_goal"]}
    cmp = client.post("/api/lab/compare", json=body).json()
    by = {r["algorithm"]: r for r in cmp["results"]}
    assert by["ASTAR"]["optimal"] is True
    assert by["ASTAR"]["cost"] == pytest.approx(cmp["optimal_cost"])
    assert by["BFS"]["nodes_expanded"] >= by["ASTAR"]["nodes_expanded"]
    assert all(r["explored"] and r["path"] for r in cmp["results"])

    bench = client.post("/api/lab/benchmark", json={"scenario": "URBAN_FIRE", "trials": 10}).json()
    astar_row = next(r for r in bench["summary"] if r["algorithm"] == "ASTAR")
    assert bench["trials"] == 10 and astar_row["optimal_rate"] == 1.0

    online = client.post("/api/lab/online", json={**body, "sensor_radius": 1}).json()
    assert online["repeated_astar"]["found"] and online["lrta_star"]["found"]
    assert online["repeated_astar"]["cost"] >= online["offline"]["cost"] - 1e-9

    bad = client.post("/api/lab/compare", json={**body, "goal": [0, 0]})
    assert bad.status_code == 400


def test_replay_rebuilds_an_identical_simulation(client):
    snap = client.post("/api/simulations", json={"scenario": "URBAN_FIRE"}).json()
    sid = snap["session_id"]
    journal = []
    for _ in range(12):
        snap = client.post(f"/api/simulations/{sid}/step", json={}).json()
    journal.append({"kind": "steps", "n": 12})
    snap = client.post(f"/api/simulations/{sid}/events", json={"type": "BLOCK_ROAD"}).json()
    journal.append({"kind": "event", "type": "BLOCK_ROAD", "target": None, "params": {}})
    for _ in range(8):
        snap = client.post(f"/api/simulations/{sid}/step", json={}).json()
    journal.append({"kind": "steps", "n": 8})

    rebuilt = client.post("/api/simulations/replay", json={"scenario": "URBAN_FIRE", "journal": journal}).json()
    assert rebuilt["session_id"] != sid
    for key in ("tick", "grid", "victims", "ambulances", "teams", "hospitals"):
        assert rebuilt[key] == snap[key], key
