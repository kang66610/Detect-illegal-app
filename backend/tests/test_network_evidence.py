import json
from types import SimpleNamespace

from agent.detection_engines.network_evidence import build_network_evidence, normalize_url


def test_network_evidence_strips_queries_and_correlates_preceding_sensitive_api(tmp_path):
    events = [
        {"type": "api", "time": 1000, "data_type": "设备标识信息", "api": "getImei"},
        {"type": "url", "time": 2500, "url": "https://track.example.com/collect?imei=secret#x", "stack": "com.umeng.analytics.Agent.send"},
    ]
    ctx = SimpleNamespace(data_dir=tmp_path, cfg={"network": {"third_party_domains": ["example.com"], "overseas_domains": []}})

    evidence = build_network_evidence(ctx, events, ["sdk_upload_undisclosed"])
    payload = json.loads((tmp_path / "traffic" / "network-events.json").read_text(encoding="utf-8"))

    assert normalize_url(events[1]["url"]) == "https://track.example.com/collect"
    assert payload["events"][0]["preceding_data_types"] == ["设备标识信息"]
    assert "secret" not in json.dumps(payload, ensure_ascii=False)
    assert evidence["type"] == "traffic"


def test_network_evidence_keeps_only_login_field_names_not_values(tmp_path):
    events = [{
        "type": "url", "time": 1, "url": "http://api.example.com/login",
        "transport": "http", "method": "POST",
        "credential_fields": ["username", "password"], "authorization_present": False,
    }]
    ctx = SimpleNamespace(data_dir=tmp_path, cfg={"network": {}})

    build_network_evidence(ctx, events, ["login_data_unprotected"])
    payload = json.loads((tmp_path / "traffic" / "network-events.json").read_text(encoding="utf-8"))

    assert payload["events"][0]["credential_fields"] == ["password", "username"]
    assert payload["events"][0]["transport"] == "http"
