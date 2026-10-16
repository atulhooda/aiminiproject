"""Tests for the CSP framework (node consistency, AC-3, forward checking,
backtracking, branch-and-bound) and the rescue resource-allocation model."""

from __future__ import annotations

import itertools
import random

import pytest

from helpers import build_world, prepare_victims, small_city
from app.csp.allocation import (
    DEFER,
    METHOD_EVACUATE,
    METHOD_EXTRACT,
    build_allocation_problem,
)
from app.csp.constraints import BinaryConstraint, CapacityConstraint, UnaryConstraint, not_equal
from app.csp.solver import CSP, BacktrackingSolver
from app.models.entities import CellType, MedicalLevel, Severity, TeamCapability

# ---------------------------------------------------------------- generic CSP
AUSTRALIA = [("WA", "NT"), ("WA", "SA"), ("NT", "SA"), ("NT", "Q"), ("SA", "Q"), ("SA", "NSW"), ("SA", "V"), ("Q", "NSW"), ("NSW", "V")]
REGIONS = ["WA", "NT", "SA", "Q", "NSW", "V", "T"]


def map_colouring(colours: list[str]) -> CSP:
    return CSP(REGIONS, {r: list(colours) for r in REGIONS}, [not_equal(a, b) for a, b in AUSTRALIA])


def n_queens(n: int) -> CSP:
    cols = [f"Q{i}" for i in range(n)]
    cons = []
    for (i, a), (j, b) in itertools.combinations(enumerate(cols), 2):
        cons.append(BinaryConstraint(f"{a}-{b}", a, b, lambda x, y, d=j - i: x != y and abs(x - y) != d))
    return CSP(cols, {c: list(range(n)) for c in cols}, cons)


def test_map_colouring_is_solved_consistently():
    sol = BacktrackingSolver(map_colouring(["red", "green", "blue"])).solve()
    assert sol.satisfiable and sol.optimal
    for a, b in AUSTRALIA:
        assert sol.assignment[a] != sol.assignment[b]
    assert set(sol.assignment) == set(REGIONS)


def test_two_colours_are_proved_unsatisfiable():
    sol = BacktrackingSolver(map_colouring(["red", "green"])).solve()
    assert not sol.satisfiable
    assert sol.assignment is None
    assert sol.failure_reason


def test_node_consistency_prunes_unary_constraints():
    csp = CSP(["X"], {"X": [1, 2, 3]}, [UnaryConstraint("not-two", "X", lambda v: v != 2)])
    solver = BacktrackingSolver(csp)
    assert solver.enforce_node_consistency() is None
    assert solver.domains["X"] == [1, 3]
    assert solver.removal_counts["NODE"] == {"not-two": 1}


def test_ac3_enforces_arc_consistency():
    csp = CSP(["X", "Y"], {"X": [1, 2, 3], "Y": [1, 2, 3]}, [BinaryConstraint("X<Y", "X", "Y", lambda x, y: x < y)])
    solver = BacktrackingSolver(csp)
    assert solver.ac3() is None
    assert solver.domains == {"X": [1, 2], "Y": [2, 3]}
    assert solver.stats.ac3_removals == 2


def test_ac3_detects_inconsistency_without_search():
    # X and Y must differ but both only have the value 1.
    csp = CSP(["X", "Y"], {"X": [1], "Y": [1]}, [not_equal("X", "Y")])
    sol = BacktrackingSolver(csp).solve()
    assert not sol.satisfiable
    assert "AC-3" in sol.failure_reason
    assert sol.stats.nodes == 0


def test_forward_checking_and_mrv_reduce_search_on_n_queens():
    plain = BacktrackingSolver(n_queens(8), forward_checking=False, mrv=False, use_ac3=False).solve()
    smart = BacktrackingSolver(n_queens(8)).solve()
    for sol in (plain, smart):
        assert sol.satisfiable
        q = sol.assignment
        for (i, a), (j, b) in itertools.combinations(enumerate(sorted(q, key=lambda k: int(k[1:]))), 2):
            assert q[a] != q[b] and abs(q[a] - q[b]) != j - i
    assert smart.stats.nodes < plain.stats.nodes
    assert smart.stats.fc_prunings > 0


def test_capacity_constraint_is_respected_and_infeasibility_proved():
    vars_ = ["a", "b", "c"]
    cap_a = CapacityConstraint("cap-A", vars_, 1, lambda v, x: int(x == "A"))
    cap_b = CapacityConstraint("cap-B", vars_, 1, lambda v, x: int(x == "B"))
    sol = BacktrackingSolver(CSP(vars_, {v: ["A", "B", "C"] for v in vars_}, [cap_a, cap_b])).solve()
    assert sol.satisfiable
    values = list(sol.assignment.values())
    assert values.count("A") <= 1 and values.count("B") <= 1
    # Three variables, two single-capacity values and nothing else: impossible.
    unsat = BacktrackingSolver(CSP(vars_, {v: ["A", "B"] for v in vars_}, [cap_a, cap_b])).solve()
    assert not unsat.satisfiable


def test_branch_and_bound_matches_brute_force_optimum():
    rng = random.Random(5)
    for _ in range(25):
        vars_ = ["v0", "v1", "v2", "v3"]
        domains = {v: [0, 1, 2] for v in vars_}
        cons = [not_equal(a, b) for a, b in itertools.combinations(vars_, 2) if rng.random() < 0.5]
        cons.append(CapacityConstraint("cap-2", vars_, 1, lambda v, x: int(x == 2)))
        util = {(v, x): rng.uniform(0, 10) for v in vars_ for x in [0, 1, 2]}
        csp = CSP(vars_, domains, cons)
        sol = BacktrackingSolver(csp, utility=lambda v, x: util[(v, x)]).solve()
        best = None
        for combo in itertools.product([0, 1, 2], repeat=4):
            a = dict(zip(vars_, combo))
            if all(c.is_consistent(a) for c in cons):
                score = sum(util[(v, a[v])] for v in vars_)
                best = score if best is None else max(best, score)
        assert sol.satisfiable == (best is not None)
        if best is not None:
            assert sol.optimal
            assert sol.score == pytest.approx(best)


# ------------------------------------------------------- resource allocation
def allocate(world, require_critical: bool = True, idle: set[str] | None = None):
    victims, needs, oracle = prepare_victims(world)
    problem = build_allocation_problem(
        victims=victims,
        needs=needs,
        ambulances=list(world.ambulances.values()),
        teams=list(world.teams.values()),
        hospitals=list(world.hospitals.values()),
        safe_zones=list(world.safe_zones.values()),
        idle_units=idle if idle is not None else {u for u, x in world.units().items() if x.available},
        er_free={h.id: h.er_free for h in world.hospitals.values()},
        icu_free={h.id: h.icu_free for h in world.hospitals.values()},
        oracle=oracle,
        require_critical=require_critical,
    )
    sol = BacktrackingSolver(problem.csp, utility=problem.utility, var_order_hint=problem.var_order).solve()
    return problem, sol


def base_city():
    b = small_city()
    b.hospital("H1", "General", (1, 3), er=4, icu=1)
    b.hospital("H2", "Clinic", (11, 11), er=4, icu=1)
    b.safe_zone("S1", "Park", [(8, 8)], entry=(8, 8))
    return b


def test_critical_victim_requires_als_ambulance_and_icu():
    b = base_city()
    b.ambulance("A1", (2, 4), MedicalLevel.BLS)  # right next to the victim
    b.ambulance("A2", (12, 12), MedicalLevel.ALS)  # far away
    b.victim("V01", (2, 5), Severity.CRITICAL, 40, 2)
    world = build_world(b)
    world.hospitals["H1"].icu_capacity = 0  # no ICU bed at the nearest hospital
    problem, sol = allocate(world)
    opt = sol.assignment["V01"]
    assert opt.ambulance == "A2"
    assert opt.destination == "H2"
    assert sol.removal_counts["NODE"].get("medical-capability", 0) > 0
    assert sol.removal_counts["NODE"].get("icu-capacity", 0) > 0


def test_unavailable_resources_are_never_assigned():
    b = base_city()
    b.ambulance("A1", (2, 4), MedicalLevel.ALS)
    b.ambulance("A2", (12, 12), MedicalLevel.ALS)
    b.victim("V01", (2, 6), Severity.HIGH, 55, 2)
    world = build_world(b)
    world.ambulances["A1"].available = False
    _problem, sol = allocate(world)
    assert sol.assignment["V01"].ambulance == "A2"


def test_one_team_cannot_do_two_tasks_and_trapped_victims_need_extraction():
    b = base_city()
    b.ambulance("A1", (2, 2), MedicalLevel.ALS)
    b.ambulance("A2", (12, 2), MedicalLevel.ALS)
    b.team("T1", (7, 7), TeamCapability.URBAN_SAR)
    b.victim("V01", (2, 9), Severity.HIGH, 55, 3, trapped=True)
    b.victim("V02", (12, 9), Severity.HIGH, 56, 3, trapped=True)
    world = build_world(b)
    _problem, sol = allocate(world)
    served = [v for v, o in sol.assignment.items() if o is not DEFER]
    assert len(served) == 1  # only one extraction team exists
    assert sol.assignment[served[0]].method == METHOD_EXTRACT
    assert sol.assignment[served[0]].team == "T1"


def test_fire_zone_victim_requires_firefighting_team():
    b = base_city()
    b.set((3, 9), CellType.FIRE)  # next to the victim at (2, 9)
    b.ambulance("A1", (2, 2), MedicalLevel.ALS)
    b.team("T1", (2, 8), TeamCapability.URBAN_SAR)  # closest, wrong capability
    b.team("T2", (12, 12), TeamCapability.FIREFIGHTING)
    b.victim("V01", (2, 9), Severity.HIGH, 55, 2)
    world = build_world(b)
    _problem, sol = allocate(world)
    assert sol.assignment["V01"].team == "T2"
    assert sol.removal_counts["NODE"].get("hazard-capability", 0) > 0


def test_multi_seat_ambulance_capacity_and_dedicated_critical_transport():
    b = base_city()
    b.ambulance("A1", (7, 7), MedicalLevel.ALS, capacity=2)
    b.victim("V01", (7, 4), Severity.MEDIUM, 70, 2)
    b.victim("V02", (7, 10), Severity.MEDIUM, 72, 2)
    b.victim("V03", (4, 7), Severity.MEDIUM, 71, 2)
    world = build_world(b)
    _problem, sol = allocate(world)
    riders = [v for v, o in sol.assignment.items() if o is not DEFER and o.ambulance == "A1"]
    assert len(riders) == 2  # capacity 2 respected
    assert len({sol.assignment[v].destination for v in riders}) == 1  # same trip, same hospital

    b2 = base_city()
    b2.ambulance("A1", (7, 7), MedicalLevel.ALS, capacity=2)
    b2.victim("V01", (7, 4), Severity.CRITICAL, 40, 2)
    b2.victim("V02", (7, 10), Severity.MEDIUM, 72, 2)
    _problem, sol2 = allocate(build_world(b2))
    assert sol2.assignment["V01"].ambulance == "A1"
    assert sol2.assignment["V02"] is DEFER  # a critical patient rides alone


def test_critical_coverage_is_relaxed_when_unsatisfiable():
    b = base_city()
    b.ambulance("A1", (7, 7), MedicalLevel.ALS)
    b.ambulance("A2", (7, 8), MedicalLevel.BLS)
    b.victim("V01", (7, 4), Severity.CRITICAL, 40, 2)
    b.victim("V02", (7, 10), Severity.CRITICAL, 42, 2)
    world = build_world(b)
    world.hospitals["H1"].icu_capacity = 1
    world.hospitals["H2"].icu_capacity = 1
    problem, hard = allocate(world, require_critical=True)
    assert set(problem.coverage_vars) == {"V01", "V02"}
    assert not hard.satisfiable  # one ALS ambulance cannot serve two critical victims
    _problem, relaxed = allocate(world, require_critical=False)
    assert relaxed.satisfiable
    served = [v for v, o in relaxed.assignment.items() if o is not DEFER]
    assert len(served) == 1 and relaxed.assignment[served[0]].ambulance == "A1"


def test_low_severity_victims_are_escorted_to_a_safe_zone():
    b = base_city()
    b.ambulance("A1", (2, 2), MedicalLevel.ALS)
    b.team("T1", (7, 7), TeamCapability.URBAN_SAR)
    b.victim("V01", (7, 9), Severity.LOW, 90, 1)
    _problem, sol = allocate(build_world(b))
    opt = sol.assignment["V01"]
    assert opt.method == METHOD_EVACUATE and opt.team == "T1" and opt.destination == "S1"


def test_hospital_capacity_limits_assignments():
    b = base_city()
    for i, pos in enumerate([(2, 4), (2, 8), (7, 4)]):
        b.ambulance(f"A{i + 1}", pos, MedicalLevel.ALS)
    b.victim("V01", (2, 5), Severity.HIGH, 55, 2)
    b.victim("V02", (2, 9), Severity.HIGH, 56, 2)
    b.victim("V03", (7, 5), Severity.HIGH, 57, 2)
    world = build_world(b)
    world.hospitals["H1"].er_capacity = 1
    world.hospitals["H2"].er_capacity = 1
    _problem, sol = allocate(world)
    dests = [o.destination for o in sol.assignment.values() if o is not DEFER]
    assert len(dests) == 2 and sorted(dests) == ["H1", "H2"]


def test_capacity_aware_bound_is_admissible():
    """The domain-specific branch-and-bound bound must never cut off the optimum."""
    b = base_city()
    b.ambulance("A1", (2, 4), MedicalLevel.ALS)
    b.ambulance("A2", (12, 4), MedicalLevel.BLS, capacity=2)
    b.team("T1", (7, 7), TeamCapability.URBAN_SAR)
    b.victim("V01", (2, 9), Severity.CRITICAL, 40, 2, trapped=True)
    b.victim("V02", (7, 10), Severity.HIGH, 55, 2)
    b.victim("V03", (12, 9), Severity.MEDIUM, 70, 2)
    b.victim("V04", (4, 7), Severity.MEDIUM, 72, 2)
    b.victim("V05", (7, 4), Severity.LOW, 90, 1)
    world = build_world(b)
    victims, needs, oracle = prepare_victims(world)
    problem = build_allocation_problem(
        victims=victims, needs=needs, ambulances=list(world.ambulances.values()), teams=list(world.teams.values()),
        hospitals=list(world.hospitals.values()), safe_zones=list(world.safe_zones.values()),
        idle_units=set(world.units()), er_free={h: x.er_free for h, x in world.hospitals.items()},
        icu_free={h: x.icu_free for h, x in world.hospitals.items()}, oracle=oracle, require_critical=False,
    )
    plain = BacktrackingSolver(problem.csp, utility=problem.utility, node_limit=200000).solve()
    bounded = BacktrackingSolver(problem.csp, utility=problem.utility, node_limit=200000, bound=problem.bound).solve()
    assert plain.optimal and bounded.optimal
    assert bounded.score == pytest.approx(plain.score)
    assert bounded.stats.nodes <= plain.stats.nodes


def test_extract_only_is_a_fallback_never_a_substitute_for_full_service():
    from app.csp.allocation import METHOD_EXTRACT_ONLY

    def world(als_available: bool):
        b = base_city()
        b.ambulance("A1", (7, 2), MedicalLevel.ALS)
        b.team("T1", (7, 7), TeamCapability.URBAN_SAR)
        b.victim("V01", (7, 9), Severity.CRITICAL, 40, 3, trapped=True)
        w = build_world(b)
        w.ambulances["A1"].available = als_available
        return w

    # No ALS ambulance: the team still frees the trapped critical victim now.
    _p, sol = allocate(world(als_available=False))
    assert sol.assignment["V01"].method == METHOD_EXTRACT_ONLY
    assert sol.assignment["V01"].team == "T1"
    # ALS ambulance available: critical coverage demands a complete plan.
    problem, sol = allocate(world(als_available=True))
    assert "V01" in problem.coverage_vars
    assert sol.assignment["V01"].method == METHOD_EXTRACT
    assert sol.assignment["V01"].ambulance == "A1"


def test_minimal_relaxation_keeps_coverage_for_the_highest_priority_critical_victim():
    b = base_city()
    b.ambulance("A1", (7, 7), MedicalLevel.ALS)
    b.victim("V01", (7, 4), Severity.CRITICAL, 30, 2)  # sicker -> higher priority
    b.victim("V02", (7, 10), Severity.CRITICAL, 46, 2)
    world = build_world(b)
    victims, needs, oracle = prepare_victims(world)
    assert [v.id for v in victims] == ["V01", "V02"]
    args = dict(
        victims=victims, needs=needs, ambulances=list(world.ambulances.values()), teams=[],
        hospitals=list(world.hospitals.values()), safe_zones=list(world.safe_zones.values()),
        idle_units={"A1"}, er_free={h: x.er_free for h, x in world.hospitals.items()},
        icu_free={h: x.icu_free for h, x in world.hospitals.items()}, oracle=oracle,
    )
    full = build_allocation_problem(**args, require_critical=True)
    assert not BacktrackingSolver(full.csp, utility=full.utility).solve().satisfiable
    relaxed = build_allocation_problem(**args, require_critical=True, coverage=["V01"])
    assert relaxed.coverage_vars == ["V01"]
    sol = BacktrackingSolver(relaxed.csp, utility=relaxed.utility).solve()
    assert sol.satisfiable and sol.assignment["V01"].ambulance == "A1" and sol.assignment["V02"] is DEFER
