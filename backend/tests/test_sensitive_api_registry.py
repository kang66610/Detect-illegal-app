from agent.detection_engines.sensitive_api_registry import (
    build_hook_script,
    load_sensitive_api_registry,
    resolve_data_type,
)


def test_registry_covers_high_value_sensitive_android_surfaces():
    entries = load_sensitive_api_registry()
    methods = {(item["class_name"], item["method_name"]) for item in entries}
    ids = {item["id"] for item in entries}

    assert ("android.provider.Settings$Secure", "getString") in methods
    assert ("android.content.ClipboardManager", "getPrimaryClip") in methods
    assert ("android.content.pm.PackageManager", "getInstalledPackages") in methods
    assert ("android.location.LocationManager", "getLastKnownLocation") in methods
    assert ("android.media.AudioRecord", "startRecording") in methods
    assert ("android.telephony.TelephonyManager", "getMeid") in methods
    assert "ads.advertising_id" in ids
    assert "content.query" in ids
    query = next(item for item in entries if item["id"] == "content.query")
    contains = query["argument_filter"]["contains_any"]
    assert "contacts" in contains and "media" in contains and "sms" in contains


def test_generated_hook_script_emits_metadata_but_not_sensitive_return_values():
    script = build_hook_script(load_sensitive_api_registry())

    assert "android.provider.Settings$Secure" in script
    assert "contains_any" in script
    assert "contacts" in script
    assert "native_load" in script
    assert "loadLibrary" in script
    assert "return_value" not in script
    assert "raw_args" not in script
    assert "registry_id" in script
    assert "credential_fields" in script
    assert "buffer.readUtf8()" in script
    assert "password_value" not in script


def test_data_type_is_resolved_from_registry_id_not_fragile_substring_rules():
    assert resolve_data_type("device.android_id") == "设备标识信息"
    assert resolve_data_type("device.subscriber_id") == "IMSI"
    assert resolve_data_type("location.last_known") == "位置信息"
    assert resolve_data_type("unknown") is None
