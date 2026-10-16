"""Backtracking CSP solver with constraint propagation.

Pipeline (each stage is reported back to the UI):

1. Node consistency - every unary constraint prunes its variable's domain.
2. AC-3           - arc consistency over all binary constraints.
3. Backtracking   - depth-first assignment with
     * MRV (minimum remaining values) variable ordering, degree tie-break,
     * value ordering by utility (optimisation) or LCV (satisfaction),
     * forward checking after every assignment (generalised to n-ary
       capacity constraints),
     * optional branch-and-bound on an additive utility, turning the solver
       into a constraint *optimiser* that returns the best consistent
       assignment it can prove (or the best found within the node budget).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from app.csp.constraints import BinaryConstraint, Constraint, UnaryConstraint, Value, describe_value

Utility = Callable[[str, Value], float]
# Optimistic estimate of the utility still obtainable by the unassigned variables.
Bound = Callable[[dict[str, Value], dict[str, list[Value]], list[str]], float]


@dataclass
class CSP:
    variables: list[str]
    domains: dict[str, list[Value]]
    constraints: list[Constraint]

    def __post_init__(self) -> None:
        known = set(self.variables)
        missing = known - set(self.domains)
        if missing:
            raise ValueError(f"variables without a domain: {sorted(missing)}")
        self.constraints_of: dict[str, list[Constraint]] = {v: [] for v in self.variables}
        self.neighbors: dict[str, set[str]] = {v: set() for v in self.variables}
        for c in self.constraints:
            unknown = set(c.scope) - known
            if unknown:
                raise ValueError(f"constraint {c.name} mentions unknown variables {sorted(unknown)}")
            for v in c.scope:
                self.constraints_of[v].append(c)
                self.neighbors[v].update(x for x in c.scope if x != v)

    @property
    def unary(self) -> list[UnaryConstraint]:
        return [c for c in self.constraints if isinstance(c, UnaryConstraint)]

    @property
    def binary(self) -> list[BinaryConstraint]:
        return [c for c in self.constraints if isinstance(c, BinaryConstraint)]


@dataclass
class Removal:
    var: str
    value: str
    constraint: str
    stage: str  # NODE | AC3 | FC

    def to_dict(self) -> dict:
        return {"var": self.var, "value": self.value, "constraint": self.constraint, "stage": self.stage}


@dataclass
class SolverStats:
    nodes: int = 0
    backtracks: int = 0
    consistency_checks: int = 0
    fc_prunings: int = 0
    bound_prunings: int = 0
    ac3_revisions: int = 0
    ac3_removals: int = 0
    node_consistency_removals: int = 0
    solutions_found: int = 0
    time_ms: float = 0.0
    truncated: bool = False

    def to_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


@dataclass
class CSPSolution:
    satisfiable: bool
    assignment: dict[str, Value] | None
    score: float | None
    optimal: bool
    stats: SolverStats
    removal_counts: dict[str, dict[str, int]] = field(default_factory=dict)  # stage -> constraint -> n
    removals: list[Removal] = field(default_factory=list)
    domain_sizes: dict[str, dict[str, int]] = field(default_factory=dict)
    failure_reason: str | None = None


class BacktrackingSolver:
    def __init__(
        self,
        csp: CSP,
        utility: Utility | None = None,
        node_limit: int = 20000,
        use_ac3: bool = True,
        forward_checking: bool = True,
        mrv: bool = True,
        var_order_hint: list[str] | None = None,
        record_limit: int = 250,
        bound: Bound | None = None,
    ):
        self.csp = csp
        self.utility = utility
        self.bound = bound
        self.node_limit = node_limit
        self.use_ac3 = use_ac3
        self.forward_checking = forward_checking
        self.mrv = mrv
        self.record_limit = record_limit
        self._order = {v: i for i, v in enumerate(var_order_hint or csp.variables)}
        self.domains: dict[str, list[Value]] = {v: list(csp.domains[v]) for v in csp.variables}
        self.stats = SolverStats()
        self.removals: list[Removal] = []
        self.removal_counts: dict[str, dict[str, int]] = {"NODE": {}, "AC3": {}, "FC": {}}
        self._best: dict[str, Value] | None = None
        self._best_score = float("-inf")
        self._stop = False

    # ------------------------------------------------------------ public API
    def solve(self) -> CSPSolution:
        t0 = time.perf_counter()
        sizes = {v: {"initial": len(self.domains[v])} for v in self.csp.variables}

        failure = self.enforce_node_consistency()
        for v in self.csp.variables:
            sizes[v]["after_node"] = len(self.domains[v])

        if failure is None and self.use_ac3:
            failure = self.ac3()
        for v in self.csp.variables:
            sizes[v]["after_ac3"] = len(self.domains[v])

        if failure is None:
            self._backtrack({}, 0.0)
            if self._best is None:
                failure = (
                    "search budget exhausted before a solution was found"
                    if self.stats.truncated
                    else "backtracking search proved no consistent assignment exists"
                )

        self.stats.time_ms = (time.perf_counter() - t0) * 1000
        found = self._best is not None
        return CSPSolution(
            satisfiable=found,
            assignment=dict(self._best) if found else None,
            score=self._best_score if found and self.utility else None,
            optimal=found and not self.stats.truncated,
            stats=self.stats,
            removal_counts={k: dict(v) for k, v in self.removal_counts.items()},
            removals=self.removals,
            domain_sizes=sizes,
            failure_reason=None if found else failure,
        )

    # ------------------------------------------------------- propagation
    def enforce_node_consistency(self) -> str | None:
        for c in self.csp.unary:
            dom = self.domains[c.var]
            bad = [v for v in dom if not c.predicate(v)]
            for v in bad:
                dom.remove(v)
                self._record(c.var, v, c.name, "NODE")
                self.stats.node_consistency_removals += 1
            if not dom:
                return f"domain of {c.var} emptied by node consistency ({c.name})"
        return None

    def ac3(self) -> str | None:
        binary = self.csp.binary
        binary_of: dict[str, list[BinaryConstraint]] = {v: [] for v in self.csp.variables}
        for c in binary:
            binary_of[c.x].append(c)
            binary_of[c.y].append(c)
        queue: deque[tuple[str, BinaryConstraint]] = deque()
        for c in binary:
            queue.append((c.x, c))
            queue.append((c.y, c))
        while queue:
            xi, c = queue.popleft()
            xj = c.other(xi)
            if self._revise(xi, xj, c):
                if not self.domains[xi]:
                    return f"AC-3 emptied the domain of {xi} ({c.name} with {xj})"
                for c2 in binary_of[xi]:
                    if c2 is not c:
                        queue.append((c2.other(xi), c2))
        return None

    def _revise(self, xi: str, xj: str, c: BinaryConstraint) -> bool:
        self.stats.ac3_revisions += 1
        revised = False
        dj = self.domains[xj]
        for x in list(self.domains[xi]):
            if not any(c.satisfied_by(xi, x, y) for y in dj):
                self.domains[xi].remove(x)
                self._record(xi, x, c.name, "AC3")
                self.stats.ac3_removals += 1
                revised = True
        return revised

    # ------------------------------------------------------- backtracking
    def _backtrack(self, assignment: dict[str, Value], score: float) -> bool:
        if self._stop:
            return False
        self.stats.nodes += 1
        if self.stats.nodes > self.node_limit:
            self.stats.truncated = True
            self._stop = True
            return False

        if len(assignment) == len(self.csp.variables):
            self.stats.solutions_found += 1
            if self.utility is None:
                self._best, self._best_score = dict(assignment), 0.0
                return True  # satisfaction: first solution is enough
            if score > self._best_score:
                self._best, self._best_score = dict(assignment), score
            return False

        if self.utility is not None and self._best is not None:
            unassigned = [v for v in self.csp.variables if v not in assignment]
            if self.bound is not None:
                optimistic = self.bound(assignment, self.domains, unassigned)
            else:
                optimistic = sum(
                    max((self.utility(v, x) for x in self.domains[v]), default=float("-inf")) for v in unassigned
                )
            if score + optimistic <= self._best_score + 1e-9:
                self.stats.bound_prunings += 1
                return False

        var = self._select_variable(assignment)
        for value in self._order_values(var, assignment):
            self.stats.consistency_checks += 1
            assignment[var] = value
            if not self._consistent(var, assignment):
                del assignment[var]
                continue
            removals: list[tuple[str, Value]] = []
            ok = self._forward_check(var, value, assignment, removals) if self.forward_checking else True
            if ok:
                gain = self.utility(var, value) if self.utility else 0.0
                if self._backtrack(assignment, score + gain):
                    return True
            for v, x in reversed(removals):
                self.domains[v].append(x)
            del assignment[var]
            if self._stop:
                return False
        self.stats.backtracks += 1
        return False

    def _consistent(self, var: str, assignment: dict[str, Value]) -> bool:
        return all(c.is_consistent(assignment) for c in self.csp.constraints_of[var] if c.kind != "unary")

    def _forward_check(
        self, var: str, value: Value, assignment: dict[str, Value], removals: list[tuple[str, Value]]
    ) -> bool:
        for c in self.csp.constraints_of[var]:
            if c.kind == "unary" or not c.relevant(var, value):
                continue
            for other in c.scope:
                if other == var or other in assignment:
                    continue
                dom = self.domains[other]
                for bad in c.prune(other, dom, assignment):
                    dom.remove(bad)
                    removals.append((other, bad))
                    self.stats.fc_prunings += 1
                    self._record(other, bad, c.name, "FC")
                if not dom:
                    return False
        return True

    def _select_variable(self, assignment: dict[str, Value]) -> str:
        unassigned = [v for v in self.csp.variables if v not in assignment]
        if not self.mrv:
            return min(unassigned, key=lambda v: self._order[v])

        def degree(v: str) -> int:
            return sum(1 for n in self.csp.neighbors[v] if n not in assignment)

        return min(unassigned, key=lambda v: (len(self.domains[v]), -degree(v), self._order[v]))

    def _order_values(self, var: str, assignment: dict[str, Value]) -> list[Value]:
        values = list(self.domains[var])
        if self.utility is not None:
            return sorted(values, key=lambda x: -self.utility(var, x))
        # Least-constraining value: prefer values that rule out the fewest
        # options for neighbouring unassigned variables.
        def ruled_out(x: Value) -> int:
            assignment[var] = x
            total = 0
            for c in self.csp.constraints_of[var]:
                if c.kind == "unary":
                    continue
                for other in c.scope:
                    if other != var and other not in assignment:
                        total += len(c.prune(other, self.domains[other], assignment))
            del assignment[var]
            return total

        return sorted(values, key=ruled_out)

    # ---------------------------------------------------------- bookkeeping
    def _record(self, var: str, value: Value, constraint: str, stage: str) -> None:
        stage_counts = self.removal_counts[stage]
        stage_counts[constraint] = stage_counts.get(constraint, 0) + 1
        if len(self.removals) < self.record_limit and stage != "FC":
            self.removals.append(Removal(var, describe_value(value), constraint, stage))
