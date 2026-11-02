"""Known manual findings are regression baselines, never synthetic findings."""
from __future__ import annotations


BASELINES = {
    "com.example.travel": {
        "name": "案例C人工检测基准",
        # These four findings are the reviewed regression baseline for the
        # supplied 案例C manual report.  They are not injected into an
        # automatic report: a missing item remains a visible false negative.
        "expected_rule_ids": {
            "RULE_2_1_SDK",
            "RULE_2_2",
            "RULE_4_1_CONSENT",
            "RULE_4_2",
        },
        "expected_timeline_paths": [[
            ("document_read_complete", "external_document_read_complete"),
            ("privacy_consent_clicked",),
            ("permission_prompt_without_purpose",),
            ("permission_denial_business_action_retried",),
            ("permission_denial_function_blocked",),
        ]],
    },
    "com.example.socialsecurity": {
        "name": "案例S人工检测基准",
        "expected_rule_ids": {
            "RULE_1_1",
            "RULE_3_1",
            "RULE_3_2",
        },
    },
    "com.example.reader": {
        "name": "案例K人工检测基准",
        "expected_rule_ids": {
            "RULE_4_2",
            "RULE_3_8",
            "RULE_2_1_SDK",
        },
    },
    "com.example.writer": {
        "name": "案例G人工检测基准",
        # The manual report contains a duplicate 2.1 description plus 2.3
        # and 6.5 findings.  Baseline recall uses distinct legal rules, so a
        # duplicate paragraph cannot inflate or hide the regression metric.
        "expected_rule_ids": {
            "RULE_2_1",
            "RULE_2_2",
            "RULE_6_5",
        },
    },
    "com.example.flowers": {
        "name": "案例H人工检测基准",
        "expected_rule_ids": {
            "RULE_2_1_SDK",
            "RULE_EXT_SENSITIVE_MARK",
            "RULE_EXT_LOGIN_DATA_PROTECTION",
        },
        "expected_timeline_paths": [[
            ("document_read_complete", "external_document_read_complete"),
            ("privacy_hub_entered", "privacy_hub_target_selected"),
            ("login_invitation_followed", "awaiting_manual_login"),
            ("permission_prompt_without_purpose",),
        ]],
    },
}


def _baseline_for(package_name: str | None, catalog=None) -> dict | None:
    if catalog is None:
        try:
            from agent.rule_engine.manual_baseline_import import default_manual_baseline_catalog
            catalog = default_manual_baseline_catalog()
        except (FileNotFoundError, ValueError, OSError):
            catalog = None
    imported = catalog.baseline_for_package(package_name or "") if catalog is not None else None
    return imported or BASELINES.get(package_name or "")


def compare_manual_baseline(
    package_name: str | None, detected_rule_ids: set[str], *, catalog=None,
) -> dict | None:
    baseline = _baseline_for(package_name, catalog)
    if not baseline:
        return None
    expected = set(baseline["expected_rule_ids"])
    true_positive = expected & detected_rule_ids
    missing = expected - detected_rule_ids
    unexpected = detected_rule_ids - expected
    return {
        "name": baseline["name"], "expected": sorted(expected), "detected": sorted(detected_rule_ids),
        "true_positive": sorted(true_positive), "false_negative": sorted(missing),
        "additional_findings": sorted(unexpected),
        "recall": len(true_positive) / len(expected) if expected else 1.0,
    }


def compare_timeline_baseline(package_name: str | None, events: list[dict], *, catalog=None) -> dict | None:
    """Check ordered milestone paths without injecting app-name rules into traversal."""
    baseline = _baseline_for(package_name, catalog)
    paths = list((baseline or {}).get("expected_timeline_paths") or [])
    if not paths:
        return None
    observed = [str((row.get("meta") or row).get("event_type") or "") for row in events]
    results = []
    for path in paths:
        cursor = 0
        missing = []
        matched = []
        for alternatives in path:
            found = next(
                (index for index in range(cursor, len(observed)) if observed[index] in set(alternatives)),
                None,
            )
            if found is None:
                missing.append(list(alternatives))
            else:
                matched.append(observed[found])
                cursor = found + 1
        results.append({"matched": matched, "missing": missing, "passed": not missing})
    return {"name": baseline["name"], "paths": results, "passed": all(row["passed"] for row in results)}
