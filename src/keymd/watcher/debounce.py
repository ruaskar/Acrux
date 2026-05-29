"""debounce.py — coalesce rapid per-path events; clock-injectable for tests."""
from __future__ import annotations

from typing import Callable


class Debouncer:
    def __init__(self, delay: float, fn: Callable[[str], None]) -> None:
        self.delay = delay
        self.fn = fn
        self._due: dict[str, float] = {}

    def submit(self, path: str, now: float) -> None:
        self._due[path] = now + self.delay

    def flush_due(self, now: float) -> None:
        ready = [p for p, t in self._due.items() if now >= t]
        for p in ready:
            del self._due[p]
            self.fn(p)
