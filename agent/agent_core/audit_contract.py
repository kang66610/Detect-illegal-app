"""One auditable contract for a real-device privacy inspection.

The orchestration, Appium, Frida and rule modules remain independent adapters.
This module is the seam that makes their shared six-dimensional guarantees
explicit in every run and every generated report.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy


AUDIT_METHOD = {
    "version": "real-audit-v2",
    "dimensions": {
        "driver": {
            "label": "规则前沿 + 受限 LLM + Appium",
            "guarantee": "规则计划优先，LLM 仅能在当前可见元素白名单中选择安全动作。",
        },
        "page_state": {
            "label": "语义页面状态 + 导航上下文",
            "guarantee": "以 Activity、稳定页面指纹、访问目标和文档滚动状态区分页面；不把重复页面一概丢弃。",
        },
        "evidence": {
            "label": "规则绑定的多源证据链",
            "guarantee": "截图、操作时间线、Frida 调用栈和网络行为按规则关联；链路不完整只降级为待核验。",
        },
        "traversal": {
            "label": "规则场景前沿",
            "guarantee": "每条可设备核验规则都有触发目标；未访问、登录限制和外部阻塞会分别记录。",
        },
        "result": {
            "label": "三态认定",
            "guarantee": "仅输出已形成完整证据链的违规、已执行未形成证据、尚未覆盖；覆盖不足不能被写成合规。",
        },
        "stability": {
            "label": "可恢复的真实设备执行",
            "guarantee": "设备/Appium/Frida 状态均写入时间线；短暂会话中断尝试恢复，真正不可恢复才失败。",
        },
    },
}


def start_audit(ctx) -> None:
    """Install immutable method metadata plus mutable run facts in runtime."""
    ctx.runtime["audit_method"] = deepcopy(AUDIT_METHOD)
    ctx.runtime["audit_execution"] = {
        "page_states": [],
        "actions": 0,
        "recovery_events": [],
        "termination": {"kind": "running", "reason": "检测尚在执行"},
    }


def observe_page(ctx, page, step: int) -> None:
    execution = ctx.runtime.setdefault("audit_execution", {})
    states = execution.setdefault("page_states", [])
    state = {
        "step": int(step),
        "activity": str(getattr(page, "activity", "") or ""),
        "surface": str(getattr(page, "surface_fingerprint", "") or "")[:16],
        "page": str(getattr(page, "fingerprint", "") or "")[:16],
        "element_count": len(getattr(page, "elements", []) or []),
    }
    # Keep the audit summary compact while retaining every state in the raw
    # Appium timeline. Consecutive equal observations add no review value.
    if not states or states[-1] != state:
        states.append(state)
    if len(states) > 160:
        del states[:-160]


def record_action(ctx) -> None:
    execution = ctx.runtime.setdefault("audit_execution", {})
    execution["actions"] = int(execution.get("actions") or 0) + 1


def record_recovery(ctx, kind: str) -> None:
    execution = ctx.runtime.setdefault("audit_execution", {})
    recoveries = execution.setdefault("recovery_events", [])
    if kind not in recoveries:
        recoveries.append(kind)


def finish_audit(ctx, *, kind: str, reason: str, stats: dict | None = None) -> dict:
    """Finalize a reportable outcome without turning coverage gaps into errors."""
    execution = ctx.runtime.setdefault("audit_execution", {})
    execution["termination"] = {"kind": str(kind), "reason": str(reason)}
    execution["coverage_complete"] = bool(ctx.runtime.get("coverage_complete", False))
    execution["coverage_gaps"] = list(dict.fromkeys(ctx.runtime.get("coverage_gaps") or []))
    if stats:
        execution["pages_covered"] = int(stats.get("pages_covered") or 0)
        execution["scenarios_triggered"] = int(stats.get("scenarios") or 0)
    return execution


def summarize_evidence(evidence_files: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(str(item.get("type") or "unknown") for item in evidence_files).items()))
