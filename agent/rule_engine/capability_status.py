"""Explicit status for checks that are not always executable automatically."""
from __future__ import annotations


def automatic_capability_status(runtime: dict, findings: list, evidence_files: list[dict]) -> dict:
    kinds = {str(item.kind) for item in findings}
    policy_complete = bool(runtime.get("policy_document_read_complete"))
    policy_html_available = bool(runtime.get("policy_preserved_html"))
    credential_events = []
    for artifact in evidence_files:
        meta = artifact.get("meta") or {}
        if artifact.get("type") not in {"traffic", "behavior_ledger", "callstack"}:
            continue
        if meta.get("credential_fields") or meta.get("authorization_present"):
            credential_events.append(artifact)

    if "sensitive_information_not_emphasized" in kinds:
        sensitive = {"status": "violation_observed", "reason": "已取得保留样式的政策正文并形成违规证据"}
    elif policy_complete and policy_html_available:
        sensitive = {"status": "executed_no_violation_evidence", "reason": "已执行 DOM/HTML 样式检测，未形成违规证据"}
    else:
        sensitive = {"status": "not_executed", "reason": "未取得可解析 DOM/CSS 样式，不能从纯文本推断显著标识"}

    if "login_data_unprotected" in kinds:
        login_transport = {"status": "violation_observed", "reason": "已观察到认证字段通过明文 HTTP 传输"}
    elif credential_events:
        login_transport = {"status": "executed_no_violation_evidence", "reason": "已观察认证传输，但未形成明文 HTTP 违规证据"}
    else:
        login_transport = {"status": "not_executed", "reason": "未使用安全测试账号触发认证请求，不能推断登录数据已加密或去标识化"}
    return {
        "sensitive_information_emphasis": sensitive,
        "login_data_protection": login_transport,
    }
