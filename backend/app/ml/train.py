"""Train the rescue-time model on simulated disasters.

    cd backend && ../.venv/bin/python -m app.ml.train

Each sample is one waiting victim at one tick; the label is how many ticks
later that victim was actually rescued. Simulations are split 80/20 so the
test score comes from runs the model never saw.
"""

from __future__ import annotations

import random

from app.ml import risk
from app.ml.features import FEATURES, victim_features
from app.ml.model import LinearRegression
from app.environment.simulator import Simulation
from app.models.entities import VictimStatus

SAMPLE_EVERY = 3
MAX_TICKS = 400


def scenario_configs(seed: int = 7) -> list[tuple[str, int | None, dict | None]]:
    rng = random.Random(seed)
    runs: list[tuple[str, int | None, dict | None]] = []
    for s in range(1, 21):
        for sid in ("URBAN_FIRE", "EARTHQUAKE", "FLOOD"):
            runs.append((sid, s, None))
    for s in range(1, 121):
        runs.append(("CUSTOM", None, {
            "seed": s,
            "victims": rng.randint(5, 14),
            "ambulances": rng.randint(2, 5),
            "teams": rng.randint(1, 4),
            "hospitals": rng.randint(1, 3),
            "fire_seeds": rng.randint(0, 3),
            "obstacle_density": round(rng.uniform(0.03, 0.12), 2),
            "hidden_hazards": rng.randint(0, 3),
        }))
    return runs


def collect(scenario: str, seed: int | None, custom: dict | None) -> list[tuple[list[float], int]]:
    """Run one simulation; return (features, ticks until that victim was rescued) samples."""
    sim = Simulation(scenario, seed=seed, custom=custom)
    samples: list[tuple[list[float], str, int]] = []
    while sim.status.value not in ("COMPLETE", "STALLED") and sim.tick < MAX_TICKS:
        sim.step()
        if sim.tick % SAMPLE_EVERY:
            continue
        agent, world = sim.agent, sim.world
        waiting = [v for v in agent.goals if v.status in (VictimStatus.WAITING, VictimStatus.ASSIGNED)]
        free = sum(1 for a in world.ambulances if world.ambulances[a].available and agent._is_idle(a))
        for pos, v in enumerate(waiting):
            samples.append((victim_features(v, world, agent.belief, pos, free), v.id, sim.tick))
    rescued = {vid: v.rescued_tick for vid, v in sim.world.victims.items() if v.status == VictimStatus.RESCUED}
    return [(x, rescued[vid] - t) for x, vid, t in samples if vid in rescued]


def main() -> None:
    risk.ENABLED = False  # the data must come from the agent without the model
    runs = scenario_configs()
    random.Random(1).shuffle(runs)
    split = int(len(runs) * 0.8)
    data: dict[str, tuple[list[list[float]], list[float]]] = {"train": ([], []), "test": ([], [])}
    for i, (sid, seed, custom) in enumerate(runs):
        part = "train" if i < split else "test"
        try:
            rows = collect(sid, seed, custom)
        except (ValueError, StopIteration):
            continue  # an impossible custom layout
        for x, label in rows:
            data[part][0].append(x)
            data[part][1].append(float(label))
    model = LinearRegression(FEATURES).fit(*data["train"])
    model.metrics = {
        "trained_on": len(data["train"][1]),
        "simulations": len(runs),
        **{f"test_{k}": v for k, v in model.evaluate(*data["test"]).items()},
    }
    model.save(risk.MODEL_PATH)
    print("saved", risk.MODEL_PATH)
    print("metrics", model.metrics)
    for name, w in sorted(zip(FEATURES, model.weights), key=lambda p: -abs(p[1])):
        print(f"  {name:20s} {w:+.2f}")


if __name__ == "__main__":
    main()
