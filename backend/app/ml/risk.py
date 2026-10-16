"""ML risk assessment used by the agent when it ranks victims.

The trained model predicts how many ticks a waiting victim will wait for
rescue. From that we project the victim's health at rescue; if it falls
below RISK_HEALTH, the victim earns extra priority points.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.environment.grid import Grid
from app.environment.world import World
from app.ml.features import victim_features
from app.ml.model import LinearRegression
from app.models.entities import SEVERITY_DECAY, Victim

MODEL_PATH = Path(__file__).with_name("rescue_time_model.json")
RISK_HEALTH = 30.0  # projected health (%) below which a victim counts as at risk
MAX_POINTS = 10.0
DANGER_DECAY_FACTOR = 1.5  # same as the simulator's deterioration model

ENABLED = True  # switched off while generating training data
_model: LinearRegression | None = None
_loaded = False


def get_model() -> LinearRegression | None:
    global _model, _loaded
    if not ENABLED:
        return None
    if not _loaded:
        _loaded = True
        _model = LinearRegression.load(MODEL_PATH) if MODEL_PATH.exists() else None
    return _model


@dataclass
class RiskAssessment:
    eta: float  # predicted ticks until rescue
    health_at_rescue: float  # projected health (%) when help arrives
    points: float  # priority points added

    def detail(self) -> str:
        return f"model predicts help in ~{self.eta:.0f} ticks, health then ~{self.health_at_rescue:.0f}%"


def assess(v: Victim, world: World, grid: Grid, queue_position: int, free_ambulances: int) -> RiskAssessment | None:
    model = get_model()
    if model is None:
        return None
    eta = max(0.0, model.predict(victim_features(v, world, grid, queue_position, free_ambulances)))
    loss_per_tick = SEVERITY_DECAY[v.severity] * (1 + DANGER_DECAY_FACTOR * grid.danger_at(v.pos))
    health = max(0.0, v.health - loss_per_tick * eta)
    points = max(0.0, min(MAX_POINTS, (RISK_HEALTH - health) / 3))
    return RiskAssessment(eta, health, points)


def model_info() -> dict | None:
    model = get_model()
    if model is None:
        return None
    return {"type": "Linear regression (from scratch)", "predicts": "ticks until rescue", **model.metrics}
