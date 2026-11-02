"""Rule completion gate: a scenario cannot complete without an evidence source."""
from __future__ import annotations

from collections.abc import Callable, Iterable


class RuleEvidenceExecutor:
    def __init__(
        self,
        *,
        mark_completed: Callable[..., object],
        delegate: object | None = None,
    ) -> None:
        self._mark_completed = mark_completed
        self._delegate = delegate

    @classmethod
    def wrap(cls, frontier: object) -> "RuleEvidenceExecutor":
        return cls(mark_completed=frontier.mark_completed, delegate=frontier)

    def __getattr__(self, name: str):
        if self._delegate is None:
            raise AttributeError(name)
        return getattr(self._delegate, name)

    def mark_completed(
        self,
        items: Iterable[str],
        *,
        evidence_source: str = "",
        finding_kind: str = "",
    ) -> bool:
        return self.complete(
            items, evidence_source=evidence_source, finding_kind=finding_kind,
        )

    def complete(
        self,
        items: Iterable[str],
        *,
        evidence_source: str = "",
        finding_kind: str = "",
    ) -> bool:
        item_list = [str(item) for item in items if item]
        if not item_list or not (evidence_source or finding_kind):
            return False
        metadata = (
            {"finding_kind": finding_kind}
            if finding_kind else {"evidence_source": evidence_source}
        )
        self._mark_completed(item_list, **metadata)
        return True
