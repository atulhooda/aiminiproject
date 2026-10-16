"""Tests for the from-scratch linear regression and the ML risk step."""

from __future__ import annotations

import random

import pytest

from app.environment.simulator import Simulation
from app.ml import risk
from app.ml.features import FEATURES
from app.ml.model import LinearRegression


def test_linear_regression_recovers_a_known_function():
    rng = random.Random(0)
    xs = [[rng.uniform(0, 10), rng.uniform(-5, 5)] for _ in range(300)]
    ys = [3 * a - 2 * b + 7 for a, b in xs]
    model = LinearRegression(["a", "b"]).fit(xs, ys, ridge=0.0)
    assert model.predict([4.0, 1.0]) == pytest.approx(3 * 4 - 2 + 7, abs=1e-6)
    assert model.evaluate(xs, ys)["r2"] == pytest.approx(1.0)


def test_saved_model_beats_the_average_baseline(tmp_path):
    model = LinearRegression.load(risk.MODEL_PATH)
    assert model.features == FEATURES
    m = model.metrics
    assert m["test_mae"] < m["test_baseline_mae"]
    model.save(tmp_path / "copy.json")
    assert LinearRegression.load(tmp_path / "copy.json").weights == model.weights


def test_agent_adds_an_ml_risk_factor_to_waiting_victims():
    sim = Simulation("URBAN_FIRE")
    sim.step()
    waiting = [v for v in sim.agent.goals if v.ml_eta is not None]
    assert waiting
    for v in waiting:
        ml = [f for f in v.priority_breakdown if f["factor"] == "ML risk"]
        assert len(ml) == 1 and 0 <= ml[0]["points"] <= risk.MAX_POINTS
        assert sum(f["points"] for f in v.priority_breakdown) == pytest.approx(v.priority, abs=0.3)
