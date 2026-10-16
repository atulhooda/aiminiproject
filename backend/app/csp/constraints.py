"""Generic constraint types for finite-domain CSPs.

A constraint has a *scope* (the variables it mentions) and a test that tells
whether a (possibly partial) assignment violates it. Partial assignments are
legal input: a constraint is only violated when the variables assigned so far
already make it impossible to satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Hashable, Mapping, Sequence

Value = Hashable
Assignment = Mapping[str, Value]


class Constraint(ABC):
    kind = "global"

    def __init__(self, name: str, scope: Sequence[str], description: str = ""):
        self.name = name
        self.scope = tuple(scope)
        self.description = description or name

    @abstractmethod
    def is_consistent(self, assignment: Assignment) -> bool:
        """False iff the assigned variables of the scope already violate the constraint."""

    def relevant(self, var: str, value: Value) -> bool:  # noqa: ARG002
        """Can assigning var=value tighten this constraint for other variables?

        Used to skip pointless forward-checking work; the default is safe.
        """
        return True

    def prune(self, var: str, domain: Sequence[Value], assignment: dict[str, Value]) -> list[Value]:
        """Values of `var` that are inconsistent with `assignment` (forward checking)."""
        bad = []
        for value in domain:
            assignment[var] = value
            if not self.is_consistent(assignment):
                bad.append(value)
            del assignment[var]
        return bad

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "scope": list(self.scope), "description": self.description}


class UnaryConstraint(Constraint):
    kind = "unary"

    def __init__(self, name: str, var: str, predicate: Callable[[Value], bool], description: str = ""):
        super().__init__(name, (var,), description)
        self.var = var
        self.predicate = predicate

    def is_consistent(self, assignment: Assignment) -> bool:
        if self.var not in assignment:
            return True
        return bool(self.predicate(assignment[self.var]))


class BinaryConstraint(Constraint):
    kind = "binary"

    def __init__(
        self,
        name: str,
        x: str,
        y: str,
        predicate: Callable[[Value, Value], bool],
        description: str = "",
    ):
        super().__init__(name, (x, y), description)
        self.x = x
        self.y = y
        self.predicate = predicate

    def other(self, var: str) -> str:
        return self.y if var == self.x else self.x

    def satisfied_by(self, var: str, value: Value, other_value: Value) -> bool:
        if var == self.x:
            return bool(self.predicate(value, other_value))
        return bool(self.predicate(other_value, value))

    def is_consistent(self, assignment: Assignment) -> bool:
        if self.x in assignment and self.y in assignment:
            return bool(self.predicate(assignment[self.x], assignment[self.y]))
        return True

    def prune(self, var: str, domain: Sequence[Value], assignment: dict[str, Value]) -> list[Value]:
        other = self.other(var)
        if other not in assignment:
            return []
        ov = assignment[other]
        return [v for v in domain if not self.satisfied_by(var, v, ov)]


def not_equal(x: str, y: str) -> BinaryConstraint:
    return BinaryConstraint(f"{x}!={y}", x, y, lambda a, b: a != b, f"{x} and {y} must differ")


class CapacityConstraint(Constraint):
    """sum(usage(var, value) for assigned var in scope) <= capacity.

    The usage function returns how much of a single shared resource a value
    consumes (0 if it does not use it). Because the sum only grows as more
    variables are assigned, partial-assignment checking is sound.
    """

    kind = "global"

    def __init__(
        self,
        name: str,
        scope: Sequence[str],
        capacity: int,
        usage: Callable[[str, Value], int],
        description: str = "",
    ):
        super().__init__(name, scope, description)
        self.capacity = capacity
        self.usage = usage

    def used(self, assignment: Assignment) -> int:
        return sum(self.usage(v, assignment[v]) for v in self.scope if v in assignment)

    def is_consistent(self, assignment: Assignment) -> bool:
        return self.used(assignment) <= self.capacity

    def relevant(self, var: str, value: Value) -> bool:
        return self.usage(var, value) > 0

    def prune(self, var: str, domain: Sequence[Value], assignment: dict[str, Value]) -> list[Value]:
        remaining = self.capacity - self.used(assignment)
        return [v for v in domain if self.usage(var, v) > remaining]

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["capacity"] = self.capacity
        return data


def describe_value(value: Any) -> str:
    label = getattr(value, "label", None)
    if callable(label):
        return str(label())
    return str(value)
