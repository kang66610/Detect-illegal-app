"""Require cross-source evidence before emitting dynamic-data violations.

Two admission modes are supported; the default is ``strict`` (see
``backend/app/config.py`` → ``rule_engine.evidence_chain_mode``):

- ``strict`` (default): the original full chain — dynamic findings need a
  callstack, a time-correlated behavior ledger and (for SDK findings) a
  consistency matrix; UI findings need a screenshot, a timeline entry and the
  rule's semantic condition.
- ``lenient``: one core artifact is enough.  Dynamic findings are admitted
  with a callstack *or* a time-correlated behavior ledger; UI findings are
  admitted with the rule's semantic condition plus at least one UI artifact
  (screenshot or timeline).  Whatever is still missing is recorded as an
  advisory ``notes`` entry instead of a downgrade, so the report keeps showing
  the real evidence depth.

``lenient`` must be requested explicitly via ``PRIVACY_EVIDENCE_CHAIN_MODE``.
It is not a production default: loosening admission silently would make the
report claim violations on thinner evidence than the README promises.
"""
from __future__ import annotations

from agent.detection_engines.base import Finding


_DYNAMIC_KINDS = {
    "api_called_before_consent", "frequent_collection", "sdk_collection_not_disclosed",
    "overseas_transfer", "collected_beyond_authorization", "api_called_after_permission_denial",
    "sdk_upload_undisclosed", "background_collection",
}
_UI_CHAIN_REQUIREMENTS = {
    # Keep the admission bar practical for real devices: one screenshot plus
    # a timestamped event and the rule-specific semantic payload.  Requiring
    # two screenshots lost valid findings when an OEM replaced the prior
    # surface as soon as a system dialog opened.
    "permission_purpose_not_informed": {"screenshot": 1, "timeline": 1},
    "permission_requested_immediately_after_consent": {"screenshot": 1, "timeline": 1},
    "permission_denial_blocks_function": {"screenshot": 1, "timeline": 1},
    "policy_entry_exceeds_four_clicks": {"screenshot": 1, "timeline": 1},
    "multiple_permissions_requested_after_consent": {"screenshot": 1, "timeline": 1},
    "permission_rerequest_after_denial": {"screenshot": 1, "timeline": 1},
}

_DYNAMIC_ARTIFACT_NAMES = {
    "traced": "动态调用栈",
    "time_correlated": "页面—操作—动态行为时间关联",
    "matrix_ready": "声明—实际一致性矩阵",
}


def _assess_dynamic(kind: str, evidence_files: list[dict], *, lenient: bool) -> dict:
    traced = any(
        item.get("type") == "callstack" and kind in set((item.get("meta") or {}).get("finding_kinds") or [])
        for item in evidence_files
    )
    time_correlated = any(
        item.get("type") == "behavior_ledger"
        and kind in set((item.get("meta") or {}).get("finding_kinds") or [])
        and int((item.get("meta") or {}).get("correlated_count") or 0) > 0
        for item in evidence_files
    )
    matrix_ready = kind != "sdk_collection_not_disclosed" or any(
        item.get("type") == "consistency_matrix"
        and kind in set((item.get("meta") or {}).get("finding_kinds") or [])
        for item in evidence_files
    )
    present = {"traced": traced, "time_correlated": time_correlated, "matrix_ready": matrix_ready}
    notes: list[str] = []
    if lenient:
        # 宽松模式：调用栈或时间关联台账任一命中即可准入，其余缺项（含一致性矩阵）降级为提示。
        # 生产测报优先召回：宁多报不漏报，不在此强制 SDK 矩阵。
        core_ok = traced or time_correlated
        missing = [] if core_ok else [
            name for key, name in _DYNAMIC_ARTIFACT_NAMES.items()
            if key != "matrix_ready" and not present[key]
        ]
        if core_ok:
            notes = [
                f"缺少{name}（宽松模式准入，不影响认定）"
                for key, name in _DYNAMIC_ARTIFACT_NAMES.items() if not present[key]
            ]
        requirements = {"callstack_or_behavior_ledger": True, "consistency_matrix": False}
    else:
        missing = [name for key, name in _DYNAMIC_ARTIFACT_NAMES.items() if not present[key]]
        requirements = {
            "callstack": True,
            "behavior_ledger": True,
            "consistency_matrix": kind == "sdk_collection_not_disclosed",
        }
    status = "admissible" if not missing else "downgraded"
    if status == "admissible":
        reason = "核心动态证据已命中（宽松模式）" if lenient and notes else "完整动态证据链"
    else:
        reason = "缺少" + "、".join(missing)
    return {
        "finding_kind": kind, "status": status, "reason": reason,
        "requirements": requirements, "missing": missing, "notes": notes,
    }


def _semantic_ok(kind: str, finding: Finding) -> bool:
    if kind == "permission_purpose_not_informed":
        return bool(
            finding.payload.get("purpose_context_verified")
            and finding.payload.get("purpose_explained_before_prompt") is False
        )
    if kind == "permission_requested_immediately_after_consent":
        return bool(finding.payload.get("consent_event_present") and finding.payload.get("no_business_action_after_consent"))
    if kind == "permission_denial_blocks_function":
        return bool(
            finding.payload.get("permission_message_matched")
            and finding.payload.get("business_action")
            and finding.payload.get("base_service_blocked")
            and not finding.payload.get("permission_intrinsic_to_action")
        )
    if kind == "policy_entry_exceeds_four_clicks":
        return bool(finding.payload.get("route_anchored_to_main"))
    if kind == "permission_rerequest_after_denial":
        return bool(
            finding.payload.get("previously_denied_at_ms")
            and finding.payload.get("unsolicited_same_context")
        )
    return bool(finding.payload.get("refusal_blocks_app"))


def assess_evidence_chain(
    finding: Finding, evidence_files: list[dict], *, strict_ui: bool = True, mode: str = "strict",
) -> dict:
    """Return a machine-readable admission decision for one finding.

    This is kept separate from rule matching so the report can tell the
    reviewer *why* a candidate was downgraded.  It never promotes a finding;
    it only records whether the rule's declared chain is sufficient.
    ``mode="lenient"`` relaxes the artifact counts (see module docstring);
    the rule's semantic condition is required in both modes.
    """
    lenient = mode == "lenient"
    kind = finding.kind
    if kind in _DYNAMIC_KINDS:
        return _assess_dynamic(kind, evidence_files, lenient=lenient)
    requirements = _UI_CHAIN_REQUIREMENTS.get(kind)
    if not requirements or not strict_ui:
        return {"finding_kind": kind, "status": "not_required", "reason": "该规则由其专属设备证据或静态证据判定", "requirements": {}, "missing": [], "notes": []}
    scoped = []
    for item in evidence_files:
        meta = item.get("meta") or {}
        kinds = {str(meta.get("finding_kind") or ""), *(str(value) for value in meta.get("finding_kinds") or [])}
        if kind in kinds:
            scoped.append(item)
    counts = {evidence_type: sum(item.get("type") == evidence_type for item in scoped) for evidence_type in requirements}
    semantic_ok = _semantic_ok(kind, finding)
    notes: list[str] = []
    if lenient:
        # 宽松模式：任一 UI 证据（截图或时间线）+ 规则语义即可准入。
        has_ui_artifact = any(counts.get(evidence_type, 0) >= 1 for evidence_type in ("screenshot", "timeline"))
        missing = [] if has_ui_artifact else ["screenshot或timeline×1"]
        if has_ui_artifact:
            notes = [
                f"缺少{evidence_type}×{minimum}（宽松模式准入，不影响认定）"
                for evidence_type, minimum in requirements.items() if counts[evidence_type] < minimum
            ]
    else:
        missing = [f"{evidence_type}×{minimum}" for evidence_type, minimum in requirements.items() if counts[evidence_type] < minimum]
    if not semantic_ok:
        missing.append("规则语义条件")
    status = "admissible" if not missing else "downgraded"
    if status == "admissible":
        reason = "核心 UI 证据已命中（宽松模式）" if lenient and notes else "完整 UI 前后对照证据链"
    else:
        reason = "缺少" + "、".join(missing)
    return {
        "finding_kind": kind, "status": status, "reason": reason,
        "requirements": requirements, "observed": counts, "missing": missing, "notes": notes,
    }


def build_evidence_chain_adjudication(
    findings: list[Finding], evidence_files: list[dict], *, strict_ui: bool = True, mode: str = "strict",
) -> list[dict]:
    return [assess_evidence_chain(finding, evidence_files, strict_ui=strict_ui, mode=mode) for finding in findings]


def keep_only_complete_dynamic_chains(
    findings: list[Finding], evidence_files: list[dict], *, mode: str = "strict",
) -> tuple[list[Finding], list[str]]:
    """A sensitive API/network observation needs a page-time anchor and trace.

    Permission-only UI rules remain independently provable by their system
    dialog screenshot/timeline.  Dynamic collection and transfer rules need
    both an Appium page observation and a Frida callstack tagged to the
    finding; ``mode="lenient"`` admits either one alone.
    """
    kept, gaps = [], []
    for finding in findings:
        if finding.kind not in _DYNAMIC_KINDS:
            kept.append(finding)
            continue
        decision = assess_evidence_chain(finding, evidence_files, strict_ui=False, mode=mode)
        if decision["status"] == "admissible":
            kept.append(finding)
        else:
            gaps.append(f"{finding.kind} 缺少页面—操作—动态行为的时间关联证据链，未作违规认定")
    return kept, gaps


def keep_only_complete_evidence_chains(
    findings: list[Finding], evidence_files: list[dict], *, strict_ui: bool = True, mode: str = "strict",
) -> tuple[list[Finding], list[str]]:
    """Validate both dynamic and UI findings before rules and scores are computed."""
    findings, gaps = keep_only_complete_dynamic_chains(findings, evidence_files, mode=mode)
    if not strict_ui:
        return findings, gaps
    kept: list[Finding] = []
    for finding in findings:
        decision = assess_evidence_chain(finding, evidence_files, strict_ui=True, mode=mode)
        if decision["status"] != "downgraded":
            kept.append(finding)
        else:
            gaps.append(f"{finding.kind} 证据链不完整或语义不一致，已降级为待核验")
    return kept, gaps


def keep_only_evidence_bound_matches(matched, evidence_files: list[dict]):
    """Admit only rule matches with at least one rule-scoped artifact.

    Semantic/static findings still need a persisted policy, permission-list,
    screenshot, timeline or dynamic artifact tagged to that finding.  A bare
    boolean candidate may remain in coverage diagnostics, but it cannot be
    emitted as a violation or reduce the score.
    """
    kept = []
    downgraded = []
    for match in matched:
        allowed = set(getattr(match.rule, "evidence_fields", None) or [])
        scoped = False
        for evidence in evidence_files:
            if evidence.get("type") not in allowed:
                continue
            meta = evidence.get("meta") or {}
            kinds = {
                str(meta.get("finding_kind") or ""),
                *(str(item) for item in (meta.get("finding_kinds") or [])),
            }
            if match.finding.kind in kinds:
                scoped = True
                break
        if scoped:
            kept.append(match)
            continue
        downgraded.append({
            "rule_id": str(getattr(match.rule, "rule_id", "") or ""),
            "finding_kind": str(match.finding.kind),
            "reason": "未形成该规则专属证据，已降级为待核验",
        })
    return kept, downgraded
