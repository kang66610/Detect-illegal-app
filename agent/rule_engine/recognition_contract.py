"""Single map: 31 recognition items ↔ YAML rules ↔ finding kinds ↔ completion."""
from __future__ import annotations

from dataclasses import dataclass

from agent.rule_engine.recognition_coverage import ITEM_BY_KEY


@dataclass(frozen=True)
class ItemContract:
    rule_ids: tuple[str, ...]
    finding_kinds: tuple[str, ...]
    complete_if: tuple[str, ...]


def _item(rule_ids=(), finding_kinds=(), complete_if=()):
    return ItemContract(tuple(rule_ids), tuple(finding_kinds), tuple(complete_if))


CONTRACT: dict[str, ItemContract] = {
    "1.1": _item(("RULE_1_1",), ("policy_missing",), ("policy_missing", "policy_document_read")),
    "1.2": _item(
        ("RULE_1_2_NOTICE",),
        ("first_run_notice_missing",),
        ("first_run_notice_missing", "first_run_notice_observed"),
    ),
    "1.3": _item(
        ("RULE_1_2", "RULE_1_3"),
        ("policy_entry_not_found", "policy_entry_exceeds_four_clicks"),
        ("policy_entry_not_found", "policy_entry_exceeds_four_clicks", "policy_entry_within_four_clicks"),
    ),
    "1.4": _item(
        (),
        (),
        ("terms_document_read", "all_consent_documents_read", "terms_body_reviewed"),
    ),
    "2.1": _item(
        ("RULE_2_1", "RULE_2_1_SDK"),
        ("purpose_not_disclosed", "sdk_collection_not_disclosed"),
        ("purpose_not_disclosed", "sdk_collection_not_disclosed", "purpose_disclosed"),
    ),
    "2.2": _item(),
    "2.3": _item(
        ("RULE_2_2",),
        ("permission_purpose_not_informed",),
        ("permission_purpose_not_informed", "permission_prompt_observed"),
    ),
    "2.4": _item(
        (),
        (),
        ("purpose_disclosed", "purpose_not_disclosed", "policy_document_read", "policy_semantics_reviewed"),
    ),
    "3.1": _item(
        ("RULE_3_1",),
        ("api_called_before_consent",),
        ("api_called_before_consent", "consent_window_monitored"),
    ),
    "3.2": _item(
        ("RULE_3_REFUSE", "RULE_3_REREQUEST"),
        ("api_called_after_permission_denial", "permission_rerequest_after_denial"),
        (
            "api_called_after_permission_denial",
            "permission_rerequest_after_denial",
            "permission_denial_no_subsequent_api",
        ),
    ),
    "3.3": _item(
        ("RULE_3_2",),
        ("collected_beyond_authorization",),
        ("collected_beyond_authorization", "collection_within_authorization"),
    ),
    "3.4": _item(
        ("RULE_3_4",),
        ("consent_checkbox_prechecked",),
        ("consent_checkbox_prechecked", "consent_checkbox_unchecked"),
    ),
    "3.5": _item(),
    "3.6": _item(
        ("RULE_3_6",),
        ("targeted_push_no_opt_out",),
        ("targeted_push_no_opt_out", "personalization_opt_out_found"),
    ),
    "3.7": _item(
        ("RULE_3_7",),
        ("misleading_consent_copy",),
        ("misleading_consent_copy", "consent_copy_consistent"),
    ),
    "3.8": _item(
        ("RULE_3_8",),
        ("withdraw_consent_unavailable",),
        ("withdraw_consent_unavailable", "withdraw_entry_found"),
    ),
    "3.9": _item(
        (),
        (),
        (
            "sdk_collection_not_disclosed",
            "collected_beyond_authorization",
            "collection_within_authorization",
            "purpose_disclosed",
            "declaration_behavior_reviewed",
        ),
    ),
    "4.1": _item(
        ("RULE_4_1", "RULE_4_1_CONSENT"),
        ("permission_industry_mismatch", "permission_requested_immediately_after_consent"),
        (
            "permission_industry_mismatch",
            "permission_requested_immediately_after_consent",
            "permission_after_business_action",
        ),
    ),
    "4.2": _item(
        ("RULE_4_2",),
        ("permission_denial_blocks_function",),
        ("permission_denial_blocks_function", "permission-denial-retry"),
    ),
    "4.3": _item(),
    "4.4": _item(
        ("RULE_4_4",),
        ("frequent_collection",),
        ("frequent_collection", "sensitive_api_monitored"),
    ),
    "4.5": _item(
        ("RULE_4_5",),
        ("forced_consent_for_service_improvement",),
        ("forced_consent_for_service_improvement", "consent_not_forced_for_service"),
    ),
    "4.6": _item(
        ("RULE_4_6",),
        ("multiple_permissions_requested_after_consent",),
        ("multiple_permissions_requested_after_consent",),
    ),
    "5.1": _item(
        ("RULE_5_1", "RULE_5_2"),
        ("overseas_transfer", "sdk_upload_undisclosed"),
        ("overseas_transfer", "sdk_upload_undisclosed"),
    ),
    "5.2": _item(),
    "5.3": _item(
        (),
        (),
        ("third_party_app_consent_observed",),
    ),
    "6.1": _item(("RULE_6_1",), ("no_delete_entry",), ("no_delete_entry", "delete_entry_found")),
    "6.2": _item(("RULE_6_2",), ("delete_obstacle",), ("delete_obstacle",)),
    "6.3": _item(
        ("RULE_6_3",),
        ("no_complaint_channel",),
        ("no_complaint_channel", "complaint_channel_ok"),
    ),
    "6.4": _item(
        ("RULE_6_4",),
        ("invalid_contact_format",),
        ("invalid_contact_format",),
    ),
    "6.5": _item(
        ("RULE_6_5",),
        ("complaint_processing_time_missing",),
        ("complaint_processing_time_missing", "complaint_deadline_disclosed"),
    ),
}

assert set(CONTRACT) == set(ITEM_BY_KEY)

RULE_LEGAL_KEYS: dict[str, set[str]] = {}
for _key, _item in CONTRACT.items():
    for _rule_id in _item.rule_ids:
        RULE_LEGAL_KEYS.setdefault(_rule_id, set()).add(_key)

_KIND_TO_KEYS: dict[str, set[str]] = {}
for _key, _item in CONTRACT.items():
    for _kind in _item.finding_kinds:
        _KIND_TO_KEYS.setdefault(_kind, set()).add(_key)


def finding_kind_to_legal_keys(kind: str) -> set[str]:
    return set(_KIND_TO_KEYS.get(kind) or ())


def apply_completions(runtime: dict, tokens: list[str] | tuple[str, ...]) -> None:
    """Mark recognition items complete only via registered completion tokens."""
    token_set = {str(token) for token in tokens if token}
    completed = set(runtime.get("scenario_completed_items") or [])
    for key, item in CONTRACT.items():
        if token_set & set(item.complete_if):
            completed.add(key)
    runtime["scenario_completed_items"] = sorted(completed)
    coverage = dict(runtime.get("scenario_coverage") or {})
    rows = [dict(row) for row in coverage.get("items") or []]
    for row in rows:
        if row.get("item") in completed and row.get("state") != "evidence_observed":
            row["state"] = "evidence_observed"
            row["state_label"] = "已形成设备证据"
            row["reason"] = "已取得该场景对应的设备侧观察证据"
    if rows:
        terminal = {"evidence_observed", "blocked_external", "requires_login", "requires_server_audit", "not_applicable"}
        coverage.update({
            "items": rows,
            "completed": sum(row.get("state") == "evidence_observed" for row in rows),
            "completed_items": sorted(completed),
            "remaining_items": [str(row.get("item")) for row in rows if str(row.get("state") or "pending") not in terminal],
            "remaining": sum(str(row.get("state") or "pending") not in terminal for row in rows),
        })
        runtime["scenario_coverage"] = coverage


def completion_allowed(legal_key: str, *, evidence_source: str = "", finding_kind: str | None = None) -> bool:
    item = CONTRACT.get(str(legal_key))
    if item is None or not item.complete_if:
        return False
    tokens = {str(evidence_source or ""), str(finding_kind or "")}
    return bool(tokens & set(item.complete_if))
