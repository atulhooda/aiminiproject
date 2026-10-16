"""Rational victim prioritisation with an explanation of every factor.

priority = severity + health deficit + survival-window urgency
           + hazard exposure + waiting time + entrapment

Each factor is returned separately so the UI can show *why* a victim was
ranked where it is.
"""

from __future__ import annotations

from app.environment.grid import Grid
from app.models.entities import SEVERITY_DECAY, Severity, Victim

SEVERITY_POINTS = {
    Severity.CRITICAL: 45.0,
    Severity.HIGH: 32.0,
    Severity.MEDIUM: 20.0,
    Severity.LOW: 8.0,
}
HEALTH_WEIGHT = 0.2  # up to 20 points
URGENCY_MAX = 15.0
URGENCY_HORIZON = 200.0  # ticks: survival windows longer than this add no urgency
HAZARD_MAX = 12.0
WAIT_RATE = 0.1
WAIT_MAX = 8.0
TRAPPED_POINTS = 4.0
DANGER_DECAY_FACTOR = 1.5  # must match the simulator's deterioration model


def survival_window(victim: Victim, danger: float) -> float:
    """Estimated ticks before the victim's health reaches zero if untreated."""
    rate = SEVERITY_DECAY[victim.severity] * (1 + DANGER_DECAY_FACTOR * danger)
    return victim.health / rate if rate > 0 else float("inf")


def compute_priority(victim: Victim, grid: Grid, tick: int) -> tuple[float, list[dict]]:
    danger = grid.danger_at(victim.pos)
    window = survival_window(victim, danger)
    waited = max(0, tick - victim.reported_tick)

    factors = [
        ("Severity", SEVERITY_POINTS[victim.severity], victim.severity.value),
        ("Health deficit", (100.0 - victim.health) * HEALTH_WEIGHT, f"{victim.health:.0f}% health remaining"),
        (
            "Survival window",
            max(0.0, min(URGENCY_MAX, URGENCY_MAX * (1 - window / URGENCY_HORIZON))),
            f"~{window:.0f} ticks before fatal without treatment",
        ),
        ("Hazard exposure", HAZARD_MAX * danger, f"danger level {danger:.2f} at {victim.pos}"),
        ("Waiting time", min(WAIT_MAX, waited * WAIT_RATE), f"waiting {waited} ticks"),
        (
            "Entrapment",
            TRAPPED_POINTS if victim.trapped and not victim.extracted else 0.0,
            "trapped - needs extraction" if victim.trapped and not victim.extracted else "not trapped",
        ),
    ]
    breakdown = [{"factor": name, "points": round(points, 1), "detail": detail} for name, points, detail in factors]
    total = round(sum(points for _n, points, _d in factors), 1)
    return total, breakdown
