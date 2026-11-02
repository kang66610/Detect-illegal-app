import sys
from types import SimpleNamespace

import pytest

from agent.common.exceptions import EngineUnavailableError
from agent.detection_engines.frida_monitor import (
    FridaMonitorEngine,
    _manual_consent_code_request_url,
    _policy_discloses_sdk_data,
)


class _DestroyedScript:
    def unload(self):
        raise RuntimeError("script is destroyed")


class _DetachedSession:
    def detach(self):
        raise RuntimeError("session is detached")


class _ServerUnavailableDevice:
    id = "emulator-5554"
    name = "Android Emulator 5554"

    def enumerate_processes(self):
        raise RuntimeError("unable to connect to remote frida-server: closed")

    def spawn(self, _target):
        raise AssertionError("server 预检失败后不得继续 spawn")


class _FakeFrida:
    def __init__(self, device):
        self.device = device

    def get_device(self, _device_id, timeout):
        assert timeout == 5000
        return self.device


class _ReadyScript:
    def on(self, *_args):
        return None

    def load(self):
        return None

    def unload(self):
        return None


class _ReadySession:
    def create_script(self, _source):
        return _ReadyScript()

    def detach(self):
        return None


class _ReadyDevice:
    id = "emulator-5554"
    name = "Android Emulator 5554"

    def enumerate_processes(self):
        return []

    def query_system_parameters(self):
        return {"access": "full"}

    def spawn(self, _target):
        return 123

    def attach(self, _target):
        return _ReadySession()

    def resume(self, _target):
        return None


class _RunningProcess:
    pid = 456
    name = "com.example.demo"
    identifier = "com.example.demo"


class _SpawnTimeoutDevice(_ReadyDevice):
    def spawn(self, _target):
        raise TimeoutError("Frida 操作超过 2 秒未返回")

    def enumerate_processes(self):
        return [_RunningProcess()]


class _FridaController:
    def __init__(self, available=True):
        self.available = available
        self.calls = []

    def ensure_frida_server(self, path, timeout):
        self.calls.append((path, timeout))
        return self.available


def test_monitor_stop_tolerates_destroyed_remote_objects():
    """A target process exiting during cleanup must not fail the whole task."""
    monitor = FridaMonitorEngine()
    monitor._script = _DestroyedScript()
    monitor._session = _DetachedSession()

    result = monitor.stop(SimpleNamespace(cfg={"frida": {"monitor_seconds": 0}}), save=False)

    assert result.findings == []
    assert monitor._script is None
    assert monitor._session is None


def test_monitor_fails_fast_when_frida_server_is_unavailable(tmp_path, monkeypatch):
    """ADB device discovery alone is insufficient: verify frida-server first."""
    monkeypatch.setitem(sys.modules, "frida", _FakeFrida(_ServerUnavailableDevice()))
    ctx = SimpleNamespace(
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"frida": {"device_id": "emulator-5554", "spawn_target": True, "monitor_seconds": 0}},
        data_dir=tmp_path,
    )

    with pytest.raises(EngineUnavailableError, match="Frida Server 未运行"):
        FridaMonitorEngine().start(ctx)

    event_types = {path.name.split("-", 2)[-1].removesuffix(".json") for path in (tmp_path / "timeline").glob("*.json")}
    assert {"connecting", "device_connected", "server_health_check", "server_unavailable", "monitor_failed"} <= event_types


def test_monitor_ensures_root_frida_server_before_spawn(tmp_path, monkeypatch):
    controller = _FridaController()
    monkeypatch.setitem(sys.modules, "frida", _FakeFrida(_ReadyDevice()))
    ctx = SimpleNamespace(
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={
            "appium": {"udid": "emulator-5554"},
            "frida": {
                "device_id": "emulator-5554", "spawn_target": True, "monitor_seconds": 0,
                "auto_start": True, "server_path": "/data/local/tmp/frida-server",
                "startup_timeout_seconds": 12, "operation_timeout_seconds": 2,
            },
        },
        data_dir=tmp_path,
    )

    FridaMonitorEngine(device_controller=controller).start(ctx)

    assert controller.calls == [("/data/local/tmp/frida-server", 12)]


def test_monitor_reports_a_bounded_spawn_timeout_instead_of_hanging(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "frida", _FakeFrida(_ReadyDevice()))
    monkeypatch.setattr(
        FridaMonitorEngine,
        "_call_with_timeout",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("Frida 操作超过 2 秒未返回"))),
    )
    ctx = SimpleNamespace(
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"frida": {"device_id": "emulator-5554", "spawn_target": True, "monitor_seconds": 0,
                       "operation_timeout_seconds": 2}},
        data_dir=tmp_path,
    )

    with pytest.raises(EngineUnavailableError, match="超过 2 秒"):
        FridaMonitorEngine().start(ctx)


def test_monitor_attaches_to_live_process_after_spawn_timeout(tmp_path, monkeypatch):
    """A live Appium-launched process is a valid bounded Frida fallback."""
    monkeypatch.setitem(sys.modules, "frida", _FakeFrida(_SpawnTimeoutDevice()))
    ctx = SimpleNamespace(
        apk=SimpleNamespace(package_name="com.example.demo"),
        cfg={"frida": {"device_id": "emulator-5554", "spawn_target": True,
                       "monitor_seconds": 0, "operation_timeout_seconds": 2}},
        data_dir=tmp_path,
    )

    monitor = FridaMonitorEngine()
    monitor.start(ctx)

    assert monitor._session is not None
    event_types = {path.name.split("-", 2)[-1].removesuffix(".json") for path in (tmp_path / "timeline").glob("*.json")}
    assert {"spawning", "spawn_failed", "spawn_fallback_attach", "monitor_started"} <= event_types


def test_monitor_only_flags_api_events_that_happened_before_recorded_consent(tmp_path):
    monitor = FridaMonitorEngine()
    monitor.events = [
        {"type": "api", "api": "android.telephony.TelephonyManager.getImei", "time": 100},
        {"type": "api", "api": "android.telephony.TelephonyManager.getDeviceId", "time": 300},
    ]
    ctx = SimpleNamespace(
        cfg={"frida": {"monitor_seconds": 0, "overseas_domains": []}},
        data_dir=tmp_path,
        runtime={"consent_timestamp_ms": 200},
    )

    result = monitor.stop(ctx)

    assert len(result.findings) == 1
    assert result.findings[0].kind == "api_called_before_consent"
    assert result.findings[0].payload["time"] == 100


def test_manual_login_consent_probe_correlates_only_a_nearby_code_request_url():
    observation = {
        "armed_at_ms": 1_000,
        "observed_at_ms": 2_000,
        "code_target": "com.demo:id/send_code",
    }
    events = [
        {"type": "url", "url": "https://api.example.test/v1/sendCode", "time": 1_500,
         "credential_fields": ["phone"]},
        {"type": "url", "url": "https://api.example.test/v1/profile", "time": 1_600,
         "credential_fields": []},
    ]

    matched = _manual_consent_code_request_url(events, observation)

    assert matched is not None
    assert matched["url"].endswith("/sendCode")


def test_monitor_emits_rule_3_1_candidate_only_after_manual_probe_and_request_trace(tmp_path):
    monitor = FridaMonitorEngine()
    monitor.events = [{
        "type": "url", "url": "https://api.example.test/auth/send_code", "time": 1_500,
        "credential_fields": ["phone"], "stack": "demo",
    }]
    ctx = SimpleNamespace(
        apk=SimpleNamespace(package_name="com.example.demo", sdk_list=[]),
        cfg={"frida": {"monitor_seconds": 0, "overseas_domains": []}, "network": {}},
        data_dir=tmp_path,
        runtime={
            "probe_profile": "deny",
            "manual_auth_consent_code_request_observations": [{
                "probe_profile": "deny", "armed_at_ms": 1_000, "observed_at_ms": 2_000,
                "checkbox_target": "agree", "code_target": "send_code",
            }],
        },
    )

    result = monitor.stop(ctx)

    finding = next(item for item in result.findings if item.kind == "api_called_before_consent")
    assert finding.payload["manual_trigger"] is True
    assert finding.payload["consent_scope"] == "login_terms_checkbox"


def test_monitor_reports_repeated_sensitive_api_collection(tmp_path):
    monitor = FridaMonitorEngine()
    monitor.events = [{"type": "api", "api": "android.location.LocationManager.requestLocationUpdates", "time": 300} for _ in range(5)]
    ctx = SimpleNamespace(
        cfg={"frida": {"monitor_seconds": 0, "overseas_domains": []}},
        data_dir=tmp_path,
        runtime={"consent_timestamp_ms": 1},
    )

    result = monitor.stop(ctx)

    frequent = next(finding for finding in result.findings if finding.kind == "frequent_collection")
    assert frequent.category == 4
    assert frequent.payload["count"] == 5


def test_monitor_flags_sdk_identifier_collection_not_disclosed_in_completed_policy(tmp_path):
    monitor = FridaMonitorEngine()
    monitor.events = [{
        "type": "api", "api": "android.telephony.TelephonyManager.getSubscriberId", "time": 300,
        "stack": "com.iflytek.cloud.SpeechUtility.init(SpeechUtility.java:1)",
    }]
    ctx = SimpleNamespace(
        cfg={"frida": {"monitor_seconds": 0, "overseas_domains": []}},
        data_dir=tmp_path,
        apk=SimpleNamespace(policy_raw=None),
        runtime={"consent_timestamp_ms": 1, "privacy_policy_read_complete": True, "policy_document_read_complete": True,
                 "policy_text": "讯飞SDK仅用于语音识别，将收集麦克风和语音内容。"},
    )

    result = monitor.stop(ctx)

    finding = next(item for item in result.findings if item.kind == "sdk_collection_not_disclosed")
    assert finding.payload["sdk"] == "讯飞语音"
    assert finding.payload["data_type"] == "IMSI"


def test_sdk_disclosure_requires_sdk_and_data_facets_in_the_same_policy_section():
    policy = """
    讯飞语音 SDK：用于语音识别，通过麦克风收集音频信息。
    其他服务：为了保障安全，我们可能收集设备信息、IMEI 和 IMSI。
    """

    assert _policy_discloses_sdk_data(policy, "讯飞语音", "设备标识信息") is False


def test_sdk_disclosure_requires_purpose_method_and_data_scope_in_its_section():
    complete = "讯飞语音 SDK：为了提供语音识别服务，将通过调用设备接口收集设备标识信息（IMEI、IMSI）。"
    missing_purpose = "讯飞语音 SDK：通过调用设备接口收集设备标识信息（IMEI、IMSI）。"

    assert _policy_discloses_sdk_data(complete, "讯飞语音", "设备标识信息") is True
    assert _policy_discloses_sdk_data(missing_purpose, "讯飞语音", "设备标识信息") is False


def test_aliyun_feedback_imsi_is_not_covered_by_generic_device_id_language():
    policy = "阿里云用户反馈 SDK：为了处理用户意见，将通过调用系统接口收集设备标识信息。"
    disclosed = "阿里云用户反馈 SDK：为了处理用户意见，将通过调用系统接口收集IMSI。"

    assert _policy_discloses_sdk_data(policy, "阿里云用户反馈", "IMSI") is False
    assert _policy_discloses_sdk_data(disclosed, "阿里云用户反馈", "IMSI") is True


def test_monitor_flags_aliyun_feedback_imsi_when_policy_omits_it(tmp_path):
    monitor = FridaMonitorEngine()
    monitor.events = [{
        "type": "api", "api": "android.telephony.TelephonyManager.getSubscriberId", "time": 300,
        "stack": "com.alibaba.sdk.android.feedback.impl.FeedbackAPI.init\ncom.ta.utdid2.device.UTDevice.getUtdid",
    }]
    ctx = SimpleNamespace(
        cfg={"frida": {"monitor_seconds": 0, "overseas_domains": []}},
        data_dir=tmp_path,
        apk=SimpleNamespace(policy_raw=None),
        runtime={
            "consent_timestamp_ms": 1,
            "privacy_policy_read_complete": True,
            "policy_document_read_complete": True,
            "policy_text": "阿里云用户反馈SDK用于收集用户意见，将获取设备标识信息。",
        },
    )

    result = monitor.stop(ctx)

    finding = next(item for item in result.findings if item.kind == "sdk_collection_not_disclosed")
    assert finding.payload["sdk"] == "阿里云用户反馈"
    assert finding.payload["data_type"] == "IMSI"


def test_unknown_sdk_imsi_collection_is_still_flagged(tmp_path):
    monitor = FridaMonitorEngine()
    monitor.events = [{
        "type": "api", "api": "android.telephony.TelephonyManager.getSubscriberId", "time": 300,
        "stack": "com.unknown.analytics.DeviceId.getSubscriberId(DeviceId.java:8)",
    }]
    ctx = SimpleNamespace(
        cfg={"frida": {"monitor_seconds": 0, "overseas_domains": []}},
        data_dir=tmp_path,
        apk=SimpleNamespace(policy_raw=None, package_name="com.example.demo", sdk_list=[]),
        runtime={
            "consent_timestamp_ms": 1,
            "privacy_policy_read_complete": True,
            "policy_document_read_complete": True,
            "policy_text": "我们收集账号用于登录，未说明任何第三方 SDK。",
        },
    )

    result = monitor.stop(ctx)

    finding = next(item for item in result.findings if item.kind == "sdk_collection_not_disclosed")
    assert finding.payload["sdk_known"] is False
    assert "com.unknown.analytics" in finding.payload["sdk"]


def test_monitor_sanitizes_url_before_it_reaches_any_evidence_file():
    monitor = FridaMonitorEngine()
    monitor._on_message({"type": "send", "payload": {
        "type": "url", "url": "https://api.example.com/collect?phone=13800000000#token", "time": 1,
    }}, None)
    assert monitor.events[0]["url"] == "https://api.example.com/collect"


def test_monitor_flags_observed_http_login_fields_without_storing_values(tmp_path):
    monitor = FridaMonitorEngine()
    monitor.events = [{
        "type": "url", "url": "http://api.example.com/login", "transport": "http",
        "method": "POST", "credential_fields": ["username", "password"], "time": 300,
    }]
    ctx = SimpleNamespace(
        cfg={"frida": {"monitor_seconds": 0, "overseas_domains": []}},
        data_dir=tmp_path, runtime={"consent_timestamp_ms": 1},
    )

    result = monitor.stop(ctx)

    finding = next(item for item in result.findings if item.kind == "login_data_unprotected")
    assert finding.payload["transport"] == "http"
    assert finding.payload["credential_fields"] == ["password", "username"]
    artifact = (tmp_path / "traffic" / "network-events.json").read_text(encoding="utf-8")
    assert "secret" not in artifact


def test_https_login_request_is_not_reported_as_unprotected(tmp_path):
    monitor = FridaMonitorEngine()
    monitor.events = [{
        "type": "url", "url": "https://api.example.com/login", "transport": "https",
        "method": "POST", "credential_fields": ["password"], "time": 300,
    }]
    ctx = SimpleNamespace(
        cfg={"frida": {"monitor_seconds": 0, "overseas_domains": []}},
        data_dir=tmp_path, runtime={"consent_timestamp_ms": 1},
    )

    result = monitor.stop(ctx)

    assert "login_data_unprotected" not in {item.kind for item in result.findings}
