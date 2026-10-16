"""Linear regression implemented from scratch (no ML library).

prediction = bias + sum(weight_i * standardized_feature_i)

Fitted with the normal equations plus a small ridge term:
    w = (X^T X + lambda * I)^-1 X^T y
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve a x = b by Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col] or 1e-12
        for r in range(n):
            if r != col:
                f = m[r][col] / div
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / (m[i][i] or 1e-12) for i in range(n)]


@dataclass
class LinearRegression:
    features: list[str]
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    mean: list[float] = field(default_factory=list)
    std: list[float] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def _scale(self, x: list[float]) -> list[float]:
        return [(v - m) / s for v, m, s in zip(x, self.mean, self.std)]

    def fit(self, xs: list[list[float]], ys: list[float], ridge: float = 1e-2) -> "LinearRegression":
        n, k = len(xs), len(xs[0])
        self.mean = [sum(r[j] for r in xs) / n for j in range(k)]
        self.std = [math.sqrt(sum((r[j] - self.mean[j]) ** 2 for r in xs) / n) or 1.0 for j in range(k)]
        z = [self._scale(r) for r in xs]
        y_mean = sum(ys) / n
        xtx = [[sum(r[i] * r[j] for r in z) + (ridge * n if i == j else 0.0) for j in range(k)] for i in range(k)]
        xty = [sum(r[i] * (y - y_mean) for r, y in zip(z, ys)) for i in range(k)]
        self.weights = _solve(xtx, xty)
        self.bias = y_mean
        return self

    def predict(self, x: list[float]) -> float:
        return self.bias + sum(w * v for w, v in zip(self.weights, self._scale(x)))

    def evaluate(self, xs: list[list[float]], ys: list[float]) -> dict:
        preds = [self.predict(x) for x in xs]
        y_mean = sum(ys) / len(ys)
        mae = sum(abs(p - y) for p, y in zip(preds, ys)) / len(ys)
        ss_res = sum((p - y) ** 2 for p, y in zip(preds, ys))
        ss_tot = sum((y - y_mean) ** 2 for y in ys) or 1.0
        baseline = sum(abs(y_mean - y) for y in ys) / len(ys)
        return {"mae": round(mae, 2), "r2": round(1 - ss_res / ss_tot, 3), "baseline_mae": round(baseline, 2), "samples": len(ys)}

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def load(cls, path: Path) -> "LinearRegression":
        return cls(**json.loads(path.read_text()))
