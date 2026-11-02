"""Per-page overlay for legacy directive-dependent candidate generation."""
from __future__ import annotations

from collections import ChainMap


class DirectivePreviewState:
    """Never mutates the real runtime or emits evidence."""

    def __init__(self, runtime: dict) -> None:
        self.base_runtime = runtime
        self._overlay: dict = {}

    @property
    def runtime_view(self):
        return ChainMap(self._overlay, self.base_runtime)

    def preview(self, directive) -> None:
        for key, value in directive.runtime_updates.items():
            self._overlay[key] = value
        for key, amount in directive.runtime_increments.items():
            self._overlay[key] = int(self.runtime_view.get(key, 0)) + int(amount)

    def discard(self) -> None:
        self._overlay.clear()
