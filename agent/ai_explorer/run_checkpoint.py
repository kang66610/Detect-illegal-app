"""Versioned serialization for the typed Appium detection run state."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.ai_explorer.runtime_state import DetectionRunState


@dataclass(frozen=True)
class CheckpointRestoreResult:
    restored: bool
    schema_version: int | None
    reason: str = ""


@dataclass(frozen=True)
class TraversalRestoreResult:
    restored: bool
    payload: dict
    reason: str = ""


def _json_safe(value: Any):
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class TraversalCheckpointRepository:
    """Version-four traversal persistence with one page/document snapshot."""

    VERSION = 4

    def __init__(
        self, data_dir: Path, runtime: dict, *, runtime_keys: tuple[str, ...] = (),
        set_like_keys: tuple[str, ...] = (),
    ) -> None:
        self.data_dir = Path(data_dir)
        self.runtime = runtime
        self.runtime_keys = tuple(runtime_keys)
        self.set_like_keys = frozenset(set_like_keys)

    @property
    def traversal_path(self) -> Path:
        return self.data_dir / "runtime" / "traversal-checkpoint.json"

    @property
    def navigation_path(self) -> Path:
        return self.data_dir / "runtime" / "navigation-replay-checkpoint.json"

    def save_traversal(self, *, state, run_state, findings: list[dict], evidence: list[dict]) -> Path:
        path = self.traversal_path
        path.parent.mkdir(parents=True, exist_ok=True)
        selected_runtime = {
            key: _json_safe(self.runtime[key])
            for key in self.runtime_keys if key in self.runtime
        } if self.runtime_keys else _json_safe(self.runtime)
        payload = {
            "version": self.VERSION,
            "run_state": RunCheckpointCodec.dump(run_state) if run_state is not None else {},
            "runtime": selected_runtime,
            "page_state": {
                "covered_pages": sorted(state.covered_pages),
                # Keep these v4 compatibility fields while document_reading is
                # the authoritative serialized ledger.
                "completed_documents": sorted(
                    set(state.completed_documents) | state.documents.completed_keys()
                ),
                "navigation_replay": state.navigation_replay.as_dict(),
                "document_reading": state.documents.as_dict(),
            },
            "findings": _json_safe([
                {"kind": item.kind, "category": item.category, "payload": item.payload}
                if hasattr(item, "kind") else item
                for item in findings
            ]),
            "evidence": _json_safe(evidence),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def restore_traversal(self, state) -> TraversalRestoreResult:
        path = self.traversal_path
        if not path.exists():
            return TraversalRestoreResult(False, {}, "missing")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return TraversalRestoreResult(False, {}, "invalid_json")
        if int(payload.get("version") or 0) != self.VERSION:
            return TraversalRestoreResult(False, payload, "unsupported_version")
        for key, value in dict(payload.get("runtime") or {}).items():
            if self.runtime_keys and key not in self.runtime_keys:
                continue
            self.runtime[key] = set(value or []) if key in self.set_like_keys else value
        page_state = dict(payload.get("page_state") or {})
        state.covered_pages.update(str(item) for item in page_state.get("covered_pages") or [])
        if isinstance(page_state.get("document_reading"), dict):
            state.documents.restore(page_state["document_reading"])
            state.completed_documents.update(state.documents.completed_keys())
            state.active_document = state.documents.active_key
            for key, session in state.documents.sessions.items():
                state.document_scrolls[key] = session.scrolls
                state.document_entry_clicks[key] = session.entry_clicks
        else:
            state.completed_documents.update(str(item) for item in page_state.get("completed_documents") or [])
        # Version-four writers may still carry a legacy completed set while
        # the reading ledger has no session (for example a checkpoint taken
        # between older document state transitions). Preserve that evidence.
        state.completed_documents.update(
            str(item) for item in page_state.get("completed_documents") or []
        )
        if isinstance(page_state.get("navigation_replay"), dict):
            state.navigation_replay.restore(page_state["navigation_replay"])
        return TraversalRestoreResult(True, payload)

    def save_navigation(self, state) -> Path:
        path = self.navigation_path
        path.parent.mkdir(parents=True, exist_ok=True)
        recovery_keys = (
            "runtime_session_recovery_attempted", "runtime_session_recovery_attempts",
            "runtime_session_recoveries", "runtime_session_recovery_status",
            "runtime_checkpoint_replayed", "navigation_replay_required",
        )
        payload = {
            "version": 1,
            "navigation_replay": state.navigation_replay.as_dict(),
            "runtime_recovery": {
                key: _json_safe(self.runtime[key]) for key in recovery_keys if key in self.runtime
            },
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def restore_navigation(self, state) -> bool:
        path = self.navigation_path
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return False
        value = payload.get("navigation_replay")
        if not isinstance(value, dict):
            return False
        state.navigation_replay.restore(value)
        for key, value in dict(payload.get("runtime_recovery") or {}).items():
            self.runtime[key] = value
        return True


class RunCheckpointCodec:
    SCHEMA_VERSION = 1

    @classmethod
    def dump(cls, state: DetectionRunState) -> dict:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "state": state.export_checkpoint_state(),
        }

    @classmethod
    def restore(cls, payload: dict, state: DetectionRunState) -> CheckpointRestoreResult:
        if not isinstance(payload, dict):
            return CheckpointRestoreResult(False, None, "invalid_payload")
        raw_version = payload.get("schema_version")
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            return CheckpointRestoreResult(False, None, "missing_schema_version")
        if version > cls.SCHEMA_VERSION:
            return CheckpointRestoreResult(False, version, "unsupported_future_schema")
        if version < 1:
            return CheckpointRestoreResult(False, version, "unsupported_legacy_schema")
        raw_state = payload.get("state")
        if not isinstance(raw_state, dict):
            return CheckpointRestoreResult(False, version, "invalid_state")
        state.restore_checkpoint_state(raw_state)
        return CheckpointRestoreResult(True, version)
