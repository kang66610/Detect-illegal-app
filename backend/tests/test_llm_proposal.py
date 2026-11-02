import json

from agent.ai_explorer.llm_proposal import LLMProposalAdapter


class _Controller:
    def __init__(self, decision, cfg=None):
        self.decision = decision
        self.cfg = cfg or {}

    def choose_action(self, _page, _visited):
        return dict(self.decision)


def test_llm_cannot_click_target_outside_current_catalog():
    adapter = LLMProposalAdapter(_Controller({
        "action": "click", "target": "购买会员", "reason": "探索",
    }))

    result = adapter.propose(
        {"activity": ".Main", "elements": []}, visited=set(), allowed_targets={"设置"},
    )

    assert result.proposal is None
    assert result.fallback_reason == "target_not_visible_or_allowed"


def test_llm_allowed_target_becomes_low_priority_proposal():
    adapter = LLMProposalAdapter(_Controller({
        "action": "click", "target": "设置", "reason": "探索隐私入口",
    }))

    result = adapter.propose(
        {"activity": ".Main", "elements": []}, visited=set(), allowed_targets={"设置"},
    )

    assert result.proposal is not None
    assert result.proposal.source == "llm"
    assert result.proposal.target == "设置"


def test_visible_label_alias_is_canonicalized_to_execution_target():
    adapter = LLMProposalAdapter(_Controller({
        "action": "click", "target": "隐私政策", "reason": "阅读",
    }))

    result = adapter.propose(
        {"activity": ".Main", "elements": []}, visited=set(),
        allowed_targets={"隐私政策": "privacy", "privacy": "privacy"},
    )

    assert result.proposal is not None
    assert result.proposal.target == "privacy"


def test_prompt_trace_contains_version_and_redacts_credentials():
    adapter = LLMProposalAdapter(_Controller({"action": "wait", "target": "", "reason": ""}))

    result = adapter.propose(
        {
            "activity": ".Login", "password": "secret",
            "screen_text": "账号 tester 密码 secret emulator-5554",
            "elements": [{"text": "secret", "password": True, "target": "password"}],
        },
        visited=set(), allowed_targets={"password"},
    )
    serialized = json.dumps(result.trace.as_dict(), ensure_ascii=False)

    assert result.trace.prompt_version == LLMProposalAdapter.PROMPT_VERSION
    assert "secret" not in serialized
    assert "emulator-5554" not in serialized


def test_malformed_model_output_has_explicit_fallback_reason():
    adapter = LLMProposalAdapter(_Controller({"unexpected": True}))

    result = adapter.propose({}, visited=set(), allowed_targets=set())

    assert result.proposal is None
    assert result.fallback_reason == "invalid_action"


def test_trace_request_snapshot_records_model_visited_and_page():
    """The persisted request must be replayable: model name, cross-page
    visited targets and the (already whitelisted) page snapshot."""
    controller = _Controller(
        {"action": "click", "target": "设置", "reason": "探索"},
        cfg={"llm": {"provider": "openai_compatible", "model": "qwen-x"}},
    )
    adapter = LLMProposalAdapter(controller)

    result = adapter.propose(
        {"activity": ".Main", "elements": []},
        visited={"set-target"},
        allowed_targets={"设置"},
    )

    request = result.trace.request
    assert request["model"] == "qwen-x"
    assert request["visited_targets"] == ["set-target"]
    assert request["page"]["activity"] == ".Main"
    # 结算后的模型入参必须包含页面元素白名单本身（离线回放的语义输入）。
    assert request["page"]["elements"] == []


def test_trace_request_snapshot_stays_despite_model_error():
    """A failed model call still persists what the model was asked about."""
    class _Boom:
        cfg = {"llm": {"model": "m"}}

        def choose_action(self, _page, _visited):
            raise RuntimeError("boom")

    result = LLMProposalAdapter(_Boom()).propose(
        {"activity": ".X", "password": "secret", "elements": []},
        visited=set(), allowed_targets=set(),
    )

    assert result.fallback_reason == "model_error"
    serialized = json.dumps(result.trace.request, ensure_ascii=False)
    assert result.trace.request["model"] == "m"
    assert "secret" not in serialized


def test_trace_request_snapshot_redacts_device_ids_and_passwords():
    adapter = LLMProposalAdapter(_Controller({
        "action": "wait", "target": "", "reason": "",
    }))

    result = adapter.propose(
        {
            "activity": ".Login",
            "password": "secret",
            "udid": "emulator-5554",
            "screen_text": "账号 tester 密码 secret emulator-5554",
            "elements": [{"text": "secret", "password": True, "target": "password"}],
        },
        visited=set(), allowed_targets={"password"},
    )
    serialized = json.dumps(result.trace.request, ensure_ascii=False)

    assert "secret" not in serialized
    assert "emulator-5554" not in serialized


def test_llm_role_correction_is_recorded_but_never_becomes_an_action():
    adapter = LLMProposalAdapter(_Controller({
        "action": "click", "target": "同意", "reason": "处理弹窗",
        "role_correction": "consent_dialog",
    }))

    result = adapter.propose(
        {"activity": ".Main", "page_role": "document_body", "elements": []},
        visited=set(), allowed_targets={"同意"},
    )

    assert result.proposal is not None
    assert result.role_correction == "consent_dialog"
    assert result.proposal.action == "click"
    assert result.trace.response["role_correction"] == "consent_dialog"


def test_invalid_llm_role_correction_is_ignored_without_rejecting_valid_action():
    result = LLMProposalAdapter(_Controller({
        "action": "wait", "target": "", "reason": "稳定观察",
        "role_correction": "invented_role",
    })).propose({}, visited=set(), allowed_targets=set())

    assert result.proposal is not None
    assert result.role_correction is None


def test_role_correction_only_response_is_not_executable_action():
    result = LLMProposalAdapter(_Controller({
        "action": "role_correction",
        "proposed_role": "consent_dialog",
        "supporting_targets": ["同意", "不同意"],
        "reason": "成对决策控件",
    })).propose({}, visited=set(), allowed_targets=set())

    assert result.proposal is None
    assert result.role_correction == "consent_dialog"
    assert result.fallback_reason == "role_correction_only"
    assert result.trace.status == "role_correction"
