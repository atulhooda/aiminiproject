"""Features describing one waiting victim at one moment.

The same function feeds training (from simulated runs) and live prediction,
so the model always sees exactly the inputs it was trained on.
"""

from __future__ import annotations

from app.environment.grid import Grid
from app.environment.world import World
from app.models.entities import SEVERITY_RANK, Victim

FEATURES = [
    "severity",  # 1 = low ... 4 = critical
    "health",  # 0..100
    "danger",  # 0..1 at the victim's cell
    "trapped",  # 1 if still needs freeing
    "assigned",  # 1 if units are already on the way
    "queue_position",  # victims ahead of it in priority order
    "free_ambulances",  # ambulances with nothing to do right now
    "ambulance_distance",  # Manhattan distance to the nearest working ambulance
    "hospital_distance",  # Manhattan distance to the nearest hospital
]


def _manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def victim_features(v: Victim, world: World, grid: Grid, queue_position: int, free_ambulances: int) -> list[float]:
    ambulances = [a.pos for a in world.ambulances.values() if a.available]
    hospitals = [h.pos for h in world.hospitals.values()]
    return [
        float(SEVERITY_RANK[v.severity]),
        v.health,
        grid.danger_at(v.pos),
        1.0 if v.trapped and not v.extracted else 0.0,
        0.0 if v.status.value == "WAITING" else 1.0,
        float(queue_position),
        float(free_ambulances),
        float(min((_manhattan(p, v.pos) for p in ambulances), default=50)),
        float(min((_manhattan(p, v.pos) for p in hospitals), default=50)),
    ]
