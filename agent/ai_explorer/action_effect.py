"""Schedule and verify semantic effects of Appium actions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ActionEffect:
    status: str
    target: str = ""
    parent_surface: str = ""
    child_surface: str = ""
    attempts: int = 0
    retry_target: str | None = None
    is_business_action: bool = False
    global_key: str = ""
    execution_layer: str = "page"
    page_role: str = "app_page"
    consent_action: bool = False


class ActionEffectLedger:
    """Own pending-action lifecycle so execution and validation cannot drift."""

    def __init__(self, runtime: dict) -> None:
        self.runtime = runtime

    @property
    def pending(self) -> bool:
        return bool(self.runtime.get("pending_action_validation"))

    def discard(self) -> None:
        self.runtime.pop("pending_action_validation", None)

    def is_blocked(self, global_key: str) -> bool:
        """Return whether a semantic target already produced no UI effect.

        The key is semantic rather than coordinate based so an Appium retry
        cannot repeatedly tap the same consent/business control through a
        different locator representation.
        """
        return bool((self.runtime.get("blocked_action_targets") or {}).get(str(global_key or "")))

    def schedule(
        self,
        *,
        surface: str,
        activity: str,
        target: str,
        global_key: str,
        semantic_target: str | None = None,
        is_business_action: bool = False,
        coordinate_retry: bool = False,
        execution_layer: str = "page",
        page_role: str = "app_page",
        consent_action: bool = False,
    ) -> None:
        self.runtime["pending_action_validation"] = {
            "surface": surface,
            "activity": activity,
            "target": target,
            "semantic_target": semantic_target or target,
            "global_key": global_key,
            "is_business_action": bool(is_business_action),
            "coordinate_retry": bool(coordinate_retry),
            "execution_layer": str(execution_layer or "page"),
            "page_role": str(page_role or "app_page"),
            "consent_action": bool(consent_action),
        }

    def observe(
        self,
        *,
        current_surface: str,
        permission_prompt: bool,
        coordinate_target: Callable[[str], str | None] | None = None,
    ) -> ActionEffect | None:
        pending = self.runtime.pop("pending_action_validation", None)
        if not pending:
            return None
        parent = str(pending.get("surface") or "")
        target = str(pending.get("semantic_target") or pending.get("target") or "")
        changed = bool(parent and current_surface != parent)
        if changed or permission_prompt:
            return ActionEffect(
                "permission_prompt" if permission_prompt else "surface_changed",
                target, parent, current_surface,
                is_business_action=bool(pending.get("is_business_action")),
                global_key=str(pending.get("global_key") or target),
                execution_layer=str(pending.get("execution_layer") or "page"),
                page_role=str(pending.get("page_role") or "app_page"),
                consent_action=bool(pending.get("consent_action")),
            )
        key = str(pending.get("global_key") or target)
        counts = self.runtime.setdefault("action_no_effect_counts", {})
        attempt = int(counts.get(key, 0)) + 1
        counts[key] = attempt
        self.runtime.setdefault("blocked_action_targets", {})[key] = {
            "attempts": attempt,
            "reason": "no_effect",
            "execution_layer": str(pending.get("execution_layer") or "page"),
        }
        retry = None
        if (
            pending.get("is_business_action")
            and not pending.get("coordinate_retry")
            and coordinate_target
        ):
            candidate = coordinate_target(target)
            if candidate and candidate != target:
                retry = candidate
        return ActionEffect(
            "no_effect", target, parent, current_surface, attempt, retry,
            bool(pending.get("is_business_action")), key,
            str(pending.get("execution_layer") or "page"),
            str(pending.get("page_role") or "app_page"),
            bool(pending.get("consent_action")),
        )
