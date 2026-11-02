"""Semantic time/retry budgets and per-operation latency metrics."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable


@dataclass(frozen=True)
class OperationToken:
    kind: str
    started_at: float


class PerformanceBudget:
    def __init__(self, config: dict, *, clock: Callable[[], float] | None = None) -> None:
        self.config = dict(config or {})
        # Keep metrics independent from the traversal deadline clock. Tests and
        # recovery code may virtualize ``monotonic`` with a finite sequence.
        self.clock = clock or time.perf_counter
        self._document_stuck_since: dict[str, float] = {}
        self._low_value_seen: set[str] = set()
        self._no_effect: dict[str, int] = {}
        self._blocked: set[str] = set()
        self._metrics: dict[str, dict[str, int]] = {}

    def allow_document_scroll(self, document_key: str, *, moved: bool) -> bool:
        key = str(document_key)
        if moved:
            self._document_stuck_since.pop(key, None)
            return True
        now = self.clock()
        started = self._document_stuck_since.setdefault(key, now)
        limit = max(0.0, float(self.config.get("document_stuck_seconds", 12)))
        return now - started <= limit

    def allow_low_value_observation(self, surface_key: str) -> bool:
        key = str(surface_key)
        if key in self._low_value_seen:
            return False
        self._low_value_seen.add(key)
        return True

    def record_action_effect(self, target_key: str, *, effective: bool) -> bool:
        key = str(target_key)
        if effective:
            self._no_effect.pop(key, None)
            self._blocked.discard(key)
            return False
        attempts = self._no_effect.get(key, 0) + 1
        self._no_effect[key] = attempts
        if attempts >= max(1, int(self.config.get("no_effect_attempts", 2))):
            self._blocked.add(key)
        return key in self._blocked

    def target_blocked(self, target_key: str) -> bool:
        return str(target_key) in self._blocked

    def begin(self, kind: str) -> OperationToken:
        return OperationToken(str(kind), self.clock())

    def finish(self, token: OperationToken) -> int:
        elapsed_ms = max(0, int(round((self.clock() - token.started_at) * 1000)))
        self.record(token.kind, elapsed_ms)
        return elapsed_ms

    def record(self, kind: str, elapsed_ms: int) -> None:
        elapsed_ms = max(0, int(elapsed_ms))
        row = self._metrics.setdefault(str(kind), {"count": 0, "total_ms": 0, "max_ms": 0})
        row["count"] += 1
        row["total_ms"] += elapsed_ms
        row["max_ms"] = max(row["max_ms"], elapsed_ms)

    def metrics(self) -> dict[str, dict[str, int]]:
        return {key: dict(value) for key, value in self._metrics.items()}
