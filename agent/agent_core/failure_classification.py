"""Stable failure taxonomy shared by workers, reports and recovery logic."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent.common.exceptions import EngineUnavailableError


class FailureCategory(str, Enum):
    DEVICE_UNAVAILABLE = "device_unavailable"
    SESSION_LOST = "session_lost"
    RECOVERY_EXHAUSTED = "recovery_exhausted"
    LLM_UNAVAILABLE = "llm_unavailable"
    CODE_BUG = "code_bug"
    ENGINE_FAILURE = "engine_failure"


@dataclass(frozen=True)
class FailureClassification:
    category: FailureCategory
    recoverable: bool
    coverage_gap: str
    reason: str


_SESSION_LOSS_MARKERS = (
    "socket hang up",
    "could not retrieve the currently focused package and activity",
    "could not proxy command to the remote server",
    "cannot be proxied to uiautomator2",
    "instrumentation process is not running",
    "uiautomator2 server is not running",
    "invalid session id",
    "session not found",
    "no such driver",
    "connection reset by peer",
    "remote end closed connection",
    "read timed out",
)
_RECOVERY_EXHAUSTED_MARKERS = (
    "恢复失败",
    "恢复上限",
    "无法恢复",
    "无法重新启动",
    "recovery exhausted",
    "recovery failed",
)
_LLM_MARKERS = (
    "llm",
    "openai",
    "qwen",
    "千问",
    "真实 ai 遍历",
    "缺少 openai 依赖",
    "未配置 qwen_api_key",
)
_DEVICE_MARKERS = (
    "appium 服务未就绪",
    "appium service unavailable",
    "uiautomator2 会话创建失败",
    "uiautomator2 session creation failed",
    "adb device",
    "设备未连接",
    "设备不可用",
    "settings app is not running",
    "appium 尚未连接",
    "缺少 appium",
    "appium-python-client",
    "connection refused",
    "device offline",
    "device not found",
    "设备离线",
    "设备消失",
    "模拟器",
    "无法启动",
    "无法重启",
    "清除已安装应用数据",
    "安装 apk",
)
_CODE_BUG_TYPES = (KeyError, TypeError, AttributeError, AssertionError, IndexError)


def classify_failure(
    error: Exception,
    *,
    stage: str = "",
    recovery_attempted: bool = False,
) -> FailureClassification:
    """Classify an exception without losing the original error message.

    Classification is intentionally evidence-first: concrete Python contract
    errors win over generic engine messages, and a failed recovery wins over
    the original transient session-loss category.  ``stage`` is metadata for
    callers and does not turn an arbitrary traversal error into a device error.
    """
    message = " ".join(str(error or "未知错误").split())
    lowered = message.lower()

    if isinstance(error, _CODE_BUG_TYPES):
        return FailureClassification(
            FailureCategory.CODE_BUG, False, "code_bug",
            f"{stage or 'unknown'} 阶段出现未处理的代码契约异常：{message[:500]}",
        )
    if any(marker in lowered for marker in _LLM_MARKERS):
        return FailureClassification(
            FailureCategory.LLM_UNAVAILABLE, False, "llm_unavailable",
            f"{stage or 'unknown'} 阶段 LLM 依赖不可用：{message[:500]}",
        )
    explicit_recovery_failure = any(
        marker in lowered for marker in _RECOVERY_EXHAUSTED_MARKERS
    )
    if explicit_recovery_failure or (
        recovery_attempted and any(marker in lowered for marker in _SESSION_LOSS_MARKERS)
    ):
        return FailureClassification(
            FailureCategory.RECOVERY_EXHAUSTED, False, "recovery_exhausted",
            f"{stage or 'unknown'} 阶段运行时恢复未完成：{message[:500]}",
        )
    # A session-creation/startup failure means the device/Appium transport
    # never became usable.  Keep it distinct from a session that dropped
    # during an already-running traversal; the latter is recoverable once.
    startup_stage = str(stage or "").lower() in {
        "preparing", "installing", "connecting", "startup", "initializing",
    }
    if isinstance(error, EngineUnavailableError) or (
        startup_stage and any(marker in lowered for marker in (
            "instrumentation process is not running",
            "uiautomator2 server is not running",
            "uiautomator2 会话创建失败",
            "session creation failed",
        ))
    ):
        return FailureClassification(
            FailureCategory.DEVICE_UNAVAILABLE, True, "device_unavailable",
            f"{stage or 'unknown'} 阶段设备或 Appium 不可用：{message[:500]}",
        )
    if any(marker in lowered for marker in _SESSION_LOSS_MARKERS):
        return FailureClassification(
            FailureCategory.SESSION_LOST, True, "session_lost",
            f"{stage or 'unknown'} 阶段 Appium 运行会话丢失：{message[:500]}",
        )
    if "frida" in lowered:
        return FailureClassification(
            FailureCategory.ENGINE_FAILURE, False, "engine_failure",
            f"{stage or 'unknown'} 阶段 Frida 引擎异常：{message[:500]}",
        )
    if isinstance(error, EngineUnavailableError) or any(marker in lowered for marker in _DEVICE_MARKERS):
        return FailureClassification(
            FailureCategory.DEVICE_UNAVAILABLE, True, "device_unavailable",
            f"{stage or 'unknown'} 阶段设备或 Appium 不可用：{message[:500]}",
        )
    return FailureClassification(
        FailureCategory.ENGINE_FAILURE, False, "engine_failure",
        f"{stage or 'unknown'} 阶段引擎异常：{message[:500]}",
    )


def failure_progress(
    progress: dict | None,
    classification: FailureClassification,
) -> dict:
    """Append a machine-readable failure without erasing progress metadata."""
    values = dict(progress or {})
    values["coverage_complete"] = False
    values["failure"] = {
        "category": classification.category.value,
        "recoverable": classification.recoverable,
        "coverage_gap": classification.coverage_gap,
        "reason": classification.reason,
    }
    gaps = [str(item) for item in values.get("coverage_gaps") or [] if item]
    if classification.coverage_gap not in gaps:
        gaps.append(classification.coverage_gap)
    values["coverage_gaps"] = gaps
    return values
