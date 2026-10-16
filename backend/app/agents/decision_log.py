"""Agent decision log: a timestamped record of every reasoning step."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LogEntry:
    seq: int
    tick: int
    time: str
    phase: str
    level: str  # INFO | DECISION | ALERT | SUCCESS | SEARCH | CSP | REPLAN | EVENT
    message: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "tick": self.tick,
            "time": self.time,
            "phase": self.phase,
            "level": self.level,
            "message": self.message,
            "details": self.details,
        }


class DecisionLog:
    def __init__(self, maxlen: int = 3000):
        self._entries: deque[LogEntry] = deque(maxlen=maxlen)
        self._seq = 0

    def add(self, tick: int, phase: str, level: str, message: str, details: list[str] | None = None) -> LogEntry:
        self._seq += 1
        entry = LogEntry(
            seq=self._seq,
            tick=tick,
            time=datetime.now().strftime("%H:%M:%S"),
            phase=phase,
            level=level,
            message=message,
            details=list(details or []),
        )
        self._entries.append(entry)
        return entry

    def truncate_after(self, seq: int) -> None:
        """Drop entries newer than `seq` (used to collapse repetitive reasoning)."""
        while self._entries and self._entries[-1].seq > seq:
            self._entries.pop()
        self._seq = max(seq, self._entries[-1].seq if self._entries else 0)

    @property
    def last_seq(self) -> int:
        return self._seq

    def since(self, seq: int, limit: int = 600) -> list[LogEntry]:
        items = [e for e in self._entries if e.seq > seq]
        return items[-limit:]

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)
