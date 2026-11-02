"""Versioned and auditable LLM action-proposal seam."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
import re
import time

from agent.ai_explorer.action_arbitration import ActionProposal
from agent.ai_explorer.prompt_registry import load_navigation_prompt


_VALID_ACTIONS = {"click", "back", "wait", "stop", "scroll"}
_VALID_ROLE_CORRECTIONS = {
    "system_launcher", "system_permission", "system_settings", "system_file_picker",
    "system_camera", "external_browser", "foreign_app", "crash", "consent_dialog",
    "document_body", "login_gate", "logged_out_profile", "splash_or_gate",
    "loading_shell", "document_hub", "main_content", "low_value", "app_page",
}
_DEVICE_ID = re.compile(r"\b(?:emulator-\d+|[0-9a-f]{12,})\b", re.I)


@dataclass(frozen=True)
class LLMProposalTrace:
    prompt_version: str
    request: dict
    response: dict
    latency_ms: int
    status: str
    fallback_reason: str = ""
    prompt_fingerprint: str = ""

    def as_dict(self) -> dict:
        return {
            "prompt_version": self.prompt_version,
            "prompt_fingerprint": self.prompt_fingerprint,
            "request": self.request,
            "response": self.response,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class LLMProposalResult:
    proposal: ActionProposal | None
    trace: LLMProposalTrace
    fallback_reason: str = ""
    # This is an observation-only disagreement.  It is deliberately separate
    # from ActionProposal so a model cannot override deterministic role
    # adjudication or enlarge its current target catalog.
    role_correction: str | None = None


def _collect_secrets(value) -> set[str]:
    secrets: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"password", "passwd", "pwd", "token", "secret"}:
                if isinstance(item, str) and item:
                    secrets.add(item)
            if isinstance(item, dict) and item.get("password"):
                for field in ("text", "content_desc", "value"):
                    raw = str(item.get(field) or "")
                    if raw:
                        secrets.add(raw)
            secrets.update(_collect_secrets(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            secrets.update(_collect_secrets(item))
    return secrets


def _redact(value, secrets: set[str]):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in {"password", "passwd", "pwd", "token", "secret"}:
                redacted[str(key)] = "[REDACTED]"
            elif isinstance(item, dict) and item.get("password"):
                protected = dict(item)
                for field in ("text", "content_desc", "value"):
                    if protected.get(field):
                        protected[field] = "[REDACTED]"
                redacted[str(key)] = _redact(protected, secrets)
            else:
                redacted[str(key)] = _redact(item, secrets)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        result = _DEVICE_ID.sub("[DEVICE]", value)
        for secret in sorted(secrets, key=len, reverse=True):
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result
    return value


class LLMProposalAdapter:
    # 版本号与指纹的唯一来源是 navigation.yaml；正文变更必须递增版本。
    _spec = load_navigation_prompt()
    PROMPT_VERSION = _spec.version

    def __init__(self, controller) -> None:
        self._controller = controller

    def propose(
        self,
        page: dict,
        *,
        visited: set[str],
        allowed_targets: set[str] | Mapping[str, str],
    ) -> LLMProposalResult:
        started = time.monotonic()
        raw: dict = {}
        reason = ""
        controller_cfg = getattr(self._controller, "cfg", None) or {}
        model_name = str((controller_cfg.get("llm") or {}).get("model") or "")
        try:
            candidate = self._controller.choose_action(page, visited)
            raw = dict(candidate) if isinstance(candidate, dict) else {}
        except Exception as exc:  # the deterministic caller owns fallback selection
            raw = {"error_type": type(exc).__name__}
            reason = "model_error"
        action = str(raw.get("action") or "")
        target = str(raw.get("target") or "")
        requested_role = str(
            raw.get("proposed_role") if action == "role_correction"
            else raw.get("role_correction") or ""
        ).strip()
        role_correction = requested_role if requested_role in _VALID_ROLE_CORRECTIONS else None
        aliases = (
            {str(key): str(value) for key, value in allowed_targets.items()}
            if isinstance(allowed_targets, Mapping)
            else {str(value): str(value) for value in allowed_targets}
        )
        if action == "role_correction" and role_correction:
            reason = "role_correction_only"
        elif not reason and action not in _VALID_ACTIONS:
            reason = "invalid_action"
        if not reason and action == "click" and (not target or target not in aliases):
            reason = "target_not_visible_or_allowed"
        if not reason and action == "click":
            target = aliases[target]
        proposal = None if reason else ActionProposal(
            action=action,
            target=target,
            reason=str(raw.get("reason") or ""),
            source="llm",
            priority=10,
        )
        secrets = _collect_secrets(page)
        trace = LLMProposalTrace(
            prompt_version=self.PROMPT_VERSION,
            prompt_fingerprint=self._spec.fingerprint,
            # 请求快照=离线回放所需的全部模型输入摘要：模型名、跨页已访问
            # 目标和脱敏后的页面白名单。无论提案成败都必须落盘，模型报错时
            # 同样要知道"它当时被问了什么"。
            request={
                "model": model_name,
                "visited_targets": sorted(str(item) for item in visited),
                "page": _redact(dict(page), secrets),
            },
            response=_redact(raw, secrets),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            status=(
                "accepted" if proposal else
                "role_correction" if reason == "role_correction_only" else "rejected"
            ),
            fallback_reason=reason,
        )
        return LLMProposalResult(
            proposal=proposal,
            trace=trace,
            fallback_reason=reason,
            role_correction=role_correction,
        )
