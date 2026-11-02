"""Small, explicit dispatcher for workflow stages."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


class UnknownStageError(ValueError):
    pass


@dataclass(frozen=True)
class StageDispatcher:
    """Route a named workflow stage to its handler without owning persistence."""

    handlers: Mapping[str, Callable[[dict[str, Any]], None]]

    def dispatch(self, stage: str, context: dict[str, Any]) -> Any:
        handler = self.handlers.get(str(stage or ""))
        if handler is None:
            raise UnknownStageError(f"no handler registered for stage: {stage}")
        return handler(context)
