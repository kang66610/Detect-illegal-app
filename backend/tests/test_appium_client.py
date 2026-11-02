from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.ai_explorer.appium_client import AppiumClient, _document_span_host_sort_key, _styled_span_clusters
from agent.ai_explorer.android_device import AndroidDevice
from agent.ai_explorer.appium_service import AppiumService, _find_appium_executable


class _Driver:
    def __init__(self, installed=True):
        self.installed = installed
        self.calls = []

    def is_app_installed(self, package):
        self.calls.append(("is_app_installed", package))
        return self.installed

    def remove_app(self, package):
        self.calls.append(("remove_app", package))
        self.installed = False

    def install_app(self, path):
        self.calls.append(("install_app", path))

    def terminate_app(self, package):
        self.calls.append(("terminate_app", package))

    def activate_app(self, package):
        self.calls.append(("activate_app", package))


def test_restart_app_terminates_background_process_before_activate():
    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _Driver()

    client.restart_app("com.example.demo")

    assert client.driver.calls == [
        ("terminate_app", "com.example.demo"),
        ("activate_app", "com.example.demo"),
    ]


def test_install_clears_existing_package_data_without_uninstalling(tmp_path):
    class _Device:
        def __init__(self):
            self.calls = []

        def clear_app_data(self, package):
            self.calls.append(("clear_app_data", package))

    device = _Device()
    client = AppiumClient({"appium": {"page_wait_seconds": 0}}, device=device)
    client.driver = _Driver(installed=True)
    apk_path = tmp_path / "demo.apk"
    apk_path.write_bytes(b"apk")

    assert client.install(apk_path, "com.example.demo") is True

    assert client.driver.calls == [
        ("is_app_installed", "com.example.demo"),
    ]
    assert device.calls == [("clear_app_data", "com.example.demo")]


def test_install_skips_uninstall_when_package_is_absent(tmp_path):
    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _Driver(installed=False)
    apk_path = tmp_path / "demo.apk"
    apk_path.write_bytes(b"apk")

    assert client.install(apk_path, "com.example.demo") is False

    assert client.driver.calls == [
        ("is_app_installed", "com.example.demo"),
        ("install_app", str(apk_path)),
    ]


def test_close_never_masks_the_primary_detection_error_when_appium_cleanup_fails():
    class _FailingQuitDriver:
        def quit(self):
            raise RuntimeError("settings service is temporarily unavailable")

    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _FailingQuitDriver()

    client.close()

    assert client.driver is None
    assert "settings service" in client.last_cleanup_error


def test_android_device_reconnects_local_emulator_when_adb_serial_changes():
    calls = []
    snapshots = [
        "List of devices attached\n",
        "List of devices attached\n127.0.0.1:5555\tdevice product:sdk_gphone64_x86_64\n",
    ]

    def runner(args):
        calls.append(list(args))
        if args == ["devices", "-l"]:
            return snapshots.pop(0)
        if args == ["connect", "127.0.0.1:5555"]:
            return "connected to 127.0.0.1:5555"
        return ""

    device = AndroidDevice({"udid": "emulator-5554"}, runner=runner)

    assert device.resolve_udid() == "127.0.0.1:5555"
    assert device.udid == "127.0.0.1:5555"
    assert ["connect", "127.0.0.1:5555"] in calls


def test_android_device_rejects_ambiguous_or_missing_physical_target():
    device = AndroidDevice(
        {"udid": "R9T123"},
        runner=lambda args: "List of devices attached\nother-device\tdevice\n"
        if args == ["devices", "-l"] else "",
    )

    with pytest.raises(RuntimeError, match="配置设备 R9T123 不可用"):
        device.resolve_udid()


def test_runtime_activity_disconnect_recovers_one_local_avd_session_without_reinstalling_the_app():
    """A rebooting AVD drops getCurrentActivity mid-traversal, not just at startup."""
    calls = []

    class _RecoveringDevice:
        udid = "emulator-5554"

        def wait_until_ready(self, timeout_seconds):
            calls.append(("wait", timeout_seconds))
            return True

        def recover_uiautomator2(self):
            calls.append(("recover_uiautomator2",))

    client = AppiumClient(
        {"appium": {"udid": "emulator-5554", "auto_recover": True,
                    "uiautomator2_reboot_timeout_seconds": 30}},
        device=_RecoveringDevice(),
    )
    client.driver = object()
    client.close = lambda: calls.append(("close",))
    client.connect = lambda: calls.append(("connect",))
    client.activate = lambda package: calls.append(("activate", package))

    assert client.recover_runtime_session("com.example.demo", RuntimeError(
        "Could not retrieve the currently focused package and activity"
    )) is True
    assert calls == [
        ("close",), ("wait", 30), ("recover_uiautomator2",),
        ("connect",), ("activate", "com.example.demo"),
    ]


def test_runtime_instrumentation_crash_recovers_on_physical_device_without_waiting_for_boot():
    calls = []

    class _PhysicalDevice:
        udid = "R9T123"

        def wait_until_ready(self, timeout_seconds):
            calls.append(("wait", timeout_seconds))
            return True

        def recover_uiautomator2(self):
            calls.append(("recover_uiautomator2",))

    client = AppiumClient(
        {"appium": {"udid": "R9T123", "auto_recover": True,
                    "uiautomator2_reboot_timeout_seconds": 30}},
        device=_PhysicalDevice(),
    )
    client.driver = object()
    client.close = lambda: calls.append(("close",))
    client.connect = lambda: calls.append(("connect",))
    client.activate = lambda package: calls.append(("activate", package))

    assert client.recover_runtime_session("com.example.demo", RuntimeError(
        "cannot be proxied to UiAutomator2: instrumentation process is not running"
    )) is True
    assert calls == [
        ("close",), ("recover_uiautomator2",),
        ("connect",), ("activate", "com.example.demo"),
    ]


def test_runtime_recovery_honors_termination_while_waiting_for_avd():
    """A user termination must interrupt the long AVD boot wait promptly."""
    calls = []

    class _CancelableDevice:
        udid = "emulator-5554"

        def wait_until_ready(self, timeout_seconds, *, should_stop=None):
            calls.append(("wait", timeout_seconds, should_stop is not None))
            return not (should_stop and should_stop())

        def recover_uiautomator2(self):
            calls.append(("recover_uiautomator2",))

    stop_calls = 0

    def should_stop():
        nonlocal stop_calls
        stop_calls += 1
        # The request arrives while wait_until_ready is polling, not before
        # the recovery transaction starts.
        return stop_calls >= 3

    client = AppiumClient(
        {"appium": {"udid": "emulator-5554", "auto_recover": True,
                    "uiautomator2_reboot_timeout_seconds": 120}},
        device=_CancelableDevice(),
    )
    client.driver = object()
    client.close = lambda: calls.append(("close",))

    assert client.recover_runtime_session(
        "com.example.demo",
        RuntimeError("Could not retrieve the currently focused package and activity"),
        should_stop=should_stop,
    ) is False
    assert calls == [("close",), ("wait", 120, True)]


def test_wait_until_ready_requires_stable_android_services_after_boot():
    calls = []

    def runner(args):
        calls.append(args)
        if args == ["shell", "getprop", "sys.boot_completed"]:
            return "1"
        if args == ["shell", "settings", "get", "global", "airplane_mode_on"]:
            return "1"
        if args == ["shell", "pidof", "system_server"]:
            return "4761"
        return ""

    device = AndroidDevice(
        {
            "udid": "emulator-5554",
            "auto_recover": False,
            "wait_for_android_services": True,
            "android_service_ready_checks": 2,
        },
        runner=runner,
        sleeper=lambda _seconds: None,
        clock=iter([0, 0, 1, 1]).__next__,
    )

    assert device.wait_until_ready(15) is True
    assert calls.count(["shell", "settings", "get", "global", "airplane_mode_on"]) == 2
    assert calls.count(["shell", "pidof", "system_server"]) == 2


def test_wait_until_ready_stops_before_polling_when_requested():
    calls = []

    def runner(args):
        calls.append(args)
        return "0"

    device = AndroidDevice(
        {"udid": "emulator-5554", "auto_recover": False},
        runner=runner,
        sleeper=lambda _seconds: None,
    )

    assert device.wait_until_ready(120, should_stop=lambda: True) is False
    assert calls == []


def test_relative_customer_service_recipe_clicks_only_inside_the_visible_screen():
    class _GestureDriver:
        def __init__(self):
            self.gestures = []

        def get_window_size(self):
            return {"width": 1080, "height": 2400}

        def execute_script(self, name, args):
            self.gestures.append((name, args))

    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _GestureDriver()

    client.perform({"action": "click", "target": "relative:0.50,0.88"})

    assert client.driver.gestures == [("mobile: clickGesture", {"x": 540, "y": 2112})]


def test_document_span_click_prefers_body_paragraph_over_checkbox_caption():
    class _El:
        def __init__(self, text, rect, checkable="false", class_name="android.widget.TextView"):
            self.text = text
            self._rect = rect
            self._checkable = checkable
            self._class_name = class_name

        def get_attribute(self, name):
            if name in ("className", "class"):
                return self._class_name
            if name == "checkable":
                return self._checkable
            return ""

        @property
        def rect(self):
            return self._rect

        def click(self):
            raise AssertionError("should tap the body ClickableSpan, not the checkbox caption")

    body = _El(
        "你可阅读《服务协议》、《隐私政策》和《第三方SDK目录》了解详细信息。请审慎阅读全部条款后再决定是否同意。",
        {"x": 80, "y": 360, "width": 920, "height": 220},
    )
    caption = _El(
        "请勾选阅读并同意《服务协议》、《隐私政策》和《第三方SDK目录》",
        {"x": 140, "y": 610, "width": 820, "height": 70},
    )

    class _Driver:
        def __init__(self):
            self.gestures = []

        def find_elements(self, _by, _selector):
            return [caption, body]

        def execute_script(self, name, args):
            self.gestures.append((name, args))

        def get_screenshot_as_png(self):
            raise RuntimeError("no screenshot in this unit test")

    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _Driver()
    client._by = SimpleNamespace(ANDROID_UIAUTOMATOR="uiautomator")
    client._click_text_contains_preferring_document_span("《隐私政策》")
    assert len(client.driver.gestures) == 1
    point = client.driver.gestures[0][1]
    assert 80 <= point["x"] <= 1000
    assert 360 <= point["y"] <= 580
    body_key = _document_span_host_sort_key(body.text, "《隐私政策》", False, "android.widget.TextView")
    caption_key = _document_span_host_sort_key(caption.text, "《隐私政策》", False, "android.widget.TextView")
    assert body_key < caption_key


def test_document_span_click_uses_styled_link_pixels_regardless_of_hue():
    from io import BytesIO
    from PIL import Image, ImageDraw

    class _El:
        text = "你可阅读《服务协议》、《隐私政策》和《第三方SDK目录》了解详细信息。"

        def get_attribute(self, name):
            if name in ("className", "class"):
                return "android.widget.TextView"
            if name == "checkable":
                return "false"
            return ""

        @property
        def rect(self):
            return {"x": 100, "y": 200, "width": 600, "height": 120}

    class _Driver:
        def __init__(self, accent):
            self.gestures = []
            image = Image.new("RGB", (800, 400), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((120, 210, 380, 228), fill=(40, 40, 40))
            draw.rectangle((130, 220, 250, 250), fill=accent)
            draw.rectangle((280, 220, 400, 250), fill=accent)
            draw.rectangle((430, 220, 580, 250), fill=accent)
            output = BytesIO()
            image.save(output, format="PNG")
            self.png = output.getvalue()

        def find_elements(self, _by, _selector):
            return [_El()]

        def execute_script(self, name, args):
            self.gestures.append((name, args))

        def get_screenshot_as_png(self):
            return self.png

        def get_window_size(self):
            return {"width": 800, "height": 400}

    for accent in ((16, 160, 90), (220, 110, 24), (40, 140, 200), (160, 80, 200)):
        client = AppiumClient({"appium": {"page_wait_seconds": 0}})
        client.driver = _Driver(accent)
        client._by = SimpleNamespace(ANDROID_UIAUTOMATOR="uiautomator")
        client._click_text_contains_preferring_document_span("《隐私政策》")
        assert client.driver.gestures[0][1]["x"] == 340
        assert 220 <= client.driver.gestures[0][1]["y"] <= 250


def test_styled_span_clusters_fall_back_to_underlines_when_links_match_body_color():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (600, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 30, 160, 58), fill=(40, 40, 40))
    draw.rectangle((200, 30, 320, 58), fill=(40, 40, 40))
    draw.rectangle((360, 30, 520, 58), fill=(40, 40, 40))
    draw.rectangle((40, 62, 160, 64), fill=(40, 40, 40))
    draw.rectangle((200, 62, 320, 64), fill=(40, 40, 40))
    draw.rectangle((360, 62, 520, 64), fill=(40, 40, 40))
    clusters = _styled_span_clusters(image)
    assert len(clusters) == 3
    assert 190 <= clusters[1][0] <= 330


def test_document_span_click_sends_one_gesture_not_a_spray():
    class _El:
        text = "请勾选阅读并同意《服务协议》《隐私政策》和《第三方SDK目录》后进入应用。"

        def get_attribute(self, name):
            if name in ("className", "class"):
                return "android.widget.TextView"
            if name == "checkable":
                return "false"
            return ""

        @property
        def rect(self):
            return {"x": 80, "y": 400, "width": 920, "height": 240}

    class _Driver:
        def __init__(self):
            self.gestures = []

        def find_elements(self, _by, _selector):
            return [_El()]

        def execute_script(self, name, args):
            self.gestures.append((name, args))

    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _Driver()
    client._by = SimpleNamespace(ANDROID_UIAUTOMATOR="uiautomator")
    client._click_text_contains_preferring_document_span("《隐私政策》")
    assert len(client.driver.gestures) == 1
    assert client.driver.gestures[0][0] == "mobile: clickGesture"


def test_document_body_blank_check_ignores_status_bar_and_document_header():
    from io import BytesIO
    from PIL import Image, ImageDraw

    class _ScreenshotDriver:
        def __init__(self, has_body_content):
            image = Image.new("RGB", (1080, 2400), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 1080, 280), fill="#36c58b")
            if has_body_content:
                draw.rectangle((140, 520, 900, 800), fill="#333333")
            output = BytesIO(); image.save(output, format="PNG")
            self.png = output.getvalue()

        def get_screenshot_as_png(self):
            return self.png

    blank = AppiumClient({"appium": {"page_wait_seconds": 0}})
    blank.driver = _ScreenshotDriver(has_body_content=False)
    filled = AppiumClient({"appium": {"page_wait_seconds": 0}})
    filled.driver = _ScreenshotDriver(has_body_content=True)

    assert blank.document_body_is_blank() is True
    assert filled.document_body_is_blank() is False


def test_blank_document_scroll_does_not_treat_a_changing_clock_as_progress():
    """A WebView clock/status-bar update must never satisfy reading progress."""
    from io import BytesIO
    from PIL import Image, ImageDraw

    class _VolatileClockDriver:
        def __init__(self):
            image = Image.new("RGB", (1080, 2400), "white")
            ImageDraw.Draw(image).rectangle((0, 0, 1080, 280), fill="#36c58b")
            output = BytesIO(); image.save(output, format="PNG")
            self.png = output.getvalue()
            self.clock = 0

        @property
        def page_source(self):
            self.clock += 1
            return f'<node text="09:{self.clock:02d}" content-desc="09:{self.clock:02d}" />'

        def get_screenshot_as_png(self):
            return self.png

        def get_window_size(self):
            return {"width": 1080, "height": 2400}

        def execute_script(self, _name, _args):
            return None

        def swipe(self, *_args, **_kwargs):
            return None

    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _VolatileClockDriver()

    assert client.scroll_down() is False
    assert client.scroll_document_down() == "stuck"


def test_document_scroll_exposes_driver_confirmed_bottom_separately_from_a_stall():
    class _BottomDriver:
        page_source = '<node text="隐私政策页尾" />'

        def get_screenshot_as_png(self):
            return b"not-an-image"

        def get_window_size(self):
            return {"width": 1080, "height": 2400}

        def execute_script(self, _name, _args):
            return False

        def swipe(self, *_args, **_kwargs):
            return None

    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _BottomDriver()

    assert client.scroll_document_down() == "bottom"


def test_appium_service_starts_local_server_when_auto_start_enabled():
    checks = iter([False, False, True])
    starts = []
    service = AppiumService(
        {
            "server_url": "http://127.0.0.1:4725",
            "auto_start": True,
            "startup_timeout_seconds": 2,
        },
        probe=lambda: next(checks),
        starter=lambda: starts.append("started"),
        sleeper=lambda _seconds: None,
    )

    assert service.ensure_ready() is True
    assert starts == ["started"]


def test_appium_service_start_enables_only_session_discovery_for_local_cleanup(monkeypatch, tmp_path):
    import agent.ai_explorer.appium_service as appium_service

    calls = []
    monkeypatch.setattr(appium_service.shutil, "which", lambda _name: "npx.cmd")
    monkeypatch.setattr(appium_service.subprocess, "Popen", lambda command, **_kwargs: calls.append(command))

    service = AppiumService({
        "server_url": "http://127.0.0.1:4725",
        "server_log_path": str(tmp_path / "appium.log"),
    })
    service.start()

    assert calls
    assert calls[0][calls[0].index("--allow-insecure"):calls[0].index("--allow-insecure") + 2] == [
        "--allow-insecure", "*:session_discovery",
    ]


def test_appium_service_starts_with_session_override_to_replace_orphan_session(monkeypatch, tmp_path):
    import agent.ai_explorer.appium_service as appium_service

    calls = []
    monkeypatch.setattr(appium_service.shutil, "which", lambda _name: "npx.cmd")
    monkeypatch.setattr(appium_service.subprocess, "Popen", lambda command, **_kwargs: calls.append(command))

    AppiumService({
        "server_url": "http://127.0.0.1:4725",
        "server_log_path": str(tmp_path / "appium.log"),
    }).start()

    assert "--session-override" in calls[0]


def test_appium_executable_resolver_uses_newest_npx_cache_without_downloading(monkeypatch, tmp_path):
    import agent.ai_explorer.appium_service as appium_service

    monkeypatch.setattr(appium_service.shutil, "which", lambda _name: None)
    monkeypatch.setenv("npm_config_cache", str(tmp_path))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    old = tmp_path / "_npx" / "old" / "node_modules" / ".bin" / "appium.cmd"
    new = tmp_path / "_npx" / "new" / "node_modules" / ".bin" / "appium.cmd"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    old.touch()
    new.touch()

    assert _find_appium_executable() == str(new)


def test_appium_service_does_not_start_when_disabled():
    service = AppiumService(
        {"server_url": "http://127.0.0.1:4725", "auto_start": False},
        probe=lambda: False,
        sleeper=lambda _seconds: None,
    )

    assert service.ensure_ready() is False


def test_appium_service_never_starts_a_remote_endpoint():
    starts = []
    service = AppiumService(
        {"server_url": "http://device-farm.example:4725", "auto_start": True},
        probe=lambda: False,
        starter=lambda: starts.append("started"),
        sleeper=lambda _seconds: None,
    )

    assert service.ensure_ready() is False
    assert starts == []


def test_appium_service_cleans_stale_loopback_sessions(monkeypatch):
    """An orphan POST /session must not outlive and kill the next session."""
    import json
    import agent.ai_explorer.appium_service as appium_service

    calls = []

    class _Response:
        def __init__(self, payload=b"{}"):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout):
        calls.append((request.method, request.full_url, timeout))
        if request.method == "GET":
            return _Response(json.dumps({"value": [{"id": "orphan-1"}]}).encode())
        return _Response()

    monkeypatch.setattr(appium_service, "urlopen", fake_urlopen)
    service = AppiumService({"server_url": "http://127.0.0.1:4725"})

    assert service.cleanup_sessions() == 1
    assert calls == [
        ("GET", "http://127.0.0.1:4725/appium/sessions", 2),
        ("DELETE", "http://127.0.0.1:4725/session/orphan-1", 5),
    ]


def test_appium_service_falls_back_to_legacy_session_discovery(monkeypatch):
    import agent.ai_explorer.appium_service as appium_service

    calls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"value": []}'

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith("/appium/sessions"):
            raise OSError("404")
        return _Response()

    monkeypatch.setattr(appium_service, "urlopen", fake_urlopen)
    service = AppiumService({"server_url": "http://127.0.0.1:4725"})

    assert service.cleanup_sessions() == 0
    assert calls == [
        "http://127.0.0.1:4725/appium/sessions",
        "http://127.0.0.1:4725/sessions",
    ]


def test_local_emulator_preflight_requests_adb_root_once():
    calls = []
    device = AndroidDevice(
        {"udid": "emulator-5554", "auto_recover": True},
        runner=lambda args: calls.append(args) or "restarting adbd as root",
    )

    device.prepare()

    assert calls == [["root"]]


def test_android_device_resolve_udid_disconnects_duplicate_ipv6_transport():
    calls = []

    def runner(args):
        calls.append(args)
        if args == ["devices", "-l"]:
            return (
                "List of devices attached\n"
                "127.0.0.1:5555 device product:sdk_gphone64_x86_64\n"
                "[::1]:5555 device product:sdk_gphone64_x86_64\n"
            )
        return ""

    device = AndroidDevice({"udid": "127.0.0.1:5555"}, runner=runner)

    assert device.resolve_udid() == "127.0.0.1:5555"
    assert ["disconnect", "[::1]:5555"] in calls


def test_android_device_resolve_udid_disconnects_aliases_when_configured_as_emulator_serial():
    calls = []

    def runner(args):
        calls.append(args)
        if args == ["devices", "-l"]:
            return (
                "List of devices attached\n"
                "127.0.0.1:5555 device product:sdk_gphone64_x86_64\n"
                "[::1]:5555 device product:sdk_gphone64_x86_64\n"
            )
        return ""

    device = AndroidDevice({"udid": "emulator-5554"}, runner=runner)

    assert device.resolve_udid() == "127.0.0.1:5555"
    assert ["disconnect", "[::1]:5555"] in calls


def test_local_emulator_preflight_enables_installed_webview_provider():
    calls = []

    def runner(args):
        calls.append(args)
        if args == ["shell", "pm", "path", "com.google.android.webview"]:
            return "package:/data/app/com.google.android.webview/base.apk"
        return ""

    device = AndroidDevice({
        "udid": "127.0.0.1:5555", "auto_recover": True,
        "ensure_appium_helpers": True, "ensure_webview_provider": True,
    }, runner=runner)

    device.prepare()

    assert ["shell", "pm", "enable", "com.google.android.webview"] in calls
    assert ["shell", "settings", "put", "global", "webview_provider", "com.google.android.webview"] in calls


def test_android_device_clear_app_data_keeps_package_installed():
    calls = []
    device = AndroidDevice(
        {"udid": "emulator-5554"},
        runner=lambda args: calls.append(args) or "Success\n",
    )

    assert device.clear_app_data("com.example.demo") is True
    assert calls == [["shell", "pm", "clear", "com.example.demo"]]


def test_android_device_clear_app_data_reports_pm_failure():
    device = AndroidDevice(
        {"udid": "emulator-5554"},
        runner=lambda _args: "Failed\n",
    )

    import pytest
    with pytest.raises(RuntimeError, match="pm clear failed"):
        device.clear_app_data("com.example.demo")


def test_local_avd_preflight_enables_helpers_and_android15_location_permissions():
    calls = []
    device = AndroidDevice(
        {
            "udid": "emulator-5554",
            "auto_recover": True,
            "ensure_appium_helpers": True,
        },
        runner=lambda args: calls.append(args) or "",
    )

    device.prepare()

    assert ["root"] in calls
    assert ["shell", "pm", "enable", "io.appium.settings"] in calls
    assert [
        "shell",
        "pm",
        "grant",
        "io.appium.settings",
        "android.permission.ACCESS_FINE_LOCATION",
    ] in calls
    assert ["shell", "pm", "grant", "io.appium.settings", "android.permission.ACCESS_COARSE_LOCATION"] in calls
    assert ["shell", "pm", "grant", "io.appium.settings", "android.permission.POST_NOTIFICATIONS"] in calls
    assert any(call[:3] == ["shell", "am", "start"] and "io.appium.settings/.Settings" in call for call in calls)


def test_uiautomator_recovery_clears_helpers_without_uninstalling_them():
    calls = []
    device = AndroidDevice(
        {"udid": "emulator-5554", "auto_recover": True},
        runner=lambda args: calls.append(args) or "",
    )

    device.recover_uiautomator2()

    assert ["uninstall", "io.appium.uiautomator2.server"] not in calls
    assert calls == [
        ["root"],
        ["shell", "am", "force-stop", "io.appium.uiautomator2.server.test"],
        ["shell", "am", "force-stop", "io.appium.uiautomator2.server"],
        ["shell", "pkill", "-f", "uiautomator"],
        ["forward", "--remove-all"],
        ["shell", "pm", "clear", "io.appium.uiautomator2.server.test"],
        ["shell", "pm", "clear", "io.appium.uiautomator2.server"],
    ]


def test_uiautomator_recovery_on_physical_device_skips_root_but_still_clears_helpers():
    calls = []
    device = AndroidDevice(
        {"udid": "R9T123", "auto_recover": True},
        runner=lambda args: calls.append(args) or "",
    )

    device.recover_uiautomator2()

    assert ["root"] not in calls
    assert ["shell", "am", "force-stop", "io.appium.uiautomator2.server"] in calls
    assert ["shell", "pm", "clear", "io.appium.uiautomator2.server"] in calls


def test_opted_in_local_avd_reboot_waits_for_android_boot_and_restores_root():
    calls = []
    boot_values = iter(["", "1"])

    def runner(args):
        calls.append(args)
        if args == ["shell", "getprop", "sys.boot_completed"]:
            return next(boot_values)
        return ""

    device = AndroidDevice(
        {
            "udid": "emulator-5554",
            "auto_recover": True,
            "auto_reboot_on_uiautomator2_failure": True,
            "uiautomator2_reboot_timeout_seconds": 15,
        },
        runner=runner,
        sleeper=lambda _seconds: None,
        clock=iter([0, 0, 1, 1]).__next__,
    )

    assert device.reboot_after_uiautomator2_failure() is True
    assert calls == [
        ["reboot"],
        ["shell", "getprop", "sys.boot_completed"],
        ["shell", "getprop", "sys.boot_completed"],
        ["root"],
    ]


def test_uiautomator_reboot_is_never_available_for_physical_devices():
    calls = []
    device = AndroidDevice(
        {"udid": "R9T123", "auto_reboot_on_uiautomator2_failure": True},
        runner=lambda args: calls.append(args) or "1",
    )

    assert device.reboot_after_uiautomator2_failure() is False
    assert calls == []


def test_uiautomator_reboot_respects_local_avd_cooldown():
    calls = []
    device = AndroidDevice(
        {
            "udid": "emulator-cooldown-test",
            "auto_recover": True,
            "auto_reboot_on_uiautomator2_failure": True,
            "uiautomator2_reboot_timeout_seconds": 15,
            "uiautomator2_reboot_cooldown_seconds": 900,
        },
        runner=lambda args: calls.append(args) or "1",
        sleeper=lambda _seconds: None,
        clock=iter([0, 0]).__next__,
        wall_clock=lambda: 100,
    )

    assert device.reboot_after_uiautomator2_failure() is True
    assert device.reboot_after_uiautomator2_failure() is False
    assert calls.count(["reboot"]) == 1


def test_local_root_avd_starts_missing_frida_server_and_waits_for_pid():
    calls = []
    pid_checks = iter(["", "6339"])

    def runner(args):
        calls.append(args)
        if args == ["shell", "pidof", "frida-server"]:
            return next(pid_checks)
        return ""

    device = AndroidDevice(
        {"udid": "emulator-5554", "auto_recover": True},
        runner=runner,
        sleeper=lambda _seconds: None,
        clock=iter([0, 0, 1]).__next__,
    )

    assert device.ensure_frida_server("/data/local/tmp/frida-server", startup_timeout_seconds=3) is True
    assert calls == [
        ["root"],
        ["shell", "pidof", "frida-server"],
        ["shell", "nohup /data/local/tmp/frida-server >/data/local/tmp/frida-server.log 2>&1 &"],
        ["shell", "pidof", "frida-server"],
    ]


def test_frida_server_is_never_auto_started_on_a_physical_device():
    calls = []
    device = AndroidDevice(
        {"udid": "R9T123", "auto_recover": True},
        runner=lambda args: calls.append(args) or "",
    )

    assert device.ensure_frida_server("/data/local/tmp/frida-server") is False
    assert calls == []


def test_permission_denial_uses_visible_button_text_when_android_15_has_no_stable_id():
    class _Button:
        def __init__(self):
            self.clicked = False

        def click(self):
            self.clicked = True

    class _DriverWithTextOnlyPermissionButton:
        def __init__(self):
            self.button = _Button()

        def find_element(self, by, value):
            if by == "uia" and "Don't allow" in value:
                return self.button
            raise RuntimeError("resource id unavailable")

    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _DriverWithTextOnlyPermissionButton()
    client._by = SimpleNamespace(ID="id", ANDROID_UIAUTOMATOR="uia")

    client.respond_to_permission("deny")

    assert client.driver.button.clicked


def test_permission_denial_matches_android_15_curly_apostrophe_and_never_aborts_when_text_is_unknown():
    class _Button:
        def __init__(self):
            self.clicked = False

        def click(self):
            self.clicked = True

    class _CurlyTextDriver:
        def __init__(self):
            self.button = _Button()
            self.backed = False

        def find_element(self, by, value):
            if by == "uia" and "textMatches" in value and "don.?t allow" in value:
                return self.button
            raise RuntimeError("no fixed id")

        def back(self):
            self.backed = True

    client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    client.driver = _CurlyTextDriver()
    client._by = SimpleNamespace(ID="id", ANDROID_UIAUTOMATOR="uia")

    client.respond_to_permission("deny")

    assert client.driver.button.clicked
    assert not client.driver.backed

    class _UnknownPermissionDriver(_CurlyTextDriver):
        def find_element(self, _by, _value):
            raise RuntimeError("unknown OEM wording")

    fallback_client = AppiumClient({"appium": {"page_wait_seconds": 0}})
    fallback_client.driver = _UnknownPermissionDriver()
    fallback_client._by = SimpleNamespace(ID="id", ANDROID_UIAUTOMATOR="uia")

    fallback_client.respond_to_permission("deny")

    assert fallback_client.driver.backed


def test_recent_app_crash_extracts_native_library_failure_from_logcat():
    logcat = """E AndroidRuntime: FATAL EXCEPTION: main
E AndroidRuntime: Process: com.example.socialsecurity, PID: 1234
E AndroidRuntime: java.lang.UnsatisfiedLinkError: dlopen failed: library /data/user/0/com.example.socialsecurity/files/libexec.so not found
"""
    device = AndroidDevice(
        {"udid": "emulator-5554", "auto_recover": True},
        runner=lambda _args: logcat,
    )

    reason = device.recent_app_crash("com.example.socialsecurity")

    assert reason is not None
    assert "UnsatisfiedLinkError" in reason
    assert "libexec.so" in reason


def test_adb_output_decoding_tolerates_non_gbk_bytes(monkeypatch):
    captured = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(stdout="decoded output", stderr="")

    monkeypatch.setattr("agent.ai_explorer.android_device.subprocess.run", _fake_run)
    device = AndroidDevice({"udid": "emulator-5554", "adb_path": "adb"})

    assert device._runner(["logcat", "-d", "-t", "10"]) == "decoded output"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_settings_app_timeout_is_a_session_startup_error():
    from agent.ai_explorer.appium_client import _is_uiautomator_startup_error

    assert _is_uiautomator_startup_error(
        RuntimeError("Message: Appium Settings app is not running after 30000ms")
    )


def test_connection_reset_during_session_creation_is_retryable_uiautomator_failure():
    from agent.ai_explorer.appium_client import _is_uiautomator_startup_error

    assert _is_uiautomator_startup_error(
        ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接")
    )


def test_accessibility_root_timeout_is_a_recoverable_runtime_session_disconnect():
    from agent.ai_explorer.appium_client import _is_runtime_session_disconnect

    assert _is_runtime_session_disconnect(RuntimeError(
        "Timed out after 10121ms waiting for the root AccessibilityNodeInfo in the active window"
    ))


def test_connect_retries_settings_timeout_without_helper_initialization(monkeypatch):
    import sys
    import types

    from agent.ai_explorer import appium_client as client_mod

    caps_seen = []
    recover_calls = []

    class _Options:
        def load_capabilities(self, caps):
            caps_seen.append(dict(caps))
            return self

    class _Remote:
        def __init__(self, _url, options=None):
            if not caps_seen[-1].get("appium:skipDeviceInitialization"):
                raise RuntimeError("Message: Appium Settings app is not running after 30000ms")

    monkeypatch.setitem(sys.modules, "appium", types.SimpleNamespace(webdriver=types.SimpleNamespace(Remote=_Remote)))
    monkeypatch.setitem(sys.modules, "appium.webdriver", types.SimpleNamespace(Remote=_Remote))
    monkeypatch.setitem(sys.modules, "appium.options.android", types.SimpleNamespace(UiAutomator2Options=lambda: _Options()))
    monkeypatch.setitem(sys.modules, "appium.webdriver.common.appiumby", types.SimpleNamespace(AppiumBy="By"))
    monkeypatch.setattr(
        client_mod,
        "AppiumService",
        lambda _cfg: types.SimpleNamespace(ensure_ready=lambda: True, cleanup_sessions=lambda: 0),
    )

    device = types.SimpleNamespace(
        resolve_udid=lambda: "127.0.0.1:5555",
        prepare=lambda: recover_calls.append("prepare"),
        recover_uiautomator2=lambda: recover_calls.append("recover"),
        reboot_after_uiautomator2_failure=lambda: False,
    )
    client = AppiumClient({
        "appium": {
            "server_url": "http://127.0.0.1:4725",
            "device_name": "Pixel_7",
            "no_reset": False,
            "new_command_timeout_seconds": 600,
            "platform_version": "",
            "udid": "emulator-5554",
            "skip_device_initialization": False,
            "ignore_hidden_api_policy_error": True,
            "uiautomator2_server_launch_timeout_seconds": 90,
            "session_retries": 2,
            "auto_reboot_on_uiautomator2_failure": False,
        },
    }, device=device)

    client.connect()

    assert recover_calls == ["prepare", "recover"]
    assert caps_seen[0]["appium:skipDeviceInitialization"] is False
    assert caps_seen[0]["appium:udid"] == "127.0.0.1:5555"
    assert caps_seen[1]["appium:skipDeviceInitialization"] is True
    assert client.driver is not None
