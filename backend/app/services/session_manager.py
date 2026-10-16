"""In-memory registry of running simulations (one per browser session)."""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict

from app.environment.simulator import Simulation

MAX_SESSIONS = 32


class SessionNotFound(KeyError):
    pass


class SessionManager:
    def __init__(self, max_sessions: int = MAX_SESSIONS):
        self._sessions: OrderedDict[str, Simulation] = OrderedDict()
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self.max_sessions = max_sessions

    def create(self, scenario: str, seed: int | None, algorithm: str, custom: dict | None) -> tuple[str, Simulation]:
        sim = Simulation(scenario, seed=seed, algorithm=algorithm, custom=custom)
        sid = uuid.uuid4().hex[:12]
        with self._guard:
            self._sessions[sid] = sim
            self._locks[sid] = threading.Lock()
            while len(self._sessions) > self.max_sessions:
                old, _ = self._sessions.popitem(last=False)
                self._locks.pop(old, None)
        return sid, sim

    def get(self, sid: str) -> Simulation:
        with self._guard:
            sim = self._sessions.get(sid)
            if sim is None:
                raise SessionNotFound(sid)
            self._sessions.move_to_end(sid)
            return sim

    def lock(self, sid: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(sid)
            if lock is None:
                raise SessionNotFound(sid)
            return lock

    def delete(self, sid: str) -> None:
        with self._guard:
            if self._sessions.pop(sid, None) is None:
                raise SessionNotFound(sid)
            self._locks.pop(sid, None)

    def __len__(self) -> int:
        return len(self._sessions)
