"""SDK 识别：特征库是加速器，未知第三方包名仍按调用栈聚类归因。"""
from __future__ import annotations

import re

import yaml

from backend.app.config import PROJECT_ROOT

_FEATURES_PATH = PROJECT_ROOT / "agent" / "config" / "sdk_features.yaml"

_PLATFORM_PREFIXES = (
    "android.", "java.", "javax.", "androidx.", "kotlin.", "kotlinx.",
    "dalvik.", "libcore.", "com.android.", "org.json.", "org.apache.",
    "okhttp3.", "okio.", "retrofit2.", "io.reactivex.", "io.reactivex.rxjava",
    "sun.", "jdk.", "org.chromium.", "com.google.android.material.",
    "com.google.protobuf.", "org.jetbrains.", "io.flutter.embedding.",
    "io.flutter.plugin.common.", "io.flutter.view.",
)

# 厂商前缀只用于给未知 SDK 起可读名和对照政策，不是准入白名单。
_VENDOR_HINTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("com.alibaba.sdk.android.feedback", "阿里云用户反馈", ("阿里云用户反馈", "阿里用户反馈", "alibaba.sdk.android.feedback")),
    ("com.alibaba", "阿里", ("阿里", "alibaba", "alipay", "淘宝")),
    ("com.taobao", "阿里", ("阿里", "淘宝", "taobao")),
    ("com.ta.utdid2", "阿里", ("阿里", "utdid")),
    ("com.umeng", "友盟", ("友盟", "umeng")),
    ("cn.sharesdk", "ShareSDK", ("sharesdk", "mob", "mobtech")),
    ("cn.fly.tools", "ShareSDK", ("sharesdk", "mob", "mobtech")),
    ("com.mob.tools", "MobTech", ("mob", "mobtech", "sharesdk")),
    ("com.mob.", "MobTech", ("mob", "mobtech", "sharesdk")),
    ("com.iflytek", "讯飞", ("讯飞", "iflytek")),
    ("com.tencent.bugly", "腾讯 Bugly", ("bugly", "腾讯")),
    ("com.tencent", "腾讯", ("腾讯", "tencent", "微信", "qq")),
    ("com.baidu", "百度", ("百度", "baidu")),
    ("com.amap", "高德", ("高德", "amap")),
    ("com.huawei.hms", "华为 HMS", ("华为", "hms", "huawei")),
    ("com.xiaomi", "小米", ("小米", "xiaomi")),
    ("cn.jpush", "极光", ("极光", "jpush")),
    ("cn.jiguang", "极光", ("极光", "jiguang")),
    ("com.igexin", "个推", ("个推", "getui")),
    ("com.bytedance", "字节跳动", ("字节", "穿山甲", "pangle", "csj")),
    ("com.qq.e", "腾讯广告", ("腾讯广告", "优量汇", "gdt")),
    ("io.agora", "声网", ("声网", "agora")),
    ("com.google.android.gms", "Google Play 服务", ("google", "gms", "谷歌")),
    ("com.facebook", "Facebook", ("facebook", "meta")),
    ("com.adjust", "Adjust", ("adjust",)),
    ("com.appsflyer", "AppsFlyer", ("appsflyer",)),
    ("com.sensorsdata", "神策", ("神策", "sensorsdata")),
    ("com.talkingdata", "TalkingData", ("talkingdata",)),
    ("io.sentry", "Sentry", ("sentry",)),
)

_NAME_ALIASES = {
    "讯飞语音": ("讯飞", "iflytek"),
    "阿里云用户反馈": ("阿里云用户反馈", "阿里用户反馈", "alibaba.sdk.android.feedback", "alibabacloud feedback"),
}

_JAVA_TOKEN = re.compile(r"\b([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,})\b")


def _load_features() -> list[dict]:
    with open(_FEATURES_PATH, "r", encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("sdk_features", [])


def detect_sdks(manifest_meta: dict, permissions: list[str], class_markers: list[str] | None = None) -> list[dict]:
    """根据 Manifest、权限和 DEX 包特征识别 SDK。

    权限仅能作为弱线索；实际 DEX 包名命中会单独标注，供动态调用栈归因使用。
    """
    result = []
    meta_keys = set(manifest_meta.keys())
    markers = set(class_markers or [])
    for feat in _load_features():
        matched_by = [k for k in feat["meta_keys"] if k in meta_keys]
        if not matched_by:
            hit_prefix = [p for p in feat.get("package_prefixes", []) if p in markers]
            if hit_prefix:
                matched_by = [f"DEX:{p}" for p in hit_prefix]
            hit_perm = [p for p in feat["permissions"] if p in permissions]
            if hit_perm and not matched_by:
                matched_by = [f"权限:{','.join(hit_perm)}"]
        if matched_by:
            result.append({
                "name": feat["name"],
                "collected": feat["collected"],
                "matched_by": matched_by,
                "known": True,
            })
    return result


def identify_sdk_from_stack(stack: str, *, app_package: str | None = None) -> dict | None:
    """从 Java 调用栈归因第三方 SDK。

    特征库命中优先；否则按第三方包名前缀聚类。应用自身与 Android 框架不算 SDK。
    """
    normalized = (stack or "").lower()
    if not normalized.strip():
        return None
    for feat in _load_features():
        for prefix in feat.get("package_prefixes", []):
            if prefix.lower() in normalized:
                return {
                    "name": feat["name"],
                    "collected": feat.get("collected", []),
                    "matched_by": f"stack:{prefix}",
                    "known": True,
                    "package": prefix,
                    "aliases": list(_NAME_ALIASES.get(feat["name"], ())),
                }
    cluster = cluster_third_party_from_stack(stack, app_package=app_package)
    return cluster


def cluster_third_party_from_stack(stack: str, *, app_package: str | None = None) -> dict | None:
    """把未知第三方包聚类成一个可对照政策的 SDK 描述。"""
    packages = [
        package for package in _packages_from_stack(stack)
        if _is_third_party_package(package, app_package)
    ]
    if not packages:
        return None
    packages.sort(key=lambda item: (-len(item.split(".")), -len(item)))
    package = _cluster_key(packages[0])
    vendor, aliases = _vendor_for_package(package)
    name = f"{vendor}（{package}）" if vendor else f"第三方SDK（{package}）"
    return {
        "name": name,
        "collected": [],
        "matched_by": f"stack-cluster:{package}",
        "known": False,
        "package": package,
        "aliases": list(aliases),
    }


def sdk_policy_aliases(sdk: dict | None, sdk_name: str = "") -> list[str]:
    """政策对照用的全部别名，包含包名、厂商名和特征库中文名。"""
    names: list[str] = []
    if sdk:
        names.append(str(sdk.get("name") or ""))
        names.extend(str(item) for item in (sdk.get("aliases") or []))
        package = str(sdk.get("package") or "")
        if package:
            names.append(package)
            names.append(package.replace(".", ""))
        names.extend(_NAME_ALIASES.get(str(sdk.get("name") or ""), ()))
    if sdk_name:
        names.append(sdk_name)
        names.extend(_NAME_ALIASES.get(sdk_name, ()))
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in names:
        alias = str(raw or "").strip().lower()
        if len(alias) < 2 or alias in seen:
            continue
        if alias.startswith("第三方sdk"):
            continue
        seen.add(alias)
        ordered.append(alias)
    return ordered


def _packages_from_stack(stack: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _JAVA_TOKEN.findall(stack or ""):
        package = _class_to_package(match)
        if package and package not in seen:
            seen.add(package)
            found.append(package)
    return found


def _class_to_package(token: str) -> str:
    parts = [part for part in token.split(".") if part]
    class_index = next((index for index, part in enumerate(parts) if part[:1].isupper()), None)
    if class_index:
        parts = parts[:class_index]
    return ".".join(parts)


def _cluster_key(package: str) -> str:
    parts = package.split(".")
    if len(parts) >= 4 and parts[0] in {"com", "cn", "io", "org", "net"}:
        return ".".join(parts[:4])
    if len(parts) >= 3:
        return ".".join(parts[:3])
    return package


def _is_third_party_package(package: str, app_package: str | None) -> bool:
    lowered = package.lower()
    if _is_obfuscated(lowered):
        return False
    if any(lowered == prefix.rstrip(".") or lowered.startswith(prefix) for prefix in _PLATFORM_PREFIXES):
        return False
    app = str(app_package or "").strip().lower()
    if app and (lowered == app or lowered.startswith(app + ".")):
        return False
    return True


def _is_obfuscated(package: str) -> bool:
    parts = package.split(".")
    if len(parts) < 2:
        return True
    return sum(1 for part in parts if len(part) <= 1) >= max(2, len(parts) - 1)


def _vendor_for_package(package: str) -> tuple[str | None, tuple[str, ...]]:
    lowered = package.lower()
    for prefix, label, aliases in _VENDOR_HINTS:
        if lowered == prefix or lowered.startswith(prefix + ".") or prefix in lowered:
            extra = (label.lower(), prefix.lower(), *aliases)
            return label, tuple(dict.fromkeys(item.lower() for item in extra))
    return None, ()
