"""Primitive actions the agent can select and the environment can execute."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models.entities import Pos


class ActionType(str, Enum):
    MOVE = "MOVE"  # move one cell (no patient on board)
    RESCUE = "RESCUE"  # on-scene work: extraction or stabilise-and-load
    TRANSPORT = "TRANSPORT"  # move one cell carrying patient(s)
    DELIVER_TO_HOSPITAL = "DELIVER_TO_HOSPITAL"
    DELIVER_TO_SAFE_ZONE = "DELIVER_TO_SAFE_ZONE"
    WAIT = "WAIT"
    REPLAN = "REPLAN"  # agent-level: recorded whenever the plan is repaired


class RescueMode(str, Enum):
    EXTRACT = "EXTRACT"  # free a trapped victim (rescue team)
    LOAD = "LOAD"  # stabilise and load the victim into the carrier


@dataclass(frozen=True)
class Action:
    type: ActionType
    unit_id: str
    target: Pos | None = None
    victim_ids: tuple[str, ...] = ()
    destination_id: str | None = None
    mode: RescueMode | None = None
    duration: int = 1
    task_id: str | None = None
    detail: str = ""

    def describe(self) -> str:
        if self.type in (ActionType.MOVE, ActionType.TRANSPORT) and self.target:
            return f"{self.unit_id} {self.type.value} -> {self.target}"
        if self.type == ActionType.RESCUE:
            return f"{self.unit_id} RESCUE[{self.mode.value if self.mode else ''}] {','.join(self.victim_ids)}"
        if self.type in (ActionType.DELIVER_TO_HOSPITAL, ActionType.DELIVER_TO_SAFE_ZONE):
            return f"{self.unit_id} {self.type.value} {','.join(self.victim_ids)} @ {self.destination_id}"
        return f"{self.unit_id} {self.type.value}"

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "unit_id": self.unit_id,
            "target": list(self.target) if self.target else None,
            "victim_ids": list(self.victim_ids),
            "destination_id": self.destination_id,
            "mode": self.mode.value if self.mode else None,
            "task_id": self.task_id,
            "detail": self.detail,
        }


@dataclass
class ActionResult:
    action: Action
    success: bool
    completed: bool = False  # a multi-tick action (RESCUE) has finished
    message: str = ""
    effects: list[str] = field(default_factory=list)
