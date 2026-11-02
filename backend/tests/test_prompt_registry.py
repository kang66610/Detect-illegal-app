import hashlib

from agent.ai_explorer import prompt_registry


def test_navigation_prompt_loaded_from_versioned_yaml_with_content_fingerprint():
    spec = prompt_registry.load_navigation_prompt()

    assert spec.version == "appium-navigation-v3"
    expected = hashlib.sha256(spec.system_prompt.encode("utf-8")).hexdigest()[:12]
    assert spec.fingerprint == expected
    assert f"{spec.version}" and len(spec.fingerprint) == 12


def test_yaml_copy_is_lossless_against_the_original_strategy_text():
    """迁移后的提示词必须保留原有策略文本的全部关键约定。"""
    spec = prompt_registry.load_navigation_prompt()
    body = spec.system_prompt

    for sentinel in (
        "你是 Android App 隐私合规检测平台中的 AI 页面遍历代理。",
        "像人类检测员一样探索页面",
        "unread_document_links",
        "privacy_dialog=true 或 page_role=consent_dialog 时禁止 back/stop",
        "sensitive_media_actions",
        "page_role 以 low_value_ 开头",
        "只能 click 当前页面提供的 action_id",
        "不得填密码",
        "输出：严格一个 JSON",
    ):
        assert sentinel in body, sentinel


def test_llm_controller_system_prompt_comes_from_registry():
    from agent.ai_explorer.llm_controller import SYSTEM_PROMPT

    spec = prompt_registry.load_navigation_prompt()

    assert SYSTEM_PROMPT == spec.system_prompt


def test_adapter_trace_carries_single_source_version_and_fingerprint():
    from agent.ai_explorer.llm_proposal import LLMProposalAdapter

    class _Controller:
        cfg = {}

        def choose_action(self, _page, _visited):
            return {"action": "wait", "target": "", "reason": ""}

    result = LLMProposalAdapter(_Controller()).propose(
        {"activity": ".Main", "elements": []}, visited=set(), allowed_targets=set(),
    )
    spec = prompt_registry.load_navigation_prompt()

    assert LLMProposalAdapter.PROMPT_VERSION == spec.version
    assert result.trace.prompt_version == spec.version
    assert result.trace.prompt_fingerprint == spec.fingerprint
