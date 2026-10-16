"""Rescue resource allocation modelled as a constraint satisfaction problem.

Variables : one per victim in the agent's attention window (highest priority first)
Domains   : every combination of rescue *method*, resources and destination,
            plus DEFER (not served in this round):
              AMBULANCE_DIRECT       (ambulance, hospital)
              EXTRACT_AND_TRANSPORT  (rescue team, ambulance, hospital)
              EXTRACT_ONLY           (rescue team) - partial plan, offered only when
                                     the victim has no feasible complete plan: free
                                     a trapped victim now, transport in a later round
              TEAM_EVACUATE          (rescue team, hospital or safe zone)
Constraints
  unary   method-applicability, resource-availability, medical-capability,
          icu-capacity, hospital-capacity, hazard-capability, reachability,
          partial-plan-fallback, critical-coverage (hard in phase 1; relaxed
          one victim at a time, lowest priority first, if unsatisfiable)
  binary  resource-conflict(Vi, Vj): no over-subscribed shared resource and
          patients sharing an ambulance go to the same hospital (enables AC-3)
  global  ambulance-capacity[A], team-exclusive[T], er-capacity[H], icu-capacity[H]
Utility  1000 + 20 * priority - estimated rescue time   (DEFER = 0;
         EXTRACT_ONLY earns a reduced base of 600 because the goal is only partly achieved)

A second, smaller CSP re-assigns hospitals when capacity changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable

from app.csp.constraints import BinaryConstraint, CapacityConstraint, Constraint, UnaryConstraint
from app.csp.solver import CSP
from app.environment.grid import Grid
from app.environment.mobility import GROUND_VEHICLE, MobilityProfile, profile_for
from app.models.entities import (
    Ambulance,
    CellType,
    Hospital,
    MedicalLevel,
    Pos,
    RescueTeam,
    SafeZone,
    Severity,
    TeamCapability,
    Unit,
    Victim,
)
from app.search import GridSearchProblem, SearchResult, run_search

METHOD_DIRECT = "AMBULANCE_DIRECT"
METHOD_EXTRACT = "EXTRACT_AND_TRANSPORT"
METHOD_EVACUATE = "TEAM_EVACUATE"
METHOD_EXTRACT_ONLY = "EXTRACT_ONLY"
METHOD_DEFER = "DEFER"
HOLD = "HOLD"

HAZARD_DANGER_THRESHOLD = 0.6
SERVE_BASE_UTILITY = 1000.0
PARTIAL_BASE_UTILITY = 600.0
PRIORITY_WEIGHT = 20.0


@dataclass(frozen=True)
class AllocationOption:
    method: str
    ambulance: str | None = None
    team: str | None = None
    destination: str | None = None

    def label(self) -> str:
        if self.method == METHOD_DEFER:
            return "DEFER"
        if self.method == METHOD_DIRECT:
            return f"{self.ambulance} -> {self.destination}"
        if self.method == METHOD_EXTRACT:
            return f"{self.team} extract + {self.ambulance} -> {self.destination}"
        if self.method == METHOD_EXTRACT_ONLY:
            return f"{self.team} extract only (ambulance later)"
        return f"{self.team} evacuate -> {self.destination}"

    @property
    def units(self) -> list[str]:
        return [u for u in (self.team, self.ambulance) if u]

    @property
    def carrier(self) -> str | None:
        return self.ambulance if self.ambulance else self.team


DEFER = AllocationOption(METHOD_DEFER)


class RouteOracle:
    """Memoised route-cost estimates computed with the agent's search algorithm.

    The cache is only valid for one version of the agent's belief map.
    """

    def __init__(self, grid: Grid, algorithm: str, on_search: Callable[[SearchResult], None] | None = None):
        self.grid = grid
        self.algorithm = algorithm
        self.on_search = on_search
        self._cache: dict[tuple[Pos, Pos, str], SearchResult] = {}
        self.searches = 0
        self.nodes_expanded = 0
        self.time_ms = 0.0

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def route(self, start: Pos, goal: Pos, profile: MobilityProfile) -> SearchResult:
        key = (start, goal, profile.name)
        cached = self._cache.get(key)
        if cached is None:
            cached = run_search(self.algorithm, GridSearchProblem(self.grid, start, goal, profile))
            self._cache[key] = cached
            self.searches += 1
            self.nodes_expanded += cached.nodes_expanded
            self.time_ms += cached.time_ms
            if self.on_search is not None:
                self.on_search(cached)
        return cached

    def cost(self, start: Pos, goal: Pos, profile: MobilityProfile) -> float | None:
        res = self.route(start, goal, profile)
        return res.cost if res.found else None

    def reset_counters(self) -> None:
        self.searches = 0
        self.nodes_expanded = 0
        self.time_ms = 0.0


@dataclass
class VictimNeeds:
    needs_extraction: bool
    hazard: bool
    needs_hospital: bool
    needs_als: bool
    needs_icu: bool
    ground_accessible: bool

    def describe(self) -> list[str]:
        out: list[str] = []
        if self.needs_hospital:
            if self.ground_accessible:
                out.append("ALS ambulance" if self.needs_als else "Ambulance")
            else:
                out.append("Boat/foot evacuation (no road access)")
            out.append("ICU bed" if self.needs_icu else "ER bed")
        else:
            out.append("Rescue team escort to safe zone")
        if self.needs_extraction:
            out.append("FIREFIGHTING team (hazard zone)" if self.hazard else "Rescue team (extraction)")
        return out


def assess_needs(victim: Victim, grid: Grid, oracle: RouteOracle, anchors: list[Pos]) -> VictimNeeds:
    """Derive what a victim requires from its condition and surroundings."""
    on_fire = grid.type_at(victim.pos) == CellType.FIRE
    hazard = on_fire or grid.danger_at(victim.pos) >= HAZARD_DANGER_THRESHOLD
    ground_ok = any(oracle.cost(a, victim.pos, GROUND_VEHICLE) is not None for a in anchors)
    return VictimNeeds(
        needs_extraction=not victim.extracted and (victim.trapped or hazard),
        hazard=hazard and not victim.extracted,
        needs_hospital=victim.needs_hospital,
        needs_als=victim.severity == Severity.CRITICAL,
        needs_icu=victim.needs_icu,
        ground_accessible=ground_ok,
    )


@dataclass
class AllocationProblem:
    kind: str  # RESOURCE_ALLOCATION | DESTINATION_REALLOCATION
    csp: CSP
    utility: Callable[[str, object], float]
    var_order: list[str]
    victims: dict[str, Victim]
    estimates: dict[tuple[str, object], float] = field(default_factory=dict)
    coverage_vars: list[str] = field(default_factory=list)  # vars made "must assign"
    bound: Callable | None = None  # problem-specific branch-and-bound estimate


# --------------------------------------------------------------------------
# Resource allocation CSP
# --------------------------------------------------------------------------
def build_allocation_problem(
    victims: list[Victim],
    needs: dict[str, VictimNeeds],
    ambulances: list[Ambulance],
    teams: list[RescueTeam],
    hospitals: list[Hospital],
    safe_zones: list[SafeZone],
    idle_units: set[str],
    er_free: dict[str, int],
    icu_free: dict[str, int],
    oracle: RouteOracle,
    require_critical: bool,
    coverage: list[str] | None = None,
) -> AllocationProblem:
    """`coverage` restricts critical-coverage to these variables (used for
    minimal relaxation); None means every critical victim that can be served."""
    units: dict[str, Unit] = {u.id: u for u in [*ambulances, *teams]}
    hosp_ids = {h.id for h in hospitals}
    dest_pos: dict[str, Pos] = {h.id: h.pos for h in hospitals} | {s.id: s.pos for s in safe_zones}
    victim_by_var = {v.id: v for v in victims}
    variables = [v.id for v in victims]  # already sorted by priority

    # ---- full (unpruned) domains: the Cartesian product of methods x resources
    full_domain: list[AllocationOption] = []
    for a in ambulances:
        for h in hospitals:
            full_domain.append(AllocationOption(METHOD_DIRECT, ambulance=a.id, destination=h.id))
    for a in ambulances:
        for t in teams:
            for h in hospitals:
                full_domain.append(AllocationOption(METHOD_EXTRACT, ambulance=a.id, team=t.id, destination=h.id))
    for t in teams:
        for d in [*hospitals, *safe_zones]:
            full_domain.append(AllocationOption(METHOD_EVACUATE, team=t.id, destination=d.id))
    for t in teams:
        full_domain.append(AllocationOption(METHOD_EXTRACT_ONLY, team=t.id))
    full_domain.append(DEFER)
    domains = {var: list(full_domain) for var in variables}

    # ---- route estimates (lazy, memoised by the oracle)
    def unit_to_victim(unit_id: str, var: str) -> float | None:
        unit = units[unit_id]
        return oracle.cost(unit.pos, victim_by_var[var].pos, profile_for(unit))

    def victim_to_dest(var: str, opt: AllocationOption) -> float | None:
        if opt.destination is None:  # EXTRACT_ONLY has no transport leg
            return 0.0
        carrier = units[opt.carrier] if opt.carrier else None
        profile = profile_for(carrier) if carrier else GROUND_VEHICLE
        return oracle.cost(victim_by_var[var].pos, dest_pos[opt.destination], profile)

    # ---- unary predicates
    def applicable(var: str, o: AllocationOption) -> bool:
        if o is DEFER:
            return True
        n = needs[var]
        if o.method == METHOD_DIRECT:
            return n.needs_hospital and not n.needs_extraction and n.ground_accessible
        if o.method in (METHOD_EXTRACT, METHOD_EXTRACT_ONLY):
            return n.needs_hospital and n.needs_extraction and n.ground_accessible
        to_hospital = o.destination in hosp_ids
        if n.needs_hospital:
            return to_hospital and not n.ground_accessible
        return not to_hospital

    def available(o: AllocationOption) -> bool:
        return all(units[u].available and u in idle_units for u in o.units)

    def medical_ok(var: str, o: AllocationOption) -> bool:
        if o.ambulance is None or not needs[var].needs_als:
            return True
        amb = units[o.ambulance]
        return isinstance(amb, Ambulance) and amb.medical == MedicalLevel.ALS

    def icu_ok(var: str, o: AllocationOption) -> bool:
        if o.destination not in hosp_ids or not needs[var].needs_icu:
            return True
        return icu_free.get(o.destination, 0) >= 1

    def er_ok(var: str, o: AllocationOption) -> bool:
        if o.destination not in hosp_ids or needs[var].needs_icu:
            return True
        return er_free.get(o.destination, 0) >= 1

    def hazard_ok(var: str, o: AllocationOption) -> bool:
        if o.team is None or not needs[var].hazard:
            return True
        team = units[o.team]
        return isinstance(team, RescueTeam) and team.capability == TeamCapability.FIREFIGHTING

    def reachable(var: str, o: AllocationOption) -> bool:
        if o is DEFER:
            return True
        if any(unit_to_victim(u, var) is None for u in o.units):
            return False
        return victim_to_dest(var, o) is not None

    unary_specs: list[tuple[str, Callable[[str, AllocationOption], bool], str]] = [
        ("method-applicability", applicable, "Rescue method must match the victim's needs (extraction, hospital, road access)"),
        ("resource-availability", lambda var, o: available(o), "Unavailable or busy resources cannot be assigned"),
        ("medical-capability", medical_ok, "Critical victims require an ALS (advanced life support) ambulance"),
        ("icu-capacity", icu_ok, "ICU patients require a hospital with a free ICU bed"),
        ("hospital-capacity", er_ok, "Hospital emergency capacity cannot be exceeded"),
        ("hazard-capability", hazard_ok, "Victims in fire danger zones require a FIREFIGHTING team"),
        ("reachability", reachable, "Every assigned unit must have a route to the victim and the destination"),
    ]

    # Can the victim, considered on its own, receive a complete rescue plan?
    complete_possible = {
        var: any(
            o is not DEFER and o.method != METHOD_EXTRACT_ONLY and all(pred(var, o) for _n, pred, _d in unary_specs)
            for o in full_domain
        )
        for var in variables
    }
    unary_specs.append(
        (
            "partial-plan-fallback",
            lambda var, o: o is DEFER or o.method != METHOD_EXTRACT_ONLY or not complete_possible[var],
            "A partial (extraction-only) plan is allowed only when no complete plan exists for the victim",
        )
    )

    constraints: list[Constraint] = []
    for var in variables:
        for name, pred, desc in unary_specs:
            constraints.append(UnaryConstraint(name, var, (lambda o, p=pred, v=var: p(v, o)), desc))

    coverage_vars: list[str] = []
    if require_critical:
        for var in variables:
            if victim_by_var[var].severity != Severity.CRITICAL:
                continue
            if coverage is not None and var not in coverage:
                continue
            # Only demand coverage when the victim could be served on its own;
            # resource *conflicts* are then left for propagation/search to find.
            # A partial (EXTRACT_ONLY) plan does not count.
            if complete_possible[var]:
                coverage_vars.append(var)
                constraints.append(
                    UnaryConstraint(
                        "critical-coverage",
                        var,
                        lambda o: o is not DEFER and o.method != METHOD_EXTRACT_ONLY,
                        "Every reachable critical victim must get a complete rescue plan this round",
                    )
                )

    # ---- resource usage model shared by the global and binary constraints
    capacity: dict[str, int] = {}
    for a in ambulances:
        capacity[f"amb:{a.id}"] = a.free_seats
    for t in teams:
        capacity[f"team:{t.id}"] = 1
    for h in hospitals:
        capacity[f"er:{h.id}"] = er_free.get(h.id, 0)
        capacity[f"icu:{h.id}"] = icu_free.get(h.id, 0)

    def usage(var: str, o: AllocationOption) -> dict[str, int]:
        if o is DEFER:
            return {}
        out: dict[str, int] = {}
        if o.ambulance:
            amb = units[o.ambulance]
            # A critical patient needs the whole ambulance (no shared trip).
            out[f"amb:{o.ambulance}"] = amb.capacity if victim_by_var[var].severity == Severity.CRITICAL else 1
        if o.team:
            out[f"team:{o.team}"] = 1
        if o.destination in hosp_ids:
            key = "icu" if needs[var].needs_icu else "er"
            out[f"{key}:{o.destination}"] = 1
        return out

    for a in ambulances:
        key = f"amb:{a.id}"
        constraints.append(
            CapacityConstraint(
                f"ambulance-capacity[{a.id}]",
                variables,
                capacity[key],
                lambda var, o, k=key: usage(var, o).get(k, 0),
                f"{a.id} carries at most {a.capacity} patient(s); one rescue at a time; critical patients ride alone",
            )
        )
    for t in teams:
        key = f"team:{t.id}"
        constraints.append(
            CapacityConstraint(
                f"team-exclusive[{t.id}]",
                variables,
                1,
                lambda var, o, k=key: usage(var, o).get(k, 0),
                f"{t.id} cannot perform two tasks simultaneously",
            )
        )
    for h in hospitals:
        for kind, label in (("er", "emergency"), ("icu", "ICU")):
            key = f"{kind}:{h.id}"
            constraints.append(
                CapacityConstraint(
                    f"{kind}-beds[{h.id}]",
                    variables,
                    capacity[key],
                    lambda var, o, k=key: usage(var, o).get(k, 0),
                    f"{h.id} has {capacity[key]} free {label} bed(s)",
                )
            )

    def pair_ok(vi: str, vj: str) -> Callable[[AllocationOption, AllocationOption], bool]:
        def check(a: AllocationOption, b: AllocationOption) -> bool:
            if a is DEFER or b is DEFER:
                return True
            ua, ub = usage(vi, a), usage(vj, b)
            for r in ua.keys() & ub.keys():
                if ua[r] + ub[r] > capacity[r]:
                    return False
            if a.ambulance and a.ambulance == b.ambulance and a.destination != b.destination:
                return False
            return True

        return check

    for vi, vj in combinations(variables, 2):
        constraints.append(
            BinaryConstraint(
                "resource-conflict",
                vi,
                vj,
                pair_ok(vi, vj),
                "Two victims cannot over-subscribe a shared resource; shared ambulance => same hospital",
            )
        )

    # ---- utility: serve high-priority victims first, then minimise rescue time
    estimates: dict[tuple[str, object], float] = {}

    def utility(var: str, o: object) -> float:
        if o is DEFER:
            return 0.0
        key = (var, o)
        if key in estimates:
            return estimates[key]
        assert isinstance(o, AllocationOption)
        v = victim_by_var[var]
        to_dest = victim_to_dest(var, o) or 0.0
        if o.method == METHOD_DIRECT:
            eta = (unit_to_victim(o.ambulance, var) or 0.0) + v.rescue_time + to_dest
        elif o.method == METHOD_EXTRACT:
            team_ready = (unit_to_victim(o.team, var) or 0.0) + v.rescue_time
            eta = max(team_ready, unit_to_victim(o.ambulance, var) or 0.0) + 1 + to_dest
        else:
            eta = (unit_to_victim(o.team, var) or 0.0) + v.rescue_time + to_dest
        base = PARTIAL_BASE_UTILITY if o.method == METHOD_EXTRACT_ONLY else SERVE_BASE_UTILITY
        value = base + PRIORITY_WEIGHT * v.priority - eta
        estimates[key] = value
        return value

    amb_keys = [k for k in capacity if k.startswith("amb:")]
    team_keys = [k for k in capacity if k.startswith("team:")]

    def bound(assignment: dict, current: dict, unassigned: list[str]) -> float:
        """Admissible branch-and-bound estimate (a relaxation of the resource
        constraints): every ambulance-borne rescue needs at least one free seat
        and every team evacuation needs a free team, so at most `seats_left`
        ambulance gains and `teams_left` team gains can still be collected."""
        used: dict[str, int] = {}
        for var, o in assignment.items():
            for k, n in usage(var, o).items():
                used[k] = used.get(k, 0) + n
        seats_left = sum(max(0, capacity[k] - used.get(k, 0)) for k in amb_keys)
        teams_left = sum(max(0, capacity[k] - used.get(k, 0)) for k in team_keys)
        amb_gains, team_gains = [], []
        for v in unassigned:
            amb_gains.append(max((utility(v, x) for x in current[v] if x is not DEFER and x.ambulance), default=0.0))
            team_gains.append(max((utility(v, x) for x in current[v] if x is not DEFER and not x.ambulance), default=0.0))
        amb_gains.sort(reverse=True)
        team_gains.sort(reverse=True)
        pooled = sum(g for g in amb_gains[:seats_left] if g > 0) + sum(g for g in team_gains[:teams_left] if g > 0)
        # A victim can appear in both pools, so also cap by the plain
        # "best value per variable" bound; the minimum of two bounds is a bound.
        plain = sum(max((utility(v, x) for x in current[v]), default=0.0) for v in unassigned)
        return min(pooled, plain)

    return AllocationProblem(
        kind="RESOURCE_ALLOCATION",
        csp=CSP(variables, domains, constraints),
        utility=utility,
        var_order=variables,
        victims=victim_by_var,
        estimates=estimates,
        coverage_vars=coverage_vars,
        bound=bound,
    )


# --------------------------------------------------------------------------
# Destination re-allocation CSP (hospital capacity changed / route lost)
# --------------------------------------------------------------------------
@dataclass
class DestinationItem:
    victim: Victim
    carrier: Unit
    start: Pos  # where the carrier will leave from towards the hospital
    loaded: bool


def build_destination_problem(
    items: list[DestinationItem],
    hospitals: list[Hospital],
    er_free: dict[str, int],
    icu_free: dict[str, int],
    oracle: RouteOracle,
    require_loaded: bool,
) -> AllocationProblem:
    variables = [it.victim.id for it in items]
    by_var = {it.victim.id: it for it in items}
    hosp = {h.id: h for h in hospitals}
    values: list[str] = [h.id for h in hospitals] + [HOLD]
    domains = {var: list(values) for var in variables}

    def route_cost(var: str, h: str) -> float | None:
        it = by_var[var]
        return oracle.cost(it.start, hosp[h].pos, profile_for(it.carrier))

    def bed_type_ok(var: str, h: str) -> bool:
        if h == HOLD:
            return True
        if by_var[var].victim.needs_icu:
            return icu_free.get(h, 0) >= 1
        return er_free.get(h, 0) >= 1

    constraints: list[Constraint] = []
    for var in variables:
        constraints.append(
            UnaryConstraint("bed-availability", var, lambda h, v=var: bed_type_ok(v, h), "Destination must have a free bed of the required type (ICU/ER)")
        )
        constraints.append(
            UnaryConstraint("reachability", var, lambda h, v=var: h == HOLD or route_cost(v, h) is not None, "Carrier must have a route to the hospital")
        )
        if require_loaded and by_var[var].loaded:
            constraints.append(UnaryConstraint("deliver-loaded-patient", var, lambda h: h != HOLD, "Patients already on board must be delivered"))

    def needs_icu(var: str) -> bool:
        return by_var[var].victim.needs_icu

    for h in hospitals:
        constraints.append(
            CapacityConstraint(f"er-beds[{h.id}]", variables, er_free.get(h.id, 0), lambda var, x, hid=h.id: int(x == hid and not needs_icu(var)), f"{h.id} free emergency beds")
        )
        constraints.append(
            CapacityConstraint(f"icu-beds[{h.id}]", variables, icu_free.get(h.id, 0), lambda var, x, hid=h.id: int(x == hid and needs_icu(var)), f"{h.id} free ICU beds")
        )
    for vi, vj in combinations(variables, 2):
        if by_var[vi].carrier.id == by_var[vj].carrier.id:
            constraints.append(
                BinaryConstraint("same-carrier-same-hospital", vi, vj, lambda a, b: a == b, "Patients in the same vehicle go to the same hospital")
            )

    def utility(var: str, h: object) -> float:
        if h == HOLD:
            return 0.0
        cost = route_cost(var, str(h))
        return SERVE_BASE_UTILITY - (cost if cost is not None else 500.0)

    return AllocationProblem(
        kind="DESTINATION_REALLOCATION",
        csp=CSP(variables, domains, constraints),
        utility=utility,
        var_order=variables,
        victims={var: it.victim for var, it in by_var.items()},
    )
