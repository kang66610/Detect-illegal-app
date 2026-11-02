from agent.agent_core.failure_classification import (
    FailureCategory,
    classify_failure,
    failure_progress,
)
from agent.common.exceptions import EngineUnavailableError, ExplorationError


def test_classifies_appium_startup_as_device_unavailable():
    result = classify_failure(
        EngineUnavailableError("Appium 服务未就绪：http://127.0.0.1:4725"),
        stage="traversing",
    )

    assert result.category is FailureCategory.DEVICE_UNAVAILABLE
    assert result.recoverable is True
    assert result.coverage_gap == "device_unavailable"


def test_classifies_live_uiautomator_disconnect_as_session_lost():
    result = classify_failure(
        ExplorationError("无法读取当前页面：socket hang up"),
        stage="traversing",
    )

    assert result.category is FailureCategory.SESSION_LOST
    assert result.recoverable is True


def test_classifies_instrumentation_drop_during_traversal_as_session_lost():
    result = classify_failure(
        ExplorationError("instrumentation process is not running"),
        stage="traversing",
    )

    assert result.category is FailureCategory.SESSION_LOST


def test_classifies_instrumentation_failure_during_startup_as_device_unavailable():
    result = classify_failure(
        ExplorationError("uiautomator2 session creation failed: instrumentation process is not running"),
        stage="preparing",
    )

    assert result.category is FailureCategory.DEVICE_UNAVAILABLE


def test_classifies_disconnect_after_recovery_attempt_as_recovery_exhausted():
    result = classify_failure(
        ExplorationError("无法读取当前页面：socket hang up"),
        stage="traversing",
        recovery_attempted=True,
    )

    assert result.category is FailureCategory.RECOVERY_EXHAUSTED
    assert result.recoverable is False


def test_classifies_failed_recovery_as_recovery_exhausted():
    result = classify_failure(
        ExplorationError("Appium 会话恢复失败，已达到恢复上限"),
        stage="traversing",
        recovery_attempted=True,
    )

    assert result.category is FailureCategory.RECOVERY_EXHAUSTED
    assert result.recoverable is False
    assert result.coverage_gap == "recovery_exhausted"


def test_explicit_failed_recovery_marker_is_terminal_without_runtime_flag():
    result = classify_failure(
        ExplorationError("恢复失败：无法重新启动应用"),
        stage="traversing",
        recovery_attempted=False,
    )

    assert result.category is FailureCategory.RECOVERY_EXHAUSTED
    assert result.recoverable is False


def test_classifies_llm_dependency_failure_separately():
    result = classify_failure(
        EngineUnavailableError("未配置 QWEN_API_KEY，无法使用真实 AI 遍历"),
        stage="traversing",
    )

    assert result.category is FailureCategory.LLM_UNAVAILABLE
    assert result.recoverable is False
    assert result.coverage_gap == "llm_unavailable"


def test_classifies_unexpected_key_error_as_code_bug():
    result = classify_failure(KeyError("1.2"), stage="traversing")

    assert result.category is FailureCategory.CODE_BUG
    assert result.recoverable is False
    assert result.coverage_gap == "code_bug"


def test_classifies_device_transport_failure_as_device_unavailable():
    result = classify_failure(
        ExplorationError("执行遍历操作 activate 失败：设备离线"),
        stage="traversing",
    )

    assert result.category is FailureCategory.DEVICE_UNAVAILABLE
    assert result.recoverable is True


def test_classifies_restart_failure_after_recovery_as_recovery_exhausted():
    result = classify_failure(
        ExplorationError("Appium 会话恢复后无法重新启动应用"),
        stage="traversing",
        recovery_attempted=True,
    )

    assert result.category is FailureCategory.RECOVERY_EXHAUSTED
    assert result.recoverable is False


def test_failure_progress_preserves_audit_as_coverage_limited():
    classification = classify_failure(
        EngineUnavailableError("Appium 服务未就绪"), stage="traversing",
    )

    progress = failure_progress({"stage": "traversing"}, classification)

    assert progress["stage"] == "traversing"
    assert progress["coverage_complete"] is False
    assert progress["failure"]["category"] == "device_unavailable"
    assert "device_unavailable" in progress["coverage_gaps"]
