"""上传阶段使用的快速、确定性 APK 静态分析。"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from agent.common.policy_text import is_valid_policy_text

from androguard.core.apk import APK

from agent.common.exceptions import ApkParseError
from agent.detection_engines.sdk_detector import detect_sdks

STATIC_ANALYSIS_VERSION = "basic-2"
_ANDROID_NS = "http://schemas.android.com/apk/res/android"
_MAX_ENTRY_SCAN_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_SCAN_BYTES = 32 * 1024 * 1024
_MAX_URLS = 300

_POLICY_KEYWORDS = ["privacy", "policy", "隐私", "政策", "agreement", "用户协议"]
DANGEROUS_PERMISSIONS = {
    "android.permission.ACCESS_FINE_LOCATION": "精确定位",
    "android.permission.ACCESS_COARSE_LOCATION": "粗略定位",
    "android.permission.READ_CONTACTS": "通讯录读取",
    "android.permission.WRITE_CONTACTS": "通讯录写入",
    "android.permission.RECORD_AUDIO": "麦克风",
    "android.permission.CAMERA": "相机",
    "android.permission.READ_EXTERNAL_STORAGE": "存储读取",
    "android.permission.WRITE_EXTERNAL_STORAGE": "存储写入",
    "android.permission.READ_PHONE_STATE": "设备标识",
    "android.permission.READ_SMS": "短信读取",
    "android.permission.SEND_SMS": "短信发送",
    "android.permission.CALL_LOG": "通话记录",
    "android.permission.READ_CALL_LOG": "通话记录读取",
    "android.permission.PROCESS_OUTGOING_CALLS": "处理去电",
    "android.permission.READ_CALENDAR": "日历读取",
    "android.permission.BODY_SENSORS": "身体传感器",
    "android.permission.ACTIVITY_RECOGNITION": "运动状态",
}

_URL_RE = re.compile(rb"(?i)\b(?:https?|wss?)://[^\x00-\x20\"'<>]+")
_PRINTABLE_RE = re.compile(rb"[\x20-\x7e]{4,}")
_SCAN_SUFFIXES = {
    ".dex", ".so", ".xml", ".json", ".txt", ".html", ".js",
    ".properties", ".kt", ".java", ".smali", ".bin", ".dat",
}
_SENSITIVE_API_MARKERS = {
    "getDeviceId": "设备标识",
    "getImei": "设备标识",
    "getMeid": "设备标识",
    "getSubscriberId": "设备标识",
    "getLine1Number": "电话号码",
    "Settings$Secure": "设备标识",
    "ANDROID_ID": "设备标识",
    "getLastKnownLocation": "定位",
    "LocationManager": "定位",
    "Camera.open": "相机",
    "AudioRecord": "麦克风",
    "MediaRecorder": "麦克风",
    "getMacAddress": "网络标识",
    "AdvertisingIdClient": "广告标识",
    "ClipboardManager": "剪贴板",
}
_COMPONENT_TAGS = {"activity", "activity-alias", "service", "receiver", "provider"}


def analyze_apk(apk_path: Path) -> dict:
    """解析 APK 基本信息和快速静态特征。失败抛 ApkParseError。"""
    try:
        apk = APK(str(apk_path))
    except Exception as e:
        raise ApkParseError(f"APK 解析失败（可能已加固或文件损坏）：{type(e).__name__}") from e
    if not apk.is_valid_APK():
        raise ApkParseError("APK 解析失败（可能已加固或文件损坏）：AndroidManifest 无效")

    permissions = apk.get_permissions() or []
    manifest_meta = _extract_meta(apk)
    archive = _inspect_zip(apk_path)
    manifest = _extract_manifest_features(apk)
    binary = _extract_binary_indicators(apk_path, archive["dex_files"])
    signature = _inspect_signatures(apk_path, archive["signature_files"], apk)
    native_libs = archive["native_libs"]
    static_summary = {
        "analysis_version": STATIC_ANALYSIS_VERSION,
        "archive": {
            "file_count": archive["file_count"],
            "compressed_bytes": archive["compressed_bytes"],
            "uncompressed_bytes": archive["uncompressed_bytes"],
            "dex_files": archive["dex_files"],
            "resource_file_count": archive["resource_file_count"],
            "asset_file_count": archive["asset_file_count"],
            "signature_files": signature["files"],
        },
        "manifest": manifest,
        "dex": binary["dex"],
        "urls": binary["urls"],
        "url_domains": binary["url_domains"],
        "sensitive_api_markers": binary["sensitive_api_markers"],
        "signature": signature,
        "native": {
            "count": len(native_libs),
            "abis": _native_abis(native_libs),
            "libraries": native_libs,
        },
        "scan": {
            "files_scanned": binary["files_scanned"],
            "bytes_scanned": binary["bytes_scanned"],
            "truncated_files": binary["truncated_files"],
        },
    }
    static_summary["indicators"] = _build_static_indicators(
        permissions, manifest, binary["urls"], binary["sensitive_api_markers"], signature,
    )
    return {
        "app_name": apk.get_app_name(),
        "package_name": apk.get_package(),
        "version_name": apk.get_androidversion_name(),
        "md5": _hash_of_file(apk_path, "md5"),
        "sha256": _hash_of_file(apk_path, "sha256"),
        "size_bytes": Path(apk_path).stat().st_size,
        "permissions": permissions,
        "permission_flags": {p: DANGEROUS_PERMISSIONS[p] for p in permissions if p in DANGEROUS_PERMISSIONS},
        "sdk_list": detect_sdks(manifest_meta, permissions, _extract_sdk_class_markers(apk)),
        "policy_raw": _extract_policy_text(apk),
        "meta": manifest_meta,
        "native_libs": native_libs,
        "static_summary": static_summary,
    }


def list_native_libs(apk_path: Path | None) -> list[str]:
    """Return packaged .so names without extracting or executing them."""
    if not apk_path:
        return []
    return _inspect_zip(Path(apk_path))["native_libs"]


def _inspect_zip(apk_path: Path) -> dict:
    result = {
        "file_count": 0,
        "compressed_bytes": 0,
        "uncompressed_bytes": 0,
        "dex_files": [],
        "native_libs": [],
        "signature_files": [],
        "resource_file_count": 0,
        "asset_file_count": 0,
    }
    if not apk_path or not Path(apk_path).is_file():
        return result
    try:
        with zipfile.ZipFile(apk_path) as archive:
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                if name.endswith("/"):
                    continue
                low = name.lower()
                result["file_count"] += 1
                result["compressed_bytes"] += max(0, info.compress_size)
                result["uncompressed_bytes"] += max(0, info.file_size)
                if re.fullmatch(r"classes\d*\.dex", Path(low).name):
                    result["dex_files"].append({"name": name, "size_bytes": info.file_size})
                if low.startswith("lib/") and low.endswith(".so"):
                    result["native_libs"].append(name)
                if low.startswith("meta-inf/") and low.endswith((".rsa", ".dsa", ".ec")):
                    result["signature_files"].append(name)
                if low.startswith("res/") or low == "resources.arsc":
                    result["resource_file_count"] += 1
                if low.startswith("assets/"):
                    result["asset_file_count"] += 1
    except (OSError, zipfile.BadZipFile):
        return result
    result["dex_files"] = sorted(result["dex_files"], key=lambda item: item["name"])
    result["native_libs"] = sorted(set(result["native_libs"]))
    result["signature_files"] = sorted(set(result["signature_files"]))
    return result


def _extract_binary_indicators(apk_path: Path, dex_inventory: list[dict]) -> dict:
    empty = {
        "dex": [], "urls": [], "url_domains": [], "sensitive_api_markers": [],
        "files_scanned": 0, "bytes_scanned": 0, "truncated_files": [],
    }
    if not apk_path or not Path(apk_path).is_file():
        return empty
    dex_by_name = {
        item["name"]: {**item, "urls": 0, "printable_strings": 0, "sensitive_markers": []}
        for item in dex_inventory
    }
    url_sources: dict[str, set[str]] = {}
    marker_sources: dict[str, set[str]] = {}
    files_scanned = 0
    bytes_scanned = 0
    truncated_files: list[str] = []
    try:
        with zipfile.ZipFile(apk_path) as archive:
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                low = name.lower()
                if name.endswith("/") or not _should_scan_entry(low):
                    continue
                if bytes_scanned >= _MAX_TOTAL_SCAN_BYTES:
                    break
                limit = min(_MAX_ENTRY_SCAN_BYTES, _MAX_TOTAL_SCAN_BYTES - bytes_scanned)
                try:
                    with archive.open(info) as stream:
                        raw = stream.read(limit + 1)
                except (OSError, zipfile.BadZipFile, RuntimeError):
                    continue
                if len(raw) > limit:
                    raw = raw[:limit]
                    truncated_files.append(name)
                files_scanned += 1
                bytes_scanned += len(raw)
                compact = raw.replace(b"\x00", b"")
                seen_urls: set[str] = set()
                for haystack in (raw, compact):
                    for match in _URL_RE.findall(haystack):
                        url = _normalise_url(match.decode("utf-8", errors="ignore"))
                        if url:
                            seen_urls.add(url)
                            url_sources.setdefault(url, set()).add(name)
                hits_for_dex: set[str] = set()
                lowered = compact.lower()
                for marker in _SENSITIVE_API_MARKERS:
                    if marker.lower().encode("utf-8") in lowered:
                        marker_sources.setdefault(marker, set()).add(name)
                        hits_for_dex.add(marker)
                if name in dex_by_name:
                    dex_by_name[name]["urls"] = len(seen_urls)
                    dex_by_name[name]["printable_strings"] = len(_PRINTABLE_RE.findall(raw))
                    dex_by_name[name]["sensitive_markers"] = sorted(hits_for_dex)
    except (OSError, zipfile.BadZipFile):
        return empty

    urls = sorted(url_sources)[:_MAX_URLS]
    markers = [
        {"marker": marker, "category": _SENSITIVE_API_MARKERS[marker], "files": sorted(files)}
        for marker, files in sorted(marker_sources.items())
    ]
    return {
        "dex": [dex_by_name[name] for name in sorted(dex_by_name)],
        "urls": [{"url": url, "files": sorted(url_sources[url])} for url in urls],
        "url_domains": sorted({domain for url in urls if (domain := _url_domain(url))}),
        "sensitive_api_markers": markers,
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
        "truncated_files": sorted(set(truncated_files)),
    }


def _should_scan_entry(name: str) -> bool:
    return Path(name).suffix.lower() in _SCAN_SUFFIXES or name.startswith("assets/")


def _normalise_url(value: str) -> str:
    value = value.strip().rstrip(".,;:!?)]}>。；，！？")[:2048]
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https", "ws", "wss"} or not parsed.netloc:
        return ""
    return value


def _url_domain(value: str) -> str:
    try:
        host = urlsplit(value).hostname
    except ValueError:
        return ""
    return (host or "").lower().rstrip(".")


def _native_abis(native_libs: list[str]) -> list[str]:
    result = set()
    for name in native_libs:
        parts = name.split("/")
        if len(parts) > 2 and parts[0] == "lib":
            result.add(parts[1])
    return sorted(result)


def _inspect_signatures(apk_path: Path, signature_files: list[str], apk: APK | None = None) -> dict:
    schemes = {
        name: _safe_signature_flag(apk, method)
        for name, method in (("v1", "is_signed_v1"), ("v2", "is_signed_v2"), ("v3", "is_signed_v3"))
    }
    result = {
        "signed": any(value is True for value in schemes.values()) or bool(signature_files),
        "schemes": schemes,
        "files": sorted(signature_files),
        "certificates": [],
    }
    if not apk_path or not Path(apk_path).is_file():
        return result
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.serialization import pkcs7
        from cryptography.x509 import load_der_x509_certificate
    except Exception:
        return result
    certificates: dict[str, dict] = {}

    def add_certificate(cert) -> None:
        fingerprint = cert.fingerprint(hashes.SHA256()).hex().upper()
        if fingerprint in certificates:
            return
        not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
        certificates[fingerprint] = {
            "sha256": fingerprint,
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
            "not_valid_after": not_after.isoformat(),
        }

    # V2/V3 证书位于 APK Signing Block，不会出现在 META-INF 中。
    if apk is not None:
        for method_name in ("get_certificates_der_v2", "get_certificates_der_v3"):
            try:
                blobs = getattr(apk, method_name)() or []
            except Exception:
                blobs = []
            for blob in blobs:
                try:
                    add_certificate(load_der_x509_certificate(blob))
                except Exception:
                    continue
    try:
        with zipfile.ZipFile(apk_path) as archive:
            for name in signature_files:
                try:
                    data = archive.read(name)
                except (KeyError, OSError, RuntimeError):
                    continue
                try:
                    certs = pkcs7.load_der_pkcs7_certificates(data) or []
                except Exception:
                    try:
                        certs = [load_der_x509_certificate(data)]
                    except Exception:
                        continue
                for cert in certs:
                    add_certificate(cert)
    except (OSError, zipfile.BadZipFile):
        return result
    result["certificates"] = list(certificates.values())
    return result


def _safe_signature_flag(apk: APK | None, method_name: str):
    if apk is None:
        return None
    try:
        return bool(getattr(apk, method_name)())
    except Exception:
        return None


def _build_static_indicators(permissions, manifest, urls, markers, signature) -> list[dict]:
    indicators: list[dict] = []
    if manifest.get("debuggable") is True:
        indicators.append({"rule_id": "manifest.debuggable", "severity": "high", "category": "配置", "evidence": "android:debuggable=true"})
    if manifest.get("uses_cleartext_traffic") is True:
        indicators.append({"rule_id": "manifest.cleartext_traffic", "severity": "medium", "category": "网络", "evidence": "android:usesCleartextTraffic=true"})
    if any(item["url"].lower().startswith("http://") for item in urls):
        indicators.append({"rule_id": "network.http_endpoint", "severity": "medium", "category": "网络", "evidence": "检测到明文 HTTP 地址"})
    for permission in sorted(p for p in permissions if p in DANGEROUS_PERMISSIONS):
        indicators.append({"rule_id": "permission." + permission.rsplit(".", 1)[-1], "severity": "info", "category": "权限", "evidence": f"{permission}（{DANGEROUS_PERMISSIONS[permission]}）"})
    for item in markers:
        indicators.append({"rule_id": "api." + item["marker"], "severity": "medium", "category": item["category"], "evidence": ", ".join(item["files"])})
    if signature.get("signed") is False:
        indicators.append({"rule_id": "signature.missing", "severity": "low", "category": "签名", "evidence": "未检测到 V1/V2/V3 APK 签名"})
    if manifest.get("exported_components", 0):
        indicators.append({"rule_id": "manifest.exported_components", "severity": "info", "category": "组件", "evidence": f"显式 exported 组件 {manifest['exported_components']} 个"})
    return indicators


def _manifest_root(apk: APK):
    try:
        xml = apk.get_android_manifest_axml()
        return xml.get_xml_obj() if hasattr(xml, "get_xml_obj") else None
    except Exception:
        return None


def _local_name(tag) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _android_attr(elem, name: str):
    return elem.get(f"{{{_ANDROID_NS}}}{name}") or elem.get(f"android:{name}") or elem.get(name)


def _parse_bool(value):
    if value is None or isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _parse_int(value):
    if value is None:
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _extract_manifest_features(apk: APK) -> dict:
    result = {
        "uses_cleartext_traffic": None,
        "network_security_config": None,
        "debuggable": None,
        "allow_backup": None,
        "min_sdk": None,
        "target_sdk": None,
        "component_counts": {tag: 0 for tag in sorted(_COMPONENT_TAGS)},
        "exported_components": 0,
    }
    root = _manifest_root(apk)
    if root is None:
        return result
    for elem in root.iter():
        tag = _local_name(elem.tag)
        if tag == "uses-sdk":
            result["min_sdk"] = _parse_int(_android_attr(elem, "minSdkVersion"))
            result["target_sdk"] = _parse_int(_android_attr(elem, "targetSdkVersion"))
        elif tag == "application":
            result["uses_cleartext_traffic"] = _parse_bool(_android_attr(elem, "usesCleartextTraffic"))
            result["network_security_config"] = _android_attr(elem, "networkSecurityConfig")
            result["debuggable"] = _parse_bool(_android_attr(elem, "debuggable"))
            result["allow_backup"] = _parse_bool(_android_attr(elem, "allowBackup"))
        elif tag in _COMPONENT_TAGS:
            result["component_counts"][tag] += 1
            if _parse_bool(_android_attr(elem, "exported")) is True:
                result["exported_components"] += 1
    return result


def _extract_meta(apk: APK) -> dict:
    """解析 AndroidManifest 中 application 下的 meta-data（SDK 特征识别输入）。"""
    meta = {}
    root = _manifest_root(apk)
    if root is None:
        return meta
    try:
        for elem in root.iter():
            if _local_name(elem.tag) == "meta-data":
                name = _android_attr(elem, "name")
                value = _android_attr(elem, "value")
                if name:
                    meta[name] = value
    except Exception:
        pass
    return meta


def _extract_policy_text(apk: APK) -> str | None:
    """在 assets 中查找隐私政策文本文件，返回原文（截断至 50KB）。"""
    for name in apk.get_files() or []:
        if any(k.lower() in name.lower() for k in _POLICY_KEYWORDS):
            try:
                text = apk.get_file(name).decode("utf-8", errors="replace")[:50000]
                if is_valid_policy_text(text):
                    return text
            except Exception:
                continue
    return None


def _extract_sdk_class_markers(apk: APK) -> list[str]:
    """在 DEX / 资源路径中查找已知 SDK 包前缀，不反编译或执行 APK。"""
    from agent.detection_engines.sdk_detector import _load_features

    prefixes = [prefix for feat in _load_features() for prefix in feat.get("package_prefixes", [])]
    if not prefixes:
        return []
    found: set[str] = set()
    try:
        files = apk.get_files() or []
    except Exception:
        files = []
    for name in files:
        lowered = str(name).replace("\\", "/").lower()
        for prefix in prefixes:
            if prefix.replace(".", "/").lower() in lowered:
                found.add(prefix)
        if not str(name).endswith(".dex"):
            continue
        try:
            raw = apk.get_file(name)
        except Exception:
            continue
        for prefix in prefixes:
            if prefix.replace(".", "/").encode() in raw or prefix.encode() in raw:
                found.add(prefix)
    return sorted(found)


def _hash_of_file(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def refresh_sdk_list_from_apk(
    apk_path: Path | None,
    *,
    manifest_meta: dict | None = None,
    permissions: list[str] | None = None,
) -> list[dict]:
    """Re-detect embedded SDKs from a decrypted APK path (task-time refresh)."""
    if not apk_path or not Path(apk_path).is_file():
        return []
    try:
        apk = APK(str(apk_path))
    except Exception:
        return []
    meta = manifest_meta if manifest_meta is not None else _extract_meta(apk)
    perms = list(permissions if permissions is not None else (apk.get_permissions() or []))
    return detect_sdks(meta, perms, _extract_sdk_class_markers(apk))
