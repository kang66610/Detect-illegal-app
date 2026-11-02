"""Versioned JSONL format and mandatory redaction for Appium replays."""
from __future__ import annotations

import json
from pathlib import Path
import re


REPLAY_SCHEMA_VERSION = 1
_DEVICE_ID = re.compile(r"\b(?:emulator-\d+|[0-9a-f]{12,})\b", re.I)
_PHONE = re.compile(r"(?<!\d)1\d{10}(?!\d)")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


def _secrets(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"password", "passwd", "pwd", "secret", "token"}:
                if isinstance(item, str) and item:
                    found.add(item)
            if isinstance(item, dict) and item.get("password"):
                for field in ("text", "content_desc", "value"):
                    if item.get(field):
                        found.add(str(item[field]))
            found.update(_secrets(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_secrets(item))
    return found


def redact_replay_value(value, *, secrets: set[str] | None = None):
    secrets = set(secrets or _secrets(value))
    if isinstance(value, dict):
        result = {}
        protected_element = bool(value.get("password"))
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"password", "passwd", "pwd", "secret", "token", "device_id", "udid"}:
                result[str(key)] = "[REDACTED]"
            elif protected_element and lowered in {"text", "content_desc", "value"} and item:
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = redact_replay_value(item, secrets=secrets)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_replay_value(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        result = _DEVICE_ID.sub("[DEVICE]", value)
        result = _PHONE.sub("[PHONE]", result)
        result = _EMAIL.sub("[EMAIL]", result)
        for secret in sorted(secrets, key=len, reverse=True):
            result = result.replace(secret, "[REDACTED]")
        return result
    return value


def replay_facts_for_semantics(semantics) -> dict:
    """Persist only role facts needed to rerun classification, never page PII."""
    role = str(getattr(getattr(semantics, "role", None), "value", "") or "")
    mapping = {
        "system_launcher": "launcher", "system_permission": "permission_prompt",
        "system_settings": "system_settings", "system_file_picker": "file_picker",
        "system_camera": "system_camera", "external_browser": "external_browser",
        "foreign_app": "foreign_app", "crash": "crash", "consent_dialog": "consent_dialog",
        "document_body": "document_body", "login_gate": "login_gate",
        "logged_out_profile": "logged_out_profile", "splash_or_gate": "splash_or_gate",
        "loading_shell": "loading_shell", "document_hub": "document_hub",
        "main_content": "main_content",
    }
    facts = {}
    if role == "low_value":
        facts["low_value_kind"] = str(getattr(semantics, "low_value_kind", "") or "generic")
    elif role in mapping:
        facts[mapping[role]] = True
    if bool(getattr(semantics, "privacy_hub", False)):
        facts["privacy_hub"] = True
    return facts


def replay_semantics_for_resolved(semantics) -> dict:
    """Persist adjudication inputs/outputs without copying page text or targets.

    The snapshot makes role choices and their conflict boundaries auditable on
    replay, while `facts` keeps old replay files fully compatible.
    """
    return {
        "role": str(getattr(getattr(semantics, "role", None), "value", "") or "app_page"),
        "scope": str(getattr(getattr(semantics, "scope", None), "value", "") or "audited_app"),
        "blocked_roles": [
            str(getattr(item, "value", item))
            for item in getattr(semantics, "blocked_roles", ())
        ],
        "evidence": [
            {
                "role": str(getattr(getattr(item, "role", None), "value", "") or ""),
                "source": str(getattr(getattr(item, "source", None), "value", "") or ""),
                "strength": int(getattr(item, "strength", 0) or 0),
                # Hits name detection predicates, not UI text; target ids and
                # labels are intentionally excluded to keep replay PII-safe.
                "hits": [str(value) for value in getattr(item, "hits", ())],
            }
            for item in getattr(semantics, "evidence", ())
        ],
    }


class ReplayWriter:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._header_written = self.path.exists() and self.path.stat().st_size > 0

    def write(self, record: dict) -> None:
        rows = []
        if not self._header_written:
            rows.append({"schema_version": REPLAY_SCHEMA_VERSION, "type": "header"})
            self._header_written = True
        rows.append(redact_replay_value(record))
        with self.path.open("a", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_replay(path: Path) -> list[dict]:
    rows = [
        json.loads(line) for line in Path(path).read_text("utf-8").splitlines()
        if line.strip()
    ]
    if not rows or rows[0].get("type") != "header":
        raise ValueError("missing replay header")
    version = int(rows[0].get("schema_version") or 0)
    if version != REPLAY_SCHEMA_VERSION:
        raise ValueError(f"unsupported replay schema: {version}")
    return rows[1:]
