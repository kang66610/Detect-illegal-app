"""Frida 动态监控：遍历期间记录敏感 API 与 URL，证据以 JSON 落盘。"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from datetime import datetime
from urllib.parse import urlsplit

from agent.common.exceptions import EngineUnavailableError
from agent.common.event_log import record_event
from agent.ai_explorer.android_device import AndroidDevice
from agent.detection_engines.base import DetectionContext, EngineResult, Finding
from agent.detection_engines.sdk_detector import identify_sdk_from_stack, sdk_policy_aliases
from agent.detection_engines.sensitive_api_registry import build_hook_script, load_sensitive_api_registry, resolve_data_type

_API_DATA_TYPES = {
    "getdeviceid": "设备标识信息", "getimei": "设备标识信息", "getsubscriberid": "IMSI",
    "getsimserialnumber": "设备标识信息", "getline1number": "手机号码",
    "requestlocationupdates": "位置信息", "mediarecorder.start": "音频信息",
}


def _api_data_type(api: str, registry_id: str | None = None) -> str | None:
    if registry_id:
        resolved = resolve_data_type(registry_id)
        if resolved:
            return resolved
    normalized = (api or "").lower()
    return next((data_type for key, data_type in _API_DATA_TYPES.items() if key in normalized), None)


def _policy_discloses_sdk_data(policy_text: str, sdk_name: str, data_type: str, *, sdk: dict | None = None) -> bool:
    raw = (policy_text or "").lower()
    matching_aliases = [alias for alias in sdk_policy_aliases(sdk, sdk_name) if alias in raw]
    if not matching_aliases:
        return False
    terms = {
        "设备标识信息": ("设备标识", "设备信息", "imei", "androidid", "android id"),
        "IMSI": ("imsi", "国际移动用户识别"),
        "手机号码": ("手机号码", "本机号码", "line1number"),
        "位置信息": ("位置信息", "定位"),
        "音频信息": ("录音", "音频", "麦克风", "语音"),
    }.get(data_type, (str(data_type or "").lower(),))
    paragraphs = [part.strip() for part in raw.replace("\r", "\n").split("\n") if part.strip()]
    sections = [part for part in paragraphs if any(alias in part for alias in matching_aliases)] or [raw]
    purpose_terms = ("为了", "用于", "目的", "以便", "提供", "保障")
    method_terms = ("收集", "获取", "调用", "访问", "请求", "上传", "传输")
    return any(
        any(term in "".join(section.split()) for term in terms if term)
        and any(term in section for term in purpose_terms)
        and any(term in section for term in method_terms)
        for section in sections
    )


def _app_package(ctx) -> str | None:
    apk = getattr(ctx, "apk", None)
    return getattr(apk, "package_name", None) if apk is not None else None


def _manual_consent_code_request_url(events: list[dict], observation: dict) -> dict | None:
    """Return the request trace bounded by a human, unchecked-consent probe.

    The UI observer sees the enabled-to-countdown transition only after the
    tester presses the button.  A URL in the armed-to-observed time window is
    required as a second independent signal; generic background traffic is
    deliberately excluded.
    """
    started = int(observation.get("armed_at_ms") or 0)
    observed = int(observation.get("observed_at_ms") or 0)
    if not started or not observed or observed < started:
        return None
    for event in events:
        if event.get("type") != "url":
            continue
        when = int(event.get("time") or 0)
        if not started - 1_000 <= when <= observed + 1_000:
            continue
        url = str(event.get("url") or "")
        identity = url.lower()
        fields = {str(item).lower() for item in event.get("credential_fields") or []}
        code_endpoint = any(term in identity for term in (
            "sms", "verify", "verification", "captcha", "sendcode", "send_code", "authcode",
        ))
        phone_payload = bool(fields.intersection({"phone", "mobile", "verification_code", "verifycode", "sms_code", "captcha"}))
        if code_endpoint or phone_payload:
            return event
    return None


class FridaMonitorEngine:
    def __init__(self, *, device_controller: AndroidDevice | None = None):
        self.events: list[dict] = []
        self._session = None
        self._script = None
        self._device_controller = device_controller
        # The workflow uses this to distinguish a spawn failure (which can
        # often be recovered by launching the app and attaching to its live
        # process) from a server, attach, or hook-loading failure.
        self.last_failure_stage: str | None = None

    @staticmethod
    def _call_with_timeout(frida, timeout_seconds: float, operation):
        """Cancel a blocking Frida RPC instead of wedging the worker thread.

        Frida's Python API natively supports ``Cancellable`` for spawn,
        attach, script load and resume.  This is intentionally not a Python
        thread timeout: a timed-out native call would otherwise continue in
        the background and retain the device lock.
        """
        cancellable_type = getattr(frida, "Cancellable", None)
        if cancellable_type is None:
            return operation()
        cancellable = cancellable_type()
        timeout = max(1.0, float(timeout_seconds))
        timer = threading.Timer(timeout, cancellable.cancel)
        timer.daemon = True
        timer.start()
        try:
            return operation(cancellable=cancellable)
        except Exception as exc:
            if getattr(cancellable, "is_cancelled", False):
                raise TimeoutError(f"Frida 操作超过 {int(timeout)} 秒未返回") from exc
            raise
        finally:
            timer.cancel()

    @staticmethod
    def _find_running_process(device, package: str):
        """Return a live Frida process for ``package`` when one is visible.

        Some Android apps do not answer ``device.spawn`` reliably (custom
        launchers, WebView bootstrap processes, or anti-debug startup code),
        while a normal Appium launch leaves an attachable process behind.
        Matching both the Frida identifier and display name keeps this
        fallback independent of the process' label.
        """
        package_lower = str(package or "").lower()
        for process in device.enumerate_processes():
            identifier = str(getattr(process, "identifier", "") or "").lower()
            name = str(getattr(process, "name", "") or "").lower()
            if package_lower and (package_lower == identifier or package_lower == name
                                  or package_lower in identifier or package_lower in name):
                return process
        return None

    def start(self, ctx: DetectionContext, *, spawn_target_override: bool | None = None) -> None:
        self.last_failure_stage = None
        try:
            import frida
        except ImportError as exc:
            raise EngineUnavailableError("缺少 frida 依赖，请安装 backend/requirements.txt") from exc
        package = ctx.apk.package_name
        if not package:
            raise EngineUnavailableError("APK 未解析出包名，无法附加 Frida")
        frida_cfg = ctx.cfg["frida"]
        timeout_seconds = float(frida_cfg.get("operation_timeout_seconds", 20))
        try:
            record_event(ctx, "frida", "connecting", package=package)
            # AVD reboots remove the root process while Frida's Android helper
            # can still report a device as present.  Start the known local
            # binary first so the following health check verifies the actual
            # spawn/attach capability instead of mere USB discovery.
            if frida_cfg.get("auto_start", False):
                controller = self._device_controller or AndroidDevice(ctx.cfg.get("appium", {}))
                record_event(ctx, "frida", "server_ensure_started", package=package)
                if not controller.ensure_frida_server(
                    str(frida_cfg.get("server_path") or "/data/local/tmp/frida-server"),
                    int(frida_cfg.get("startup_timeout_seconds", 12)),
                ):
                    record_event(ctx, "frida", "server_ensure_failed", package=package)
                    raise EngineUnavailableError("Frida Server 未运行，且无法在本地 root AVD 上自动启动")
                record_event(ctx, "frida", "server_ensure_completed", package=package)
            device = frida.get_device(frida_cfg["device_id"], timeout=5000) if frida_cfg["device_id"] else frida.get_usb_device(timeout=5000)
            record_event(ctx, "frida", "device_connected", device_id=device.id, device_name=device.name)
            # get_device only verifies that Frida can see an ADB device.  It
            # does not contact frida-server, so spawn/attach could otherwise
            # block after an AVD reboot while the UI still says “connecting”.
            record_event(ctx, "frida", "server_health_check", device_id=device.id)
            try:
                device.enumerate_processes()
                parameters = getattr(device, "query_system_parameters", lambda: {})()
                if parameters and parameters.get("access") not in (None, "full"):
                    raise RuntimeError(f"Frida 访问级别不足：{parameters.get('access')}")
            except Exception as exc:
                record_event(ctx, "frida", "server_unavailable", device_id=device.id, error=str(exc)[:300])
                raise EngineUnavailableError(
                    "Frida Server 未运行或不可连接；请在已 root 的模拟器中启动 frida-server 后重新检测"
                ) from exc
            record_event(ctx, "frida", "server_ready", device_id=device.id)
            spawn_target = frida_cfg["spawn_target"] if spawn_target_override is None else bool(spawn_target_override)
            if spawn_target:
                self.last_failure_stage = "spawning"
                record_event(ctx, "frida", "spawning", package=package)
                try:
                    pid = self._call_with_timeout(frida, timeout_seconds, lambda **kwargs: device.spawn([package], **kwargs))
                except Exception as spawn_error:
                    # A timed-out spawn may nevertheless have left the target
                    # process alive. Attach to that process before declaring
                    # Frida unavailable; this is safe because it does not
                    # alter permissions or device-wide settings.
                    record_event(ctx, "frida", "spawn_failed", package=package,
                                 error=str(spawn_error)[:300])
                    process = self._find_running_process(device, package)
                    if process is None:
                        raise
                    pid = getattr(process, "pid", None)
                    record_event(ctx, "frida", "spawn_fallback_attach", package=package,
                                 pid=pid, process_name=getattr(process, "name", ""))
                record_event(ctx, "frida", "attaching", package=package, pid=pid)
                self.last_failure_stage = "attaching"
                self._session = self._call_with_timeout(frida, timeout_seconds, lambda **kwargs: device.attach(pid, **kwargs))
            else:
                record_event(ctx, "frida", "attaching", package=package)
                self.last_failure_stage = "attaching"
                self._session = self._call_with_timeout(frida, timeout_seconds, lambda **kwargs: device.attach(package, **kwargs))
                pid = None
            self.last_failure_stage = "loading_hook"
            record_event(ctx, "frida", "loading_hook", package=package, pid=pid)
            self._script = self._session.create_script(build_hook_script(load_sensitive_api_registry()))
            self._script.on("message", self._on_message)
            self._call_with_timeout(frida, timeout_seconds, lambda **kwargs: self._script.load(**kwargs))
            if pid is not None:
                record_event(ctx, "frida", "resuming", package=package, pid=pid)
                self._call_with_timeout(frida, timeout_seconds, lambda **kwargs: device.resume(pid, **kwargs))
            record_event(ctx, "frida", "monitor_started", package=package, pid=pid)
        except Exception as exc:
            record_event(ctx, "frida", "monitor_failed", package=package,
                         stage=self.last_failure_stage or "startup",
                         error=str(exc)[:300])
            self.stop(ctx, save=False)
            raise EngineUnavailableError(f"Frida 无法附加 {package}：{exc}") from exc

    def _on_message(self, message: dict, _data) -> None:
        if message.get("type") == "send" and isinstance(message.get("payload"), dict):
            payload = dict(message["payload"])
            if payload.get("type") == "url":
                from agent.detection_engines.network_evidence import normalize_url
                payload["url"] = normalize_url(str(payload.get("url") or ""))
            payload.setdefault("observed_at", datetime.utcnow().isoformat())
            self.events.append(payload)

    def stop(self, ctx: DetectionContext, save: bool = True) -> EngineResult:
        # 可选延长观察窗口必须发生在卸载脚本之前，确保仍能接收事件。
        if save:
            wait = ctx.cfg["frida"].get("monitor_seconds", 0)
            if wait:
                time.sleep(wait)
            record_event(ctx, "frida", "monitor_stopping")
        try:
            if self._script:
                try:
                    self._script.unload()
                except Exception:
                    # A spawned target may exit before cleanup.  In that case
                    # Frida has already destroyed the remote script, which is
                    # a normal teardown condition rather than a task failure.
                    pass
            if self._session:
                try:
                    self._session.detach()
                except Exception:
                    pass
        finally:
            self._script = self._session = None
        if not save:
            return EngineResult()
        # Normalize at the ingestion boundary so every downstream rule uses
        # the registry's stable identifier/data category and stack attribution.
        for event in self.events:
            if event.get("type") != "api":
                continue
            event.setdefault("data_type", _api_data_type(str(event.get("api") or ""), event.get("registry_id")))
            sdk = identify_sdk_from_stack(str(event.get("stack") or ""), app_package=_app_package(ctx))
            if sdk:
                event.setdefault("sdk", sdk["name"])
                event.setdefault("sdk_matched_by", sdk["matched_by"])
        profile = str(ctx.runtime.get("probe_profile") or "observe")
        path = ctx.data_dir / "callstack" / profile / "frida-events.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        aggregate_path = ctx.data_dir / "callstack" / "frida-events.json"
        aggregate_path.parent.mkdir(parents=True, exist_ok=True)
        previous = []
        if aggregate_path.is_file():
            try:
                previous = list(json.loads(aggregate_path.read_text(encoding="utf-8")).get("events") or [])
            except (OSError, json.JSONDecodeError):
                previous = []
        phase_events = [{**event, "probe_profile": profile} for event in self.events]
        events = previous + phase_events
        payload = {"captured_at": datetime.utcnow().isoformat(), "probe_profile": profile, "events": phase_events}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        aggregate_path.write_text(json.dumps({
            "captured_at": datetime.utcnow().isoformat(), "events": events,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        record_event(ctx, "frida", "monitor_stopped", event_count=len(self.events))
        findings: list[Finding] = []
        api_events = [e for e in self.events if e.get("type") == "api"]
        native_loads = [e for e in self.events if e.get("type") == "native_load"]
        ctx.runtime["frida_sensitive_api_events"] = len(api_events)
        ctx.runtime["frida_native_load_events"] = len(native_loads)
        consent_time = ctx.runtime.get("consent_timestamp_ms")
        before_consent = [event for event in api_events if not consent_time or event.get("time", 0) <= consent_time]
        if before_consent:
            findings.append(Finding(kind="api_called_before_consent", category=3, payload={**before_consent[0], "before_consent": True}))
        manual_probe_evidence: list[dict] = []
        for observation in ctx.runtime.get("manual_auth_consent_code_request_observations", []):
            if str(observation.get("probe_profile") or "observe") != profile:
                continue
            matched_url = _manual_consent_code_request_url(self.events, observation)
            if matched_url is None:
                gap = "人工未勾选登录条款后验证码入口已响应，但未捕获同时间窗验证码网络请求，未作违规认定"
                if gap not in ctx.runtime.setdefault("coverage_gaps", []):
                    ctx.runtime["coverage_gaps"].append(gap)
                ctx.runtime["coverage_complete"] = False
                continue
            finding_payload = {
                **matched_url,
                "before_consent": True,
                "consent_scope": "login_terms_checkbox",
                "manual_trigger": True,
                "checkbox_target": observation.get("checkbox_target"),
                "code_target": observation.get("code_target"),
                "armed_at_ms": observation.get("armed_at_ms"),
                "observed_at_ms": observation.get("observed_at_ms"),
                "evidence_limit": "仅确认人工未勾选登录条款时，验证码请求按钮已被应用接受且同一时间窗存在设备侧请求；不记录手机号、验证码或请求内容。",
            }
            findings.append(Finding(
                kind="api_called_before_consent", category=3, payload=finding_payload,
            ))
            manual_probe_evidence.append(record_event(
                ctx, "frida", "manual_login_consent_code_request_correlated",
                finding_kind="api_called_before_consent", **finding_payload,
            ))
        api_counts = Counter(str(event.get("api") or "") for event in api_events)
        for api, count in api_counts.items():
            if api and count >= 5:
                findings.append(Finding(kind="frequent_collection", category=4, payload={
                    "api": api, "count": count, "window_minutes": "monitor_session",
                }))
                break
        apk = getattr(ctx, "apk", None)
        app_package = getattr(apk, "package_name", None) if apk is not None else None
        from agent.detection_engines.policy_analyzer import _policy_source
        policy_text, _policy_source_name, policy_is_complete = _policy_source(ctx)
        for event in api_events:
            sdk = identify_sdk_from_stack(str(event.get("stack") or ""), app_package=app_package)
            data_type = _api_data_type(str(event.get("api") or ""), event.get("registry_id"))
            if not sdk or not data_type or not policy_is_complete:
                continue
            if not _policy_discloses_sdk_data(policy_text, sdk["name"], data_type, sdk=sdk):
                findings.append(Finding(kind="sdk_collection_not_disclosed", category=2, payload={
                    **event, "sdk": sdk["name"], "sdk_matched_by": sdk["matched_by"], "data_type": data_type,
                    "sdk_known": bool(sdk.get("known")), "sdk_package": sdk.get("package"),
                    "policy_document_complete": True,
                }))
                break
        triggered = {
            (identify_sdk_from_stack(str(event.get("stack") or ""), app_package=app_package) or {}).get("name")
            for event in api_events
        }
        for item in (getattr(apk, "sdk_list", None) if apk is not None else None) or []:
            name = str((item or {}).get("name") or "")
            matched_by = [str(marker) for marker in ((item or {}).get("matched_by") or [])]
            weak_only = bool(matched_by) and all(marker.startswith("权限:") for marker in matched_by)
            if not name or weak_only or name in triggered:
                continue
            if not (item or {}).get("collected"):
                continue
            gaps = ctx.runtime.setdefault("coverage_gaps", [])
            gap = f"静态识别到的第三方 SDK「{name}」未在本次可访问路径触发敏感 API"
            if gap not in gaps:
                gaps.append(gap)
            ctx.runtime["coverage_complete"] = False
        domains = [d.lower() for d in [
            *ctx.cfg["frida"].get("overseas_domains", []),
            *ctx.cfg.get("network", {}).get("overseas_domains", []),
        ]]
        for event in self.events:
            if event.get("type") != "url":
                continue
            url = str(event.get("url") or "")
            transport = str(event.get("transport") or "").lower()
            if not transport:
                transport = "https" if url.lower().startswith("https://") else (
                    "http" if url.lower().startswith("http://") else ""
                )
            credential_fields = sorted({
                str(item) for item in event.get("credential_fields") or [] if item
            })
            authorization_present = bool(event.get("authorization_present"))
            if transport == "http" and (credential_fields or authorization_present):
                findings.append(Finding(kind="login_data_unprotected", category=5, payload={
                    "url": url,
                    "host": (urlsplit(url).hostname or "").lower(),
                    "transport": "http",
                    "method": str(event.get("method") or ""),
                    "credential_fields": credential_fields,
                    "authorization_present": authorization_present,
                    "body_class": str(event.get("body_class") or "")[:160],
                    "time": event.get("time"),
                    "evidence_limit": "仅确认设备侧实际观察到的明文 HTTP 认证传输；不推断服务端存储、日志或数据库是否加密/去标识化。",
                }))
                break
        for event in self.events:
            url = str(event.get("url") or "")
            if event.get("type") == "url" and any(domain in url.lower() for domain in domains):
                findings.append(Finding(kind="overseas_transfer", category=5, payload={**event, "overseas": True}))
                break
        evidence_kinds = [finding.kind for finding in findings]
        matched_events = [{
            "api": event.get("api"), "url": event.get("url"), "time": event.get("time"),
            "observed_at": event.get("observed_at"),
            "transport": event.get("transport"), "method": event.get("method"),
            "credential_fields": event.get("credential_fields"),
            "authorization_present": bool(event.get("authorization_present")),
            "sdk": (identify_sdk_from_stack(str(event.get("stack") or ""), app_package=app_package) or {}).get("name"),
            "registry_id": event.get("registry_id"),
            "data_type": _api_data_type(str(event.get("api") or ""), event.get("registry_id")),
        } for event in self.events if event.get("type") in {"api", "url"}][:20]
        evidence = [*manual_probe_evidence, {"type": "callstack", "path": str(path), "meta": {
            "event_count": len(self.events), "finding_kinds": evidence_kinds,
            "matched_events": matched_events,
        }}]
        from agent.detection_engines.network_evidence import build_network_evidence
        evidence.append(build_network_evidence(ctx, self.events, evidence_kinds))
        return EngineResult(
            findings=findings,
            evidence_files=evidence,
            stats={
                "frida_events": len(self.events),
                "native_load_events": len(native_loads),
            },
        )
