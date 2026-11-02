"""Deterministic document-entry and first-run consent decisions."""
from __future__ import annotations

from dataclasses import dataclass

from agent.ai_explorer.action_executor import ActionExecutionResult
from agent.ai_explorer.decision_directive import DecisionDirective


@dataclass(frozen=True)
class ConsentActionResult:
    accept_attempted: bool = False
    declined_privacy: bool = False
    awaiting_effect_confirmation: bool = False


@dataclass(frozen=True)
class ConsentDecisionInput:
    unread_document: str = ""
    document_kind: str = ""
    consent_dialog: bool = False
    consent_accepted: bool = False
    document_target_visited: bool = False
    checkbox_target: str = ""
    checkbox_clicks: int = 0
    consent_target: str = ""
    consent_target_visited: bool = False
    consent_button_retries: int = 0
    consent_target_blocked: bool = False


class ConsentDecisionModule:
    """Own document-before-consent ordering and bounded consent recovery."""

    def propose(self, facts: ConsentDecisionInput) -> DecisionDirective | None:
        if facts.unread_document and not facts.consent_dialog and facts.consent_accepted:
            return DecisionDirective(
                "click", facts.unread_document,
                "在设置/个人信息/关于我们等枢纽打开尚未阅读的隐私政策/协议/清单",
                "deterministic_document", "required_document_prioritized",
                {"document_kind": facts.document_kind, "note": "hub_document_reading"},
            )
        if facts.unread_document and facts.consent_dialog and not facts.document_target_visited:
            return DecisionDirective(
                "click", facts.unread_document,
                "首次同意页存在独立条款入口，先做一次有界打开验证，避免后续无入口造成漏检",
                "deterministic_document", "splash_document_probe_started",
                {"document_kind": facts.document_kind},
            )
        if facts.checkbox_target and facts.checkbox_clicks < 2:
            return DecisionDirective(
                "click", facts.checkbox_target,
                "可见启动页条款已完成有界探测后，勾选“阅读并同意”复选框",
                "deterministic_consent_checkbox", "consent_checkbox_required",
                runtime_increments={"consent_checkbox_clicks": 1},
                completed_scenarios=("3.4",),
                completion_source="consent_checkbox_unchecked",
                effects=("forget_consent_target",),
            )
        if not facts.consent_dialog:
            return None
        common_updates = {"consent_policy_docs_deferred_to_hub": True}
        if facts.consent_target and facts.consent_target_blocked:
            return DecisionDirective(
                "stop", "",
                "同意控件已点击但未产生页面或权限语义变化，停止重复点击并标记该阶段未完成",
                "deterministic_consent", "consent_target_no_effect",
                runtime_updates={**common_updates, "consent_target_no_effect": True},
            )
        if facts.consent_target and not facts.consent_target_visited:
            return DecisionDirective(
                "click", facts.consent_target,
                "启动页可定位条款已完成有界探测；同意进入应用后，继续到设置、我的、个人信息或关于我们补齐未读条款",
                "deterministic_consent", "consent_without_splash_documents",
                {"reason": "policy_docs_deferred_to_hub"}, common_updates,
            )
        if facts.consent_target and facts.consent_target_visited and facts.consent_button_retries < 2:
            return DecisionDirective(
                "click", facts.consent_target,
                "同意弹窗仍在，再次点击同意进入应用（有界重试）",
                "deterministic_consent", "consent_button_retried",
                runtime_updates=common_updates,
                runtime_increments={"consent_button_retries": 1},
            )
        return DecisionDirective(
            "wait", "", "首次同意弹窗暂未见可用同意按钮，等待控件出现",
            "deterministic_consent", "consent_dialog_wait_for_agree",
            runtime_updates=common_updates,
        )

    def observe_action_result(
        self, result: ActionExecutionResult, *, consent_action: bool = False,
        declined_privacy: bool = False,
    ) -> ConsentActionResult:
        """Classify one executed click for the consent domain.

        Acceptance itself is confirmed from the next page effect, never from
        the click command, so this only records what the action attempted.
        """
        click_landed = result.succeeded and result.action == "click"
        accept = bool(click_landed and consent_action and not declined_privacy)
        return ConsentActionResult(
            accept_attempted=accept,
            declined_privacy=bool(click_landed and declined_privacy),
            awaiting_effect_confirmation=accept,
        )

    def defer_splash_document(
        self, *, original_target: str, checkbox_target: str,
        checkbox_clicks: int, consent_target: str,
    ) -> DecisionDirective:
        common = {"consent_policy_docs_deferred_to_hub": True}
        meta = {"original_target": original_target, "reason": "policy_docs_deferred_to_hub"}
        if checkbox_target and checkbox_clicks < 2:
            return DecisionDirective(
                "click", checkbox_target,
                "首次同意弹窗不展开外链条款，先勾选阅读并同意",
                "deterministic_consent_checkbox", "splash_document_click_deferred", meta,
                common, {"consent_checkbox_clicks": 1},
                completed_scenarios=("3.4",), completion_source="consent_checkbox_unchecked",
                effects=("forget_consent_target",),
            )
        if consent_target:
            return DecisionDirective(
                "click", consent_target,
                "首次同意弹窗不展开外链条款，直接同意进入应用后再到设置/我的阅读",
                "deterministic_consent", "splash_document_click_deferred", meta, common,
            )
        return DecisionDirective(
            "wait", "", "首次同意弹窗暂不打开条款外链，等待可见的同意控件",
            "deterministic_consent", "splash_document_click_deferred", meta, common,
        )

    def force_progress(
        self, *, checkbox_target: str, consent_target: str,
        consent_target_visited: bool,
        consent_target_blocked: bool = False,
    ) -> DecisionDirective | None:
        if checkbox_target:
            return DecisionDirective(
                "click", checkbox_target, "同意弹窗尚未勾选，不能结束遍历",
                "deterministic_consent_checkbox", "consent_dialog_progress_forced",
                runtime_increments={"consent_checkbox_clicks": 1},
                completed_scenarios=("3.4",), completion_source="consent_checkbox_unchecked",
                effects=("forget_consent_target",),
            )
        if consent_target and consent_target_blocked:
            return DecisionDirective(
                "stop", "", "同意控件已验证无效果，不能用强制进度逻辑重复点击",
                "deterministic_consent", "consent_target_no_effect",
                runtime_updates={"consent_target_no_effect": True},
            )
        if consent_target and not consent_target_visited:
            return DecisionDirective(
                "click", consent_target, "同意弹窗仍可进入应用，继续检测而不结束",
                "deterministic_consent", "consent_dialog_progress_forced",
            )
        return None
