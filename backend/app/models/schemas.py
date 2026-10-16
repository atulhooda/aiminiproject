"""Request bodies for the REST API (responses are plain JSON dictionaries)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CustomScenarioConfig(BaseModel):
    rows: int = Field(25, ge=12, le=40)
    cols: int = Field(25, ge=12, le=40)
    seed: int = 42
    victims: int = Field(8, ge=1, le=25)
    critical_ratio: float = Field(0.3, ge=0, le=1)
    ambulances: int = Field(3, ge=1, le=8)
    teams: int = Field(3, ge=0, le=8)
    hospitals: int = Field(2, ge=1, le=4)
    obstacle_density: float = Field(0.06, ge=0, le=0.25)
    fire_seeds: int = Field(1, ge=0, le=6)
    fire_spread: bool = True
    hidden_hazards: int = Field(2, ge=0, le=10)
    flood: bool = False


class CreateSimulationRequest(BaseModel):
    scenario: str = "EARTHQUAKE"
    seed: int | None = None
    algorithm: str = "ASTAR"
    custom: CustomScenarioConfig | None = None


class StepRequest(BaseModel):
    steps: int = Field(1, ge=1, le=50)
    since: int = 0


class AlgorithmRequest(BaseModel):
    algorithm: str
    since: int = 0


class EventRequest(BaseModel):
    type: str
    target: list[int] | None = Field(None, min_length=2, max_length=2)
    params: dict[str, Any] = Field(default_factory=dict)
    since: int = 0


class LabSource(BaseModel):
    scenario: str = "EARTHQUAKE"
    seed: int | None = None
    session_id: str | None = None  # use the agent's current belief map of a live simulation


class CompareRequest(LabSource):
    start: list[int] = Field(..., min_length=2, max_length=2)
    goal: list[int] = Field(..., min_length=2, max_length=2)
    profile: str = "GROUND_VEHICLE"
    danger_aware: bool = True
    heuristic: str = "manhattan"


class BenchmarkRequest(LabSource):
    trials: int = Field(30, ge=1, le=200)
    bench_seed: int = 1
    profile: str = "GROUND_VEHICLE"
    danger_aware: bool = True
    heuristic: str = "manhattan"


class OnlineRequest(LabSource):
    start: list[int] = Field(..., min_length=2, max_length=2)
    goal: list[int] = Field(..., min_length=2, max_length=2)
    profile: str = "GROUND_VEHICLE"
    sensor_radius: int = Field(1, ge=0, le=5)
