import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from agent.detection_engines.base import Finding
from agent.rule_engine.behavior_evidence import (
    build_declaration_actual_matrix,
    correlate_behavior_events,
    enrich_behavior_evidence,
)


def test_sensitive_event_is_bound_to_nearest_page_and_action_only_within_window():
    base = datetime(2026, 8, 17, 8, 0, 0)
    records = [
        {"time": (base - timedelta(seconds=2)).isoformat(), "source": "appium", "event_type": "page_observed", "page": "HomeKT"},
        {"time": (base - timedelta(seconds=1)).isoformat(), "source": "appium", "event_type": "action_completed", "action": "click: location"},
        {"time": (base - timedelta(minutes=2)).isoformat(), "source": "appium", "event_type": "page_observed", "page": "OldKT"},
    ]
    events = [{"type": "api", "registry_id": "location.last_known", "observed_at": base.isoformat()}]

    rows = correlate_behavior_events(events, records, max_delta_seconds=15)

    assert rows[0]["page"] == "HomeKT"
    assert rows[0]["action"] == "click: location"
    assert rows[0]["chain_complete"] is True


def test_declaration_actual_matrix_reports_sdk_actor_data_and_disclosure_state():
    rows = build_declaration_actual_matrix(
        "讯飞语音 SDK：为了提供语音识别，通过麦克风收集音频信息。",
        [{
            "type": "api", "registry_id": "device.subscriber_id", "data_type": "设备标识信息",
            "sdk": "讯飞语音", "api": "TelephonyManager.getSubscriberId", "chain_complete": True,
        }],
    )

    assert rows == [{
        "actor": "讯飞语音", "data_type": "设备标识信息", "disclosed": False,
        "observed": True, "chain_complete": True, "apis": ["TelephonyManager.getSubscriberId"], "event_count": 1,
    }]


def test_enrichment_creates_scoped_ledger_and_matrix_evidence(tmp_path):
    timeline = tmp_path / "timeline"
    timeline.mkdir()
    at = datetime.utcnow()
    (timeline / "page.json").write_text(json.dumps({
        "time": (at - timedelta(seconds=1)).isoformat(), "source": "appium",
        "event_type": "page_observed", "page": "PrivacyKT",
    }), encoding="utf-8")
    callstack = tmp_path / "callstack" / "frida-events.json"
    callstack.parent.mkdir()
    callstack.write_text(json.dumps({"events": [{
        "type": "api", "api": "TelephonyManager.getSubscriberId",
        "registry_id": "device.subscriber_id", "data_type": "设备标识信息",
        "sdk": "讯飞语音", "observed_at": at.isoformat(),
    }]}), encoding="utf-8")
    finding = Finding(kind="sdk_collection_not_disclosed", category=2, payload={
        "registry_id": "device.subscriber_id", "sdk": "讯飞语音", "data_type": "设备标识信息",
    })
    ctx = SimpleNamespace(
        data_dir=tmp_path, runtime={"policy_text": "讯飞语音 SDK：用于语音服务。"},
        apk=SimpleNamespace(policy_raw=None),
    )

    additions, gaps = enrich_behavior_evidence(ctx, [finding], [{"type": "callstack", "path": str(callstack), "meta": {}}])

    assert gaps == []
    assert {item["type"] for item in additions} == {"behavior_ledger", "consistency_matrix"}
    assert all("sdk_collection_not_disclosed" in item["meta"]["finding_kinds"] for item in additions)
