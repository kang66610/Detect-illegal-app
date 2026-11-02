"""End-of-run findings that do not belong inside the Appium click loop."""
from __future__ import annotations

import json
import re

import yaml

from agent.detection_engines.base import DetectionContext, Finding
from agent.detection_engines.policy_analyzer import _policy_source, policy_discloses_withdraw_path
from agent.detection_engines.static_analyzer import DANGEROUS_PERMISSIONS, list_native_libs
from agent.detection_engines.ui_roles import personalization_mentioned
from backend.app.config import PROJECT_ROOT

_INDUSTRY_PATH = PROJECT_ROOT / "agent" / "config" / "industry_permissions.yaml"
_DELETE_TERMS = ("注销", "删除个人信息", "更正个人信息", "账号注销", "注销账号")
_SETTINGS_TERMS = ("设置", "我的", "账号", "账户", "个人中心")
_POLICY_TERMS = ("隐私政策", "隐私", "服务条款", "用户协议")
_IDENTIFIER_TYPES = {"设备标识信息", "网络与设备信息"}
_IDENTIFIER_TERMS = ("android id", "androidid", "设备标识", "mac", "imei", "oaid", "设备信息")
_DENIED_DATA_TYPES = {"位置信息", "图像信息", "音频信息", "通讯录"}
_NATIVE_HINT_PERMISSIONS = {
    "android.permission.READ_PHONE_STATE",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.READ_CONTACTS",
    "android.permission.RECORD_AUDIO",
    "android.permission.CAMERA",
    "android.permission.READ_SMS",
    "android.permission.READ_CALL_LOG",
}
_NATIVE_HINT_DATA_TYPES = {
    "设备标识信息", "IMSI", "手机号码", "位置信息", "通讯录", "音频信息", "图像信息", "短信",
}


def _load_industry_policy() -> dict:
    return yaml.safe_load(_INDUSTRY_PATH.read_text(encoding="utf-8")) or {}


def _canonical_industry(industry: str, policy: dict | None = None) -> str:
    text = str(industry or "通用").strip() or "通用"
    aliases = (policy or _load_industry_policy()).get("aliases") or {}
    return str(aliases.get(text) or text)


def mismatched_permissions(industry: str, permissions: list[str] | None) -> list[str]:
    policy = _load_industry_policy()
    key = _canonical_industry(industry, policy)
    perms = list(permissions or [])
    never_ok = set(policy.get("never_ok_unless_listed") or [])
    allowed_map = policy.get("allowed") or {}
    allowed = set(allowed_map.get(key) or [])
    known_industry = key in allowed_map
    hits = []
    for perm in perms:
        if perm not in DANGEROUS_PERMISSIONS:
            continue
        if perm in never_ok and perm not in allowed:
            hits.append(perm)
        elif known_industry and perm not in allowed:
            hits.append(perm)
    return sorted(set(hits))


def _policy_mentions_identifiers(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or "")).lower()
    return any(term.replace(" ", "") in compact for term in _IDENTIFIER_TERMS)


def _frida_events(ctx: DetectionContext) -> list[dict]:
    path = ctx.data_dir / "callstack" / "frida-events.json"
    if not path.is_file():
        return list(ctx.runtime.get("frida_events") or [])
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("events") or [])
    except (OSError, json.JSONDecodeError):
        return []


def _network_rows(ctx: DetectionContext) -> list[dict]:
    path = ctx.data_dir / "traffic" / "network-events.json"
    if not path.is_file():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("events") or [])
    except (OSError, json.JSONDecodeError):
        return []


def collect_deferred_findings(ctx: DetectionContext) -> tuple[list[Finding], list[str]]:
    """Emit previously dead-rule findings from runtime facts already collected."""
    findings: list[Finding] = []
    completions: list[str] = []
    seen_text = str(ctx.runtime.get("seen_text") or "")
    termination = str((ctx.runtime.get("traversal_termination") or {}).get("kind") or "")
    finished = termination in {"page_limit_reached", "safe_frontier_exhausted"}
    policy_text, _policy_source_name, policy_complete = _policy_source(ctx)

    if finished and not policy_complete and not any(term in seen_text for term in _POLICY_TERMS):
        findings.append(Finding(kind="policy_missing", category=1, payload={
            "pages_covered": int(ctx.runtime.get("pages_covered") or 0),
            "termination": termination,
        }))
        completions.append("policy_missing")
    elif ctx.runtime.get("policy_document_read_complete"):
        completions.append("policy_document_read")

    if finished and not any(term in seen_text for term in _POLICY_TERMS):
        findings.append(Finding(kind="policy_entry_not_found", category=1, payload={
            "pages_covered": int(ctx.runtime.get("pages_covered") or 0),
            "termination": termination,
        }))
        completions.append("policy_entry_not_found")

    industry = str(getattr(ctx.task, "industry", "") or "通用")
    mismatched = mismatched_permissions(industry, getattr(ctx.apk, "permissions", None))
    if mismatched:
        findings.append(Finding(kind="permission_industry_mismatch", category=4, payload={
            "industry": industry, "permissions": mismatched, "permission_industry_mismatch": True,
        }))
        completions.append("permission_industry_mismatch")

    if (
        finished
        and any(term in seen_text for term in _SETTINGS_TERMS)
        and not any(term in seen_text for term in _DELETE_TERMS)
        and not ctx.runtime.get("delete_paths_observed")
    ):
        findings.append(Finding(kind="no_delete_entry", category=6, payload={
            "pages_covered": int(ctx.runtime.get("pages_covered") or 0),
        }))
        completions.append("no_delete_entry")
    elif ctx.runtime.get("delete_paths_observed"):
        completions.append("delete_entry_found")

    # Exhausting some unrelated branch is not proof that the privacy/account
    # hub was fully inspected.  This previously produced RULE_3_8 on logged-out
    # runs that had merely visited “我的” before hitting a login/crash boundary.
    withdraw_audit_complete = bool(ctx.runtime.get("privacy_hub_audit_complete"))
    if withdraw_audit_complete and ctx.runtime.get("privacy_hub_visited") and not ctx.runtime.get("withdraw_paths_observed"):
        findings.append(Finding(kind="withdraw_consent_unavailable", category=3, payload={
            "pages_covered": int(ctx.runtime.get("pages_covered") or 0),
            "privacy_hub_visited": True,
            "privacy_hub_audit_complete": bool(ctx.runtime.get("privacy_hub_audit_complete")),
            "withdraw_ui_observed": False,
            "policy_document_complete": policy_complete,
            "policy_discloses_withdraw_path": bool(policy_complete and policy_discloses_withdraw_path(policy_text)),
        }))
        completions.append("withdraw_consent_unavailable")
    elif ctx.runtime.get("withdraw_paths_observed"):
        completions.append("withdraw_entry_found")

    if ctx.runtime.get("consent_dialog_seen") or ctx.runtime.get("first_run_notice_observed"):
        completions.append("first_run_notice_observed")
    elif finished:
        findings.append(Finding(kind="first_run_notice_missing", category=1, payload={
            "pages_covered": int(ctx.runtime.get("pages_covered") or 0),
            "termination": termination,
        }))
        completions.append("first_run_notice_missing")

    if ctx.runtime.get("personalization_paths_observed"):
        completions.append("personalization_opt_out_found")
    elif (
        finished
        and ctx.runtime.get("privacy_hub_visited")
        and personalization_mentioned(seen_text + " " + policy_text)
    ):
        findings.append(Finding(kind="targeted_push_no_opt_out", category=3, payload={
            "pages_covered": int(ctx.runtime.get("pages_covered") or 0),
            "privacy_hub_visited": True,
        }))
        completions.append("targeted_push_no_opt_out")

    if ctx.runtime.get("misleading_consent_reported"):
        completions.append("misleading_consent_copy")
    elif ctx.runtime.get("consent_dialog_seen"):
        completions.append("consent_copy_consistent")

    if ctx.runtime.get("forced_consent_reported"):
        completions.append("forced_consent_for_service_improvement")
    elif ctx.runtime.get("consent_dialog_seen"):
        completions.append("consent_not_forced_for_service")

    events = _frida_events(ctx)
    api_events = [event for event in events if event.get("type") == "api"]
    if api_events:
        completions.append("sensitive_api_monitored")
        if ctx.runtime.get("consent_timestamp_ms"):
            completions.append("consent_window_monitored")
    identifier_events = [
        event for event in api_events
        if str(event.get("data_type") or "") in _IDENTIFIER_TYPES
    ]
    if identifier_events and policy_complete and not _policy_mentions_identifiers(policy_text):
        findings.append(Finding(kind="collected_beyond_authorization", category=3, payload={
            "data_types": sorted({str(event.get("data_type")) for event in identifier_events}),
            "count": len(identifier_events),
        }))
        completions.append("collected_beyond_authorization")
    elif identifier_events and policy_complete:
        completions.append("collection_within_authorization")

    denied_at = ctx.runtime.get("permission_denied_at_ms")
    if denied_at:
        after_deny = [
            event for event in api_events
            if float(event.get("time") or 0) >= float(denied_at)
            and str(event.get("data_type") or "") in _DENIED_DATA_TYPES
        ]
        if after_deny:
            findings.append(Finding(kind="api_called_after_permission_denial", category=3, payload={
                "count": len(after_deny), "data_types": sorted({str(e.get("data_type")) for e in after_deny}),
            }))
            completions.append("api_called_after_permission_denial")
        else:
            completions.append("permission_denial_no_subsequent_api")

    background_at = ctx.runtime.get("background_probe_started_ms")
    if background_at:
        background_hits = [
            event for event in api_events
            if float(event.get("time") or 0) >= float(background_at)
            and str(event.get("data_type") or "") in _IDENTIFIER_TYPES | _DENIED_DATA_TYPES
        ]
        if background_hits:
            findings.append(Finding(kind="background_collection", category=4, payload={
                "count": len(background_hits),
                "data_types": sorted({str(event.get("data_type")) for event in background_hits}),
            }))

    for row in _network_rows(ctx):
        if row.get("third_party") and row.get("preceding_data_types") and row.get("sdk"):
            if policy_complete and row["sdk"].lower() not in policy_text.lower():
                findings.append(Finding(kind="sdk_upload_undisclosed", category=5, payload={
                    "sdk": row.get("sdk"), "host": row.get("host"),
                    "preceding_data_types": row.get("preceding_data_types"),
                }))
                completions.append("sdk_upload_undisclosed")
                break

    if policy_complete and not any(item.kind == "sdk_collection_not_disclosed" for item in findings):
        static_sdk = _static_sdk_disclosure_finding(ctx, policy_text)
        if static_sdk:
            # Static package/class markers prove embedding, not actual personal
            # information collection.  Keep this as a coverage/review signal;
            # RULE_2_1_SDK requires a runtime callstack or correlated ledger.
            gap = (
                f"静态识别到第三方 SDK「{static_sdk.payload.get('sdk')}」的潜在收集能力，"
                "但未形成实际收集调用证据，未作 RULE_2_1_SDK 违规认定"
            )
            gaps = ctx.runtime.setdefault("coverage_gaps", [])
            if gap not in gaps:
                gaps.append(gap)
            ctx.runtime["coverage_complete"] = False

    _note_native_coverage_gaps(ctx)

    ctx.runtime["deferred_completions"] = completions
    return findings, completions


def _merged_sdk_list(ctx: DetectionContext) -> list[dict]:
    """Prefer a task-time DEX refresh when the decrypted APK is available."""
    from agent.detection_engines.static_analyzer import refresh_sdk_list_from_apk

    existing = [dict(item) for item in (getattr(ctx.apk, "sdk_list", None) or []) if item]
    refreshed = refresh_sdk_list_from_apk(
        getattr(ctx, "apk_path", None),
        manifest_meta=getattr(ctx.apk, "meta", None) or {},
        permissions=list(getattr(ctx.apk, "permissions", None) or []),
    )
    by_name: dict[str, dict] = {}
    for row in [*existing, *refreshed]:
        name = str((row or {}).get("name") or "").strip()
        if not name:
            continue
        prev = by_name.get(name) or {}
        matched = list(dict.fromkeys([
            *(prev.get("matched_by") or []),
            *((row or {}).get("matched_by") or []),
        ]))
        collected = list(dict.fromkeys([
            *(prev.get("collected") or []),
            *((row or {}).get("collected") or []),
        ]))
        by_name[name] = {
            **prev, **(row or {}),
            "name": name, "matched_by": matched, "collected": collected,
        }
    merged = list(by_name.values())
    if merged and hasattr(ctx.apk, "sdk_list"):
        ctx.apk.sdk_list = merged
    return merged


def _static_sdk_disclosure_finding(ctx: DetectionContext, policy_text: str) -> Finding | None:
    """Known embedded SDK collects a type the complete policy never discloses.

    Used when Frida did not observe the API this run (native/obfuscated paths),
    but DEX/package markers still prove the SDK is present. Permission-only
    matches are ignored — those are not proof of embedding.
    """
    from agent.detection_engines.frida_monitor import _policy_discloses_sdk_data

    for item in _merged_sdk_list(ctx):
        name = str((item or {}).get("name") or "").strip()
        matched_by = [str(marker) for marker in ((item or {}).get("matched_by") or [])]
        weak_only = bool(matched_by) and all(marker.startswith("权限:") for marker in matched_by)
        if not name or weak_only:
            continue
        for data_type in (item or {}).get("collected") or []:
            data_type = str(data_type or "").strip()
            if not data_type:
                continue
            if _policy_discloses_sdk_data(policy_text, name, data_type, sdk=item):
                continue
            return Finding(kind="sdk_collection_not_disclosed", category=2, payload={
                "sdk": name,
                "data_type": data_type,
                "matched_by": matched_by,
                "sdk_known": True,
                "evidence_source": "static_sdk_feature_vs_policy",
                "policy_document_complete": True,
            })
    return None


def _note_native_coverage_gaps(ctx: DetectionContext) -> None:
    """Record a coverage gap when native code may hide sensitive collection.

    This never invents a Finding.  It only marks the audit incomplete when the
    APK ships .so libraries, declares phone/location-class dangerous permissions,
    and the Java hooks did not observe a matching sensitive API this run.
    """
    libs = list(getattr(ctx.apk, "native_libs", None) or []) or list_native_libs(ctx.apk_path)
    if not libs:
        return
    declared = set(getattr(ctx.apk, "permissions", None) or [])
    if not (declared & _NATIVE_HINT_PERMISSIONS):
        return
    events = _frida_events(ctx)
    matching = [
        event for event in events
        if event.get("type") == "api"
        and str(event.get("data_type") or "") in _NATIVE_HINT_DATA_TYPES
    ]
    if matching:
        return
    native_loads = [event for event in events if event.get("type") == "native_load"]
    gap = (
        "APK 含 native 库且声明电话/定位等危险权限，但本次未观察到对应 Java 敏感 API；"
        "可能存在未挂钩的 native 采集路径"
    )
    if native_loads:
        gap = (
            f"{gap}（已观察到 {len(native_loads)} 次 native_load）"
        )
    gaps = ctx.runtime.setdefault("coverage_gaps", [])
    if gap not in gaps:
        gaps.append(gap)
    ctx.runtime["coverage_complete"] = False
    ctx.runtime["native_coverage_gap"] = True
