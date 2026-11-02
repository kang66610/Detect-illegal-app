import xml.etree.ElementTree as ET
import zipfile

from agent.detection_engines import static_analyzer
from agent.detection_engines.sdk_detector import detect_sdks, identify_sdk_from_stack


class _FakeAxml:
    def __init__(self, root):
        self.root = root

    def get_xml_obj(self):
        return self.root


class _FakeApk:
    def __init__(self, path):
        self.path = path
        self.root = ET.fromstring(
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
            '<uses-sdk android:minSdkVersion="23" android:targetSdkVersion="35" />'
            '<application android:debuggable="true" android:allowBackup="false" '
            'android:usesCleartextTraffic="true" android:networkSecurityConfig="@xml/network_security_config">'
            '<activity android:name=".MainActivity" android:exported="true" />'
            '<meta-data android:name="UMENG_APPKEY" android:value="demo" />'
            '</application></manifest>'
        )

    def is_valid_APK(self):
        return True

    def get_android_manifest_axml(self):
        return _FakeAxml(self.root)

    def get_permissions(self):
        return ["android.permission.READ_PHONE_STATE"]

    def get_files(self):
        with zipfile.ZipFile(self.path) as archive:
            return archive.namelist()

    def get_file(self, name):
        with zipfile.ZipFile(self.path) as archive:
            return archive.read(name)

    def get_app_name(self):
        return "演示应用"

    def get_package(self):
        return "com.example.demo"

    def get_androidversion_name(self):
        return "1.0"

    def is_signed_v1(self):
        return True

    def is_signed_v2(self):
        return False

    def is_signed_v3(self):
        return False

    def get_certificates_der_v2(self):
        return []

    def get_certificates_der_v3(self):
        return []


def test_detect_sdks_by_meta_and_permissions():
    meta = {
        "com.amap.api.v2.apikey": "dummy",
        "UMENG_APPKEY": "dummy",
    }
    sdks = detect_sdks(meta, ["android.permission.ACCESS_FINE_LOCATION"])
    names = {s["name"] for s in sdks}
    assert "高德地图" in names
    assert "友盟" in names


def test_detect_sdks_empty_when_nothing_matches():
    assert detect_sdks({}, []) == []


def test_detects_iflytek_from_dex_package_marker_without_manifest_metadata():
    sdks = detect_sdks({}, [], ["com.iflytek.cloud"])

    assert sdks == [{
        "name": "讯飞语音", "collected": ["语音数据", "设备标识信息"],
        "matched_by": ["DEX:com.iflytek.cloud"], "known": True,
    }]


def test_identifies_sharesdk_from_java_stack():
    sdk = identify_sdk_from_stack(
        "cn.sharesdk.framework.a.c.d(Protocols.java:475)\n"
        "cn.fly.tools.network.NetworkHelper.httpPostNew",
        app_package="com.example.flowers",
    )
    assert sdk["name"] == "ShareSDK"
    assert sdk["known"] is True


def test_identifies_aliyun_feedback_sdk_from_java_stack():
    sdk = identify_sdk_from_stack(
        "com.alibaba.sdk.android.feedback.impl.FeedbackAPI.init(FeedbackAPI.java:1)\n"
        "com.ta.utdid2.device.UTDevice.getUtdid"
    )

    assert sdk["name"] == "阿里云用户反馈"
    assert "IMSI" in sdk["collected"]


def test_unknown_third_party_stack_is_clustered_instead_of_dropped():
    sdk = identify_sdk_from_stack(
        "com.unknown.analytics.Tracker.getSubscriberId(Tracker.java:12)",
        app_package="com.example.demo",
    )

    assert sdk["known"] is False
    assert sdk["package"] == "com.unknown.analytics"
    assert "第三方SDK" in sdk["name"]


def test_app_and_android_framework_stacks_are_not_sdks():
    assert identify_sdk_from_stack(
        "android.telephony.TelephonyManager.getSubscriberId",
        app_package="com.example.demo",
    ) is None
    assert identify_sdk_from_stack(
        "com.example.demo.MainActivity.onCreate(MainActivity.java:1)",
        app_package="com.example.demo",
    ) is None


def test_basic_static_analysis_collects_manifest_dex_network_signature_and_native_features(tmp_path, monkeypatch):
    apk_path = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk_path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"binary axml placeholder")
        archive.writestr(
            "classes.dex",
            b"dex\nhttp://api.example.com/v1\ngetDeviceId\ncom/umeng/analytics",
        )
        archive.writestr("assets/privacy_policy.txt", "隐私政策示例")
        archive.writestr("lib/arm64-v8a/libdemo.so", b"ELF\x00https://native.example.com")
        archive.writestr("META-INF/CERT.RSA", b"not-a-real-certificate")

    monkeypatch.setattr(static_analyzer, "APK", _FakeApk)
    result = static_analyzer.analyze_apk(apk_path)
    summary = result["static_summary"]

    assert result["app_name"] == "演示应用"
    assert len(result["sha256"]) == 64
    assert result["policy_raw"] == "隐私政策示例"
    assert summary["analysis_version"] == "basic-2"
    assert summary["manifest"]["target_sdk"] == 35
    assert summary["manifest"]["debuggable"] is True
    assert summary["manifest"]["uses_cleartext_traffic"] is True
    assert summary["manifest"]["exported_components"] == 1
    assert summary["native"]["abis"] == ["arm64-v8a"]
    assert "api.example.com" in summary["url_domains"]
    assert "native.example.com" in summary["url_domains"]
    assert any(item["marker"] == "getDeviceId" for item in summary["sensitive_api_markers"])
    assert summary["signature"]["schemes"]["v1"] is True
    assert any(item["rule_id"] == "manifest.debuggable" for item in summary["indicators"])
    assert any(sdk["name"] == "友盟" for sdk in result["sdk_list"])


def test_binary_scan_is_bounded_per_entry(tmp_path):
    apk_path = tmp_path / "large.apk"
    payload = b"A" * (static_analyzer._MAX_ENTRY_SCAN_BYTES + 100)
    with zipfile.ZipFile(apk_path, "w") as archive:
        archive.writestr("classes.dex", payload)

    result = static_analyzer._extract_binary_indicators(
        apk_path,
        [{"name": "classes.dex", "size_bytes": len(payload)}],
    )

    assert result["bytes_scanned"] == static_analyzer._MAX_ENTRY_SCAN_BYTES
    assert result["truncated_files"] == ["classes.dex"]
