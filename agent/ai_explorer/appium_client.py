"""Appium 的最小封装；依赖延迟导入以提供清晰的运行环境错误。"""
from __future__ import annotations

import time
import json
import hashlib
import inspect
import re
from io import BytesIO
from pathlib import Path

from agent.common.exceptions import EngineUnavailableError, ExplorationError
from agent.ai_explorer.appium_service import AppiumService
from agent.ai_explorer.android_device import AndroidDevice, is_local_emulator_udid


class AppiumClient:
    def __init__(self, cfg: dict, *, device: AndroidDevice | None = None):
        self.cfg = cfg
        self.driver = None
        self._by = None
        self._device = device or AndroidDevice(cfg.get("appium", {}))
        self.last_cleanup_error = ""
        self.last_package = ""

    def connect(self) -> None:
        appium = self.cfg["appium"]
        # Resolve and canonicalize the ADB transport before touching Appium.
        # A single AVD can appear as both 127.0.0.1 and [::1]; leaving that
        # ambiguity in place makes Appium select competing UiAutomator2
        # instrumentations before the service-level cleanup can run.
        resolver = getattr(self._device, "resolve_udid", None)
        if callable(resolver):
            try:
                resolved_udid = str(resolver() or "").strip()
            except Exception as exc:
                raise EngineUnavailableError(
                    f"ADB 设备不可用：{str(exc)[:500]}。请确认模拟器已启动且出现在 adb devices 中。"
                ) from exc
            if resolved_udid:
                appium["udid"] = resolved_udid
                # Frida must observe the same transport as Appium.  This also
                # handles an AVD that changed from emulator-5554 to a loopback
                # TCP serial after the ADB daemon was restarted.
                frida_cfg = self.cfg.get("frida")
                if isinstance(frida_cfg, dict):
                    frida_cfg["device_id"] = resolved_udid
        service = AppiumService(appium)
        if not service.ensure_ready():
            raise EngineUnavailableError(
                f"Appium 服务未就绪：{appium['server_url']}。"
                "请运行 scripts\\start_appium.ps1，或启用 PRIVACY_APPIUM_AUTO_START=true。"
            )
        # A failed POST /session can leave an Appium master session alive even
        # though webdriver.Remote raised.  Its later newCommandTimeout cleanup
        # can stop UiAutomator2 underneath a newer session.  The worker is
        # serial for real-device audits, so cleaning loopback orphan sessions
        # before opening a new one is safe and deterministic.
        service.cleanup_sessions()
        self._device.prepare()
        try:
            from appium import webdriver
            from appium.options.android import UiAutomator2Options
            from appium.webdriver.common.appiumby import AppiumBy
        except ImportError as exc:
            raise EngineUnavailableError("缺少 Appium-Python-Client，请安装 backend/requirements.txt") from exc
        caps = {
            "platformName": "Android", "appium:automationName": "UiAutomator2",
            "appium:deviceName": appium["device_name"],
            "appium:noReset": appium["no_reset"],
            "appium:newCommandTimeout": appium["new_command_timeout_seconds"],
            "appium:skipDeviceInitialization": appium.get("skip_device_initialization", False),
            "appium:ignoreHiddenApiPolicyError": appium.get("ignore_hidden_api_policy_error", True),
            "appium:uiautomator2ServerLaunchTimeout": (
                int(appium.get("uiautomator2_server_launch_timeout_seconds", 30)) * 1000
            ),
        }
        if appium["platform_version"]:
            caps["appium:platformVersion"] = appium["platform_version"]
        if appium["udid"]:
            caps["appium:udid"] = appium["udid"]
        retries = max(1, int(appium.get("session_retries", 2)))
        # A normal retry clears only Appium's two helper APKs.  Some AVDs can
        # leave Android's instrumentation subsystem wedged after that; an
        # explicitly configured local AVD gets one no-wipe reboot and one
        # final session attempt.  Never apply this to a physical device.
        reboot_retry = bool(appium.get("auto_reboot_on_uiautomator2_failure", False))
        total_attempts = retries + int(reboot_retry)
        last_error = None
        for attempt in range(total_attempts):
            attempt_caps = dict(caps)
            # This audit never uses Appium Settings' location mock.  After a
            # Settings-process timeout, skip helper initialization so
            # UiAutomator2 can still attach.
            if last_error is not None and _is_settings_startup_error(last_error):
                attempt_caps["appium:skipDeviceInitialization"] = True
            try:
                self.driver = webdriver.Remote(
                    appium["server_url"],
                    options=UiAutomator2Options().load_capabilities(attempt_caps),
                )
                break
            except Exception as exc:
                last_error = exc
                if _is_uiautomator_startup_error(exc) and attempt + 1 < total_attempts:
                    if attempt + 1 < retries:
                        self._device.recover_uiautomator2()
                        continue
                    if self._device.reboot_after_uiautomator2_failure():
                        continue
                detail = _compact_appium_error(exc)
                raise EngineUnavailableError(
                    "Appium 服务已响应，但 UiAutomator2 会话创建失败："
                    f"{detail}。已完成设备预检；请查看 data/logs/appium-4725.log。"
                ) from exc
        if self.driver is None:
            raise EngineUnavailableError(f"UiAutomator2 会话创建失败：{_compact_appium_error(last_error)}")
        self._by = AppiumBy

    def install(self, apk_path: Path, package_name: str) -> bool:
        """Prepare the audited package without needless uninstall/reinstall.

        An existing package is reset with Android's ``pm clear`` so the audit
        starts from clean app data while retaining the installed APK.  Only a
        package that is absent is installed from ``apk_path``.
        """
        if not self.driver:
            raise ExplorationError("Appium 尚未连接")
        was_installed = False
        try:
            was_installed = bool(self.driver.is_app_installed(package_name))
            if was_installed:
                clear_data = getattr(self._device, "clear_app_data", None)
                if not callable(clear_data):
                    raise ExplorationError("无法清除已安装应用数据：设备适配器不支持 pm clear")
                clear_data(package_name)
            else:
                self.driver.install_app(str(apk_path))
            return was_installed
        except Exception as exc:
            action = "清除已安装应用数据" if was_installed else "安装 APK"
            raise ExplorationError(f"{action}失败：{exc}") from exc

    def activate(self, package_name: str) -> None:
        try:
            self.driver.activate_app(package_name)
            time.sleep(self.cfg["appium"]["page_wait_seconds"])
        except Exception as exc:
            raise ExplorationError(f"无法启动 {package_name}：{exc}") from exc

    def restart_app(self, package_name: str) -> None:
        """Cold-restart only the audited app while preserving its local data.

        A rendered loading shell is different from a broken Appium session:
        UiAutomator2 is still responsive, but the app process has stopped
        making progress.  Terminating and activating the package is the least
        destructive recovery because it keeps login, consent and audit state.
        """
        if not self.driver:
            raise ExplorationError("Appium 尚未连接")
        try:
            self.driver.terminate_app(package_name)
            self.driver.activate_app(package_name)
            time.sleep(self.cfg["appium"]["page_wait_seconds"])
        except Exception as exc:
            raise ExplorationError(f"无法重启 {package_name}：{exc}") from exc

    def page(self) -> tuple[str, str]:
        try:
            try:
                self.last_package = getattr(self.driver, "current_package", None) or ""
            except Exception:
                self.last_package = ""
            return self.driver.current_activity or "", self.driver.page_source or ""
        except Exception as exc:
            raise ExplorationError(f"无法读取当前页面：{exc}") from exc

    def recover_runtime_session(
        self,
        package_name: str,
        error: Exception,
        *,
        should_stop=None,
    ) -> bool:
        """Recover once when a live AVD restart drops the current Activity.

        Appium's startup recovery only helps before a session exists.  During
        an audit an Android restart makes the existing UiAutomator2 HTTP
        proxy disappear (usually as ``socket hang up``), then the next
        ``getCurrentActivity`` produces the misleading focused-activity
        error.  Wait for the already-rebooting emulator, reset only Appium's
        helper state, create a fresh session and relaunch the audited app.
        The APK is intentionally *not* reinstalled, preserving this run's
        clean installation while avoiding a second app lifecycle mutation.
        """
        appium = self.cfg.get("appium", {})
        if not _is_runtime_session_disconnect(error):
            return False
        if not (appium.get("auto_recover", False) and package_name):
            return False
        if callable(should_stop) and should_stop():
            return False
        self.close()
        if callable(should_stop) and should_stop():
            return False
        if is_local_emulator_udid(self._device.udid):
            timeout = int(appium.get("uiautomator2_reboot_timeout_seconds", 120))
            wait_until_ready = self._device.wait_until_ready
            try:
                parameters = inspect.signature(wait_until_ready).parameters.values()
                accepts_stop = any(
                    parameter.name == "should_stop"
                    or parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                )
            except (TypeError, ValueError):
                accepts_stop = False
            ready = (
                wait_until_ready(timeout, should_stop=should_stop)
                if accepts_stop and callable(should_stop)
                else wait_until_ready(timeout)
            )
            if not ready or (callable(should_stop) and should_stop()):
                return False
        try:
            if callable(should_stop) and should_stop():
                return False
            self._device.recover_uiautomator2()
            if callable(should_stop) and should_stop():
                return False
            self.connect()
            if callable(should_stop) and should_stop():
                self.close()
                return False
            self.activate(package_name)
            return True
        except Exception:
            self.close()
            return False

    def screenshot(self, path: Path) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return bool(self.driver.get_screenshot_as_file(str(path)))
        except Exception:
            return False

    @staticmethod
    def _document_body_signature(screenshot: bytes) -> bytes:
        """Hash only the readable body, excluding volatile status/navigation bars."""
        if not screenshot:
            return b""
        try:
            from PIL import Image

            image = Image.open(BytesIO(screenshot)).convert("RGB")
            width, height = image.size
            if width < 20 or height < 20:
                return b""
            # Top status/title and bottom gesture/nav regions may change every
            # second even while a blank WebView never renders any document.
            body = image.crop((0, int(height * 0.16), width, int(height * 0.94)))
            body.thumbnail((96, 160))
            return body.tobytes()
        except Exception:
            return b""

    def document_body_is_blank(self) -> bool | None:
        """Return a conservative visual blank-body observation for WebViews.

        ``None`` means a screenshot could not be decoded. This distinguishes a
        real empty document body from an App crash and avoids treating a title
        bar plus a white canvas as a fully readable policy.
        """
        if not self.driver:
            raise ExplorationError("Appium 尚未连接")
        try:
            body = self._document_body_signature(self.driver.get_screenshot_as_png() or b"")
            if not body:
                return None
            # Nearly-white RGB samples have no readable text or loaded body.
            dark_samples = sum(1 for offset in range(0, len(body), 3) if min(body[offset:offset + 3]) < 235)
            return dark_samples / max(1, len(body) // 3) < 0.001
        except Exception:
            return None

    def recent_app_crash(self, package_name: str) -> str | None:
        """Expose read-only device crash diagnostics to the explorer."""
        return self._device.recent_app_crash(package_name)

    def scroll_document_down(self) -> str:
        """Return ``moved``, driver-confirmed ``bottom``, or transient ``stuck``."""
        if not self.driver:
            raise ExplorationError("Appium 尚未连接")
        def viewport_signature() -> str:
            try:
                source = str(self.driver.page_source or "")
                screenshot = self.driver.get_screenshot_as_png() or b""
                # Clock text and animated status bars must not make an empty
                # page look like a successfully scrolled document.
                source = re.sub(
                    r'(text|content-desc)="[^"]*\b\d{1,2}:\d{2}\b[^"]*"',
                    r'\1="<volatile-time>"', source, flags=re.I,
                )
                body = self._document_body_signature(screenshot)
                return hashlib.sha256(source.encode("utf-8") + body).hexdigest()
            except Exception:
                return ""

        before = viewport_signature()
        can_scroll_more: bool | None = None
        try:
            size = self.driver.get_window_size()
            width, height = int(size["width"]), int(size["height"])
            gesture_result = self.driver.execute_script("mobile: scrollGesture", {
                "left": max(1, width // 10), "top": max(1, height // 5),
                "width": max(1, width * 8 // 10), "height": max(1, height * 3 // 5),
                "direction": "down", "percent": 0.8,
            })
            if isinstance(gesture_result, bool):
                can_scroll_more = gesture_result
            time.sleep(self.cfg["appium"]["page_wait_seconds"])
            if before and viewport_signature() != before:
                return "moved"
        except Exception:
            # Fall through to the compatibility swipe below.
            pass
        # UiAutomator2 may report ``false`` for a nested WebView even when a
        # physical swipe is still possible. Verify the swipe rather than
        # assuming either command proves that the document was read.
        try:
            size = self.driver.get_window_size()
            x = int(size["width"]) // 2
            self.driver.swipe(x, int(size["height"]) * 4 // 5, x, int(size["height"]) // 4, duration=450)
            time.sleep(self.cfg["appium"]["page_wait_seconds"])
            if before and viewport_signature() != before:
                return "moved"
            return "bottom" if can_scroll_more is False else "stuck"
        except Exception as exc:
            raise ExplorationError(f"向下滚动页面失败：{exc}") from exc

    def scroll_down(self) -> bool:
        """Backward-compatible boolean scroll API for non-document callers."""
        return self.scroll_document_down() == "moved"

    def perform(self, decision: dict) -> None:
        action, target = decision["action"], decision.get("target", "")
        try:
            if action == "back":
                self.driver.back()
            elif action == "wait":
                page_wait = float(self.cfg["appium"].get("page_wait_seconds", 1))
                detection = self.cfg.get("detection") or {}
                settle_wait = float(detection.get(
                    "page_settle_wait_seconds",
                    0.0 if page_wait == 0 else 2.5,
                ))
                time.sleep(max(page_wait, settle_wait))
            elif action == "click":
                # 目标来自页面白名单，依次按 id、无障碍描述和可转义的文本定位。
                if target.startswith("relative:"):
                    match = re.fullmatch(r"relative:(0(?:\.\d+)?|1(?:\.0+)?),(0(?:\.\d+)?|1(?:\.0+)?)", target)
                    if not match:
                        raise ValueError("非法相对坐标目标")
                    x_ratio, y_ratio = (float(value) for value in match.groups())
                    # Relative targets are created only by a constrained
                    # app-specific scenario recipe in the explorer.  Keeping
                    # the coordinates inside the screen prevents this client
                    # primitive from becoming a free-form tap mechanism.
                    if not (0.05 <= x_ratio <= 0.95 and 0.05 <= y_ratio <= 0.95):
                        raise ValueError("相对坐标目标超出安全范围")
                    size = self.driver.get_window_size()
                    self.driver.execute_script("mobile: clickGesture", {
                        "x": int(int(size["width"]) * x_ratio),
                        "y": int(int(size["height"]) * y_ratio),
                    })
                    time.sleep(self.cfg["appium"]["page_wait_seconds"])
                    return
                if target.startswith("bounds:"):
                    match = re.fullmatch(r"bounds:\[(\d+),(\d+)\]\[(\d+),(\d+)\]", target)
                    if not match:
                        raise ValueError("非法页面边界目标")
                    left, top, right, bottom = (int(value) for value in match.groups())
                    if right <= left or bottom <= top:
                        raise ValueError("无效页面边界目标")
                    self.driver.execute_script("mobile: clickGesture", {
                        "x": (left + right) // 2, "y": (top + bottom) // 2,
                    })
                    time.sleep(self.cfg["appium"]["page_wait_seconds"])
                    return
                try:
                    self.driver.find_element(self._by.ID, target).click()
                except Exception:
                    try:
                        self.driver.find_element(self._by.ACCESSIBILITY_ID, target).click()
                    except Exception:
                        # target 已由 LLMController 对当前页面元素白名单化；再用 JSON 转义，
                        # 避免页面文本中的引号改变 UiSelector 表达式。
                        selector = f"new UiSelector().text({json.dumps(target, ensure_ascii=False)})"
                        try:
                            self.driver.find_element(self._by.ANDROID_UIAUTOMATOR, selector).click()
                        except Exception:
                            if len(str(target)) < 2:
                                raise
                            self._click_text_contains_preferring_document_span(str(target))
                time.sleep(self.cfg["appium"]["page_wait_seconds"])
        except Exception as exc:
            raise ExplorationError(f"执行遍历操作 {action} 失败：{exc}") from exc

    def enter_text(self, target: str, value: str) -> None:
        """Fill one whitelisted editable control without logging its value."""
        if not target or value is None:
            raise ExplorationError("输入目标或测试值为空")
        try:
            try:
                element = self.driver.find_element(self._by.ID, target)
            except Exception:
                element = self.driver.find_element(self._by.ACCESSIBILITY_ID, target)
            try:
                element.clear()
            except Exception:
                pass
            element.send_keys(value)
        except Exception as exc:
            raise ExplorationError(f"填写安全测试账号字段失败：{exc}") from exc

    def _click_text_contains_preferring_document_span(self, target: str) -> None:
        """Click a short 《隐私政策》 title even when it lives inside a long TextView.

        Consent dialogs often expose one accessibility node for the whole
        paragraph.  A naive center-click toggles the nearby checkbox or misses
        the ClickableSpan.  Probe several points along the estimated title line.
        """
        contains = f"new UiSelector().textContains({json.dumps(target, ensure_ascii=False)})"
        matches = list(self.driver.find_elements(self._by.ANDROID_UIAUTOMATOR, contains) or [])
        if not matches:
            raise ExplorationError(f"未找到包含文本的控件：{target}")
        compact_target = re.sub(r"\s+", "", target)
        scored: list[tuple[tuple, object, str]] = []
        for element in matches:
            try:
                text = str(element.text or "")
            except Exception:
                text = ""
            try:
                checkable = bool(element.get_attribute("checkable") == "true")
            except Exception:
                checkable = False
            try:
                class_name = str(element.get_attribute("className") or element.get_attribute("class") or "").lower()
            except Exception:
                class_name = ""
            scored.append((_document_span_host_sort_key(text, compact_target, checkable, class_name), element, text))
        scored.sort(key=lambda item: item[0])
        element = scored[0][1]
        text = scored[0][2]
        compact_text = re.sub(r"\s+", "", text)
        compact_text_lower = compact_text.lower()
        compact_target_lower = compact_target.lower()
        if text and compact_target_lower in compact_text_lower:
            try:
                rect = element.rect
                left, top, width, height = int(rect["x"]), int(rect["y"]), int(rect["width"]), int(rect["height"])
                point = self._document_span_click_point(target, text, left, top, width, height)
                if point is not None:
                    self.driver.execute_script("mobile: clickGesture", {"x": point[0], "y": point[1]})
                    return
            except Exception:
                pass
        element.click()

    def _document_span_click_point(
        self, target: str, host_text: str, left: int, top: int, width: int, height: int,
    ) -> tuple[int, int] | None:
        visual_point = self._document_span_point_from_visual_style(target, host_text, left, top, width, height)
        if visual_point is not None:
            return visual_point
        probe_i = int(getattr(self, "_document_span_probe", 0))
        self._document_span_probe = probe_i + 1
        return _estimated_document_span_point(target, host_text, left, top, width, height, probe_i)

    def _document_span_point_from_visual_style(
        self, target: str, host_text: str, left: int, top: int, width: int, height: int,
    ) -> tuple[int, int] | None:
        try:
            png = self.driver.get_screenshot_as_png()
        except Exception:
            return None
        if not png:
            return None
        try:
            from PIL import Image
            image = Image.open(BytesIO(png)).convert("RGB")
        except Exception:
            return None
        try:
            window = self.driver.get_window_size()
            scale_x = image.width / max(1, int(window["width"]))
            scale_y = image.height / max(1, int(window["height"]))
        except Exception:
            scale_x = scale_y = 1.0
        crop_box = (
            max(0, int(left * scale_x)),
            max(0, int(top * scale_y)),
            min(image.width, int((left + width) * scale_x)),
            min(image.height, int((top + height) * scale_y)),
        )
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
            return None
        crop = image.crop(crop_box)
        clusters = _styled_span_clusters(crop)
        if not clusters:
            return None
        titles = _ordered_document_titles(host_text)
        compact_target = re.sub(r"\s+", "", target).lower()
        index = next((i for i, title in enumerate(titles) if compact_target in title.lower() or title.lower() in compact_target), 0)
        if titles and len(clusters) >= len(titles) * 2:
            # Body + checkbox caption in one crop: the first group is the paragraph.
            index = min(index, len(titles) - 1)
        index = min(index, len(clusters) - 1)
        cx, cy, _cw, _ch = clusters[index]
        return (
            int((crop_box[0] + cx) / scale_x),
            int((crop_box[1] + cy) / scale_y),
        )

    def press_home(self) -> None:
        """Send the app to background for a bounded keepalive probe."""
        try:
            self.driver.press_keycode(3)
            time.sleep(self.cfg["appium"]["page_wait_seconds"])
        except Exception as exc:
            raise ExplorationError(f"切换到后台失败：{exc}") from exc

    def respond_to_permission(self, action: str) -> None:
        """Answer a visible Android permission prompt using stable system ids.

        This path is intentionally separate from LLM page decisions.  It never
        supplies credentials or changes application data beyond the selected
        platform permission state.
        """
        if action not in {"allow", "deny"}:
            raise ExplorationError(f"不支持的权限探针动作：{action}")
        candidates = {
            "allow": (
                "com.android.permissioncontroller:id/permission_allow_button",
                "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
                "com.google.android.permissioncontroller:id/permission_allow_button",
            ),
            "deny": (
                "com.android.permissioncontroller:id/permission_deny_button",
                "com.android.permissioncontroller:id/permission_deny_and_dont_ask_again_button",
                "com.google.android.permissioncontroller:id/permission_deny_button",
            ),
        }[action]
        visible_labels = {
            "allow": ("Allow", "While using the app", "Only this time", "允许", "仅在使用期间允许", "仅此一次"),
            "deny": ("Don't allow", "Deny", "不允许", "拒绝"),
        }[action]
        try:
            for resource_id in candidates:
                try:
                    self.driver.find_element(self._by.ID, resource_id).click()
                    time.sleep(self.cfg["appium"]["page_wait_seconds"])
                    return
                except Exception:
                    continue
            # Android 15's permission UI varies by image/OEM and sometimes
            # exposes only visible Compose text rather than a stable resource
            # id.  The labels are from the current system dialog, never from
            # LLM output, so this remains a deterministic platform action.
            for label in visible_labels:
                try:
                    selector = f"new UiSelector().text({json.dumps(label)})"
                    self.driver.find_element(self._by.ANDROID_UIAUTOMATOR, selector).click()
                    time.sleep(self.cfg["appium"]["page_wait_seconds"])
                    return
                except Exception:
                    continue
            if action == "deny":
                # Android localises apostrophes (Don't/Don’t) and some images
                # expose only Compose text.  A restrictive deny-only regex is
                # safer than matching a generic "allow" label.
                try:
                    selector = f"new UiSelector().textMatches({json.dumps(r'(?i)don.?t allow')})"
                    self.driver.find_element(self._by.ANDROID_UIAUTOMATOR, selector).click()
                    time.sleep(self.cfg["appium"]["page_wait_seconds"])
                    return
                except Exception:
                    pass
                # Last-resort dismissal does not grant the permission and is
                # preferable to failing the complete audit on OEM wording.
                try:
                    self.driver.back()
                    time.sleep(self.cfg["appium"]["page_wait_seconds"])
                    return
                except Exception:
                    pass
            raise ExplorationError(f"未找到 Android 权限{action}按钮")
        except ExplorationError:
            raise
        except Exception as exc:
            raise ExplorationError(f"处理 Android 权限弹窗失败：{exc}") from exc

    def close(self) -> None:
        """Best-effort session cleanup that never hides the audit failure.

        When an AVD is rebooting, Appium can fail while restoring its hidden
        API policy because Android's ``settings`` service is temporarily not
        registered.  That is useful diagnostic context, but it occurs in a
        ``finally`` block and must not replace the original page/automation
        exception that caused the session to end.
        """
        self.last_cleanup_error = ""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as exc:
                self.last_cleanup_error = _compact_appium_error(exc)
            finally:
                self.driver = None


def _is_settings_startup_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "settings app is not running" in message or "io.appium.settings" in message


def _is_uiautomator_startup_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        isinstance(exc, ConnectionResetError)
        or "instrumentation process" in message
        or "uiautomator2" in message
        or "connection reset" in message
        or "connection aborted" in message
        or "远程主机强迫关闭" in message
        or _is_settings_startup_error(exc)
    )


def _is_runtime_session_disconnect(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in (
        "could not retrieve the currently focused package and activity",
        "could not proxy command to the remote server",
        "cannot be proxied to uiautomator2",
        "instrumentation process is not running",
        "socket hang up",
        "uiautomator2 server is not running",
        "root accessibilitynodeinfo",
    ))


def _compact_appium_error(exc: Exception | None) -> str:
    message = str(exc or "未知错误").splitlines()[0].strip()
    return message[:500]


_DOCUMENT_SPAN_INSTRUCTION_CUES = ("请勾选", "勾选阅读", "请阅读并同意")
_DOCUMENT_TITLE_RE = re.compile(r"《([^》]{2,16})》")
_DOCUMENT_TITLE_HINTS = ("协议", "政策", "条款", "目录", "隐私", "服务", "sdk")


def _document_span_host_sort_key(text: str, compact_target: str, checkable: bool, class_name: str) -> tuple:
    compact = re.sub(r"\s+", "", text or "")
    class_name = str(class_name or "").lower()
    penalty = 0
    if checkable or "checkbox" in class_name or "compoundbutton" in class_name:
        penalty += 100_000
    if "button" in class_name:
        penalty += 50_000
    if any(cue in compact for cue in _DOCUMENT_SPAN_INSTRUCTION_CUES) or (
        "阅读并同意" in compact and len(compact) < 80
    ):
        penalty += 80_000
    compact_target = re.sub(r"\s+", "", compact_target or "")
    exact = bool(compact_target) and compact.lower() in {compact_target.lower(), compact_target.strip("《》").lower()}
    return (penalty, 0 if exact else 1, -len(compact) if compact else 0)


def _ordered_document_titles(text: str) -> list[str]:
    titles: list[str] = []
    for match in _DOCUMENT_TITLE_RE.finditer(str(text or "")):
        inner = match.group(1)
        if any(hint.lower() in inner.lower() for hint in _DOCUMENT_TITLE_HINTS):
            titles.append(match.group(0))
    return titles


def _luma(color: tuple[int, int, int]) -> float:
    r, g, b = color
    return 0.299 * r + 0.587 * g + 0.114 * b


def _chroma(color: tuple[int, int, int]) -> int:
    return max(color) - min(color)


def _color_dist(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1]) + abs(left[2] - right[2])


def _is_background_pixel(color: tuple[int, int, int], background: tuple[int, int, int]) -> bool:
    if _color_dist(color, background) < 42:
        return True
    return _luma(background) >= 150 and _luma(color) >= 200 and _chroma(color) <= 24


def _is_styled_span_pixel(color: tuple[int, int, int], background: tuple[int, int, int]) -> bool:
    """True for accent-colored glyphs. Hue is irrelevant; body ink is low-chroma."""
    if _is_background_pixel(color, background):
        return False
    return _chroma(color) >= 28


def _crop_background(image) -> tuple[int, int, int]:
    width, height = image.size
    sample_w, sample_h = max(1, width // 4), max(1, height // 4)
    sample = image.resize((sample_w, sample_h))
    pixels = sample.load()
    buckets: dict[tuple[int, int, int], int] = {}
    for y in range(sample_h):
        for x in range(sample_w):
            pixel = pixels[x, y][:3]
            color = (pixel[0] // 16 * 16, pixel[1] // 16 * 16, pixel[2] // 16 * 16)
            buckets[color] = buckets.get(color, 0) + 1
    return max(
        ((color, count) for color, count in buckets.items() if _luma(color) >= 160),
        key=lambda item: item[1],
        default=((255, 255, 255), 0),
    )[0]


def _merge_span_runs(runs: list[tuple[int, int, int]]) -> list[tuple[int, int, int, int]]:
    clusters: list[list[int]] = []
    for x0, x1, y in runs:
        merged = False
        for cluster in clusters:
            if y <= cluster[3] + 4 and x1 >= cluster[0] - 10 and x0 <= cluster[2] + 10:
                cluster[0] = min(cluster[0], x0)
                cluster[1] = min(cluster[1], y)
                cluster[2] = max(cluster[2], x1)
                cluster[3] = max(cluster[3], y)
                cluster[4] += x1 - x0
                merged = True
                break
        if not merged:
            clusters.append([x0, y, x1, y, x1 - x0])
    boxes = []
    for min_x, min_y, max_x, max_y, count in clusters:
        box_w, box_h = max_x - min_x, max_y - min_y + 1
        if box_w < 16 or count < 12:
            continue
        boxes.append((min_x + box_w // 2, min_y + max(1, box_h // 3), box_w, box_h))
    boxes.sort(key=lambda item: (item[1], item[0]))
    return boxes


def _styled_span_clusters(image) -> list[tuple[int, int, int, int]]:
    """Locate in-paragraph links by accent contrast or underlines, not a fixed hue."""
    width, height = image.size
    pixels = image.load()
    background = _crop_background(image)
    accent_runs: list[tuple[int, int, int]] = []
    ink_runs: list[tuple[int, int, int]] = []
    for y in range(height):
        x = 0
        while x < width:
            color = pixels[x, y][:3]
            if _is_background_pixel(color, background):
                x += 1
                continue
            start = x
            if _is_styled_span_pixel(color, background):
                while x < width and _is_styled_span_pixel(pixels[x, y][:3], background):
                    x += 1
                if x - start >= 2:
                    accent_runs.append((start, x, y))
                    ink_runs.append((start, x, y))
                continue
            while (
                x < width
                and not _is_background_pixel(pixels[x, y][:3], background)
                and not _is_styled_span_pixel(pixels[x, y][:3], background)
            ):
                x += 1
            if x - start >= 2:
                ink_runs.append((start, x, y))
    clusters = _merge_span_runs(accent_runs)
    if clusters:
        return clusters
    return _underline_span_clusters(ink_runs, height)


def _underline_span_clusters(ink_runs: list[tuple[int, int, int]], height: int) -> list[tuple[int, int, int, int]]:
    """Same-color ClickableSpans still leave a thin underline under the title."""
    by_row: dict[int, list[tuple[int, int]]] = {}
    for x0, x1, y in ink_runs:
        by_row.setdefault(y, []).append((x0, x1))
    underline_runs: list[tuple[int, int, int]] = []
    for y, segments in by_row.items():
        thickness = 1
        for delta in range(1, 4):
            if y + delta in by_row:
                thickness += 1
            else:
                break
        if thickness > 4:
            continue
        above = any((y - delta) in by_row for delta in range(6, 18) if y - delta >= 0)
        below = any((y + delta) in by_row for delta in range(6, 16) if y + delta < height)
        if not above or below:
            continue
        for x0, x1 in segments:
            if x1 - x0 >= 16:
                underline_runs.append((x0, x1, y))
    return [
        (cx, max(0, cy - 8), width, height)
        for cx, cy, width, height in _merge_span_runs(underline_runs)
    ]


def _estimated_document_span_point(
    target: str, host_text: str, left: int, top: int, width: int, height: int, probe_i: int = 0,
) -> tuple[int, int] | None:
    text = str(host_text or "")
    compact_target = re.sub(r"\s+", "", target)
    if not text or not compact_target:
        return None
    index = re.sub(r"\s+", "", text).lower().find(compact_target.lower())
    if index < 0:
        index = text.lower().find(str(target).lower())
    if index < 0:
        return None
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    char_px = 42 if cjk > len(text) * 0.35 else 18
    char_px = max(18, min(char_px, max(18, width // 18)))
    cols = max(8, min(36, max(1, int(width * 0.92) // char_px)))
    line, col = divmod(index, cols)
    line_height = max(char_px + 8, int(char_px * 1.35))
    offsets = ((0.0, 0.0), (-0.10, 0.0), (0.10, 0.0), (0.0, -0.12), (0.0, 0.12))
    dx, dy = offsets[int(probe_i) % len(offsets)]
    x = left + int((col + max(1, len(compact_target)) / 2) * char_px + dx * width)
    y = top + int((line + 0.45) * line_height + dy * height)
    x = min(left + width - 4, max(left + 4, x))
    y = min(top + height - 4, max(top + 4, y))
    return x, y
