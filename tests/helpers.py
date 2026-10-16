"""Shared helpers for the test-suite."""

from __future__ import annotations

from app.agents.priority import compute_priority
from app.csp.allocation import RouteOracle, assess_needs
from app.environment.scenarios import ScenarioBuilder, ScenarioInfo
from app.environment.world import World
from app.models.entities import Pos


def is_valid_path(path: list[Pos], grid, profile) -> bool:
    """Contiguous 4-connected path whose every step is passable for the profile."""
    for a, b in zip(path, path[1:]):
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            return False
        if not profile.passable(grid.type_at(b)):
            return False
    return True


def small_city(seed: int = 3) -> ScenarioBuilder:
    """13x13 city with avenues on rows/cols 2, 7, 12 and no random alleys."""
    b = ScenarioBuilder(13, 13, seed)
    b.avenues(rows=(2, 7, 12), cols=(2, 7, 12))
    return b


def build_world(b: ScenarioBuilder) -> World:
    return b.build(ScenarioInfo("TEST", "Test", "unit-test world", [])).world


def prepare_victims(world: World, ids: list[str] | None = None):
    """Compute priorities and needs exactly as the agent would."""
    oracle = RouteOracle(world.grid, "ASTAR")
    anchors = [h.pos for h in world.hospitals.values()] + list(world.bases)
    victims = [world.victims[i] for i in (ids or sorted(world.victims))]
    needs = {}
    for v in victims:
        v.priority, v.priority_breakdown = compute_priority(v, world.grid, world.tick)
        needs[v.id] = assess_needs(v, world.grid, oracle, anchors)
    victims.sort(key=lambda v: -v.priority)
    return victims, needs, oracle
