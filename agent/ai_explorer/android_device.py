"""Small, explicit recovery layer for a local Android emulator.

Normal recovery only touches Appium's helper packages and ADB forwards.  A
single no-wipe AVD reboot is available as an explicit opt-in after that softer
recovery has already failed; physical devices are never rebooted.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from collections.abc import Callable
from pathlib import Path


_UIA_PACKAGES = (
    "io.appium.uiautomator2.server.test",
    "io.appium.uiautomator2.server",
)
_APPIUM_HELPER_PACKAGES = ("io.appium.settings", *_UIA_PACKAGES)
_WEBVIEW_PROVIDER_PACKAGES = (
    "com.google.android.webview",
    "com.android.webview",
)
# Phone/location are granted only in the later SDK-observation phase.
# First-run permission dialogs (2.2 / 4.1 / 4.2) need them denied.
_KEEP_FOR_COLLECTION_OBSERVABILITY = (
    "android.permission.READ_PHONE_STATE",
    "android.permission.READ_PHONE_NUMBERS",
    "android.permission.READ_PRIVILEGED_PHONE_STATE",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.ACCESS_BACKGROUND_LOCATION",
    "android.permission.BLUETOOTH_SCAN",
    "android.permission.BLUETOOTH_CONNECT",
    "android.permission.NEARBY_WIFI_DEVICES",
)

# Android 15 enforces the runtime location prerequisite for Appium Settings'
# location-typed foreground service.  Appium normally asks the device to
# grant these while creating a session, but a previously installed helper can
# retain a denied state after a failed session or an AVD snapshot restore.
# Granting only Appium's own helper permissions on an opted-in local emulator
# makes the preflight deterministic and never changes the audited app.
_APPIUM_SETTINGS_RUNTIME_PERMISSIONS = (
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.ACCESS_BACKGROUND_LOCATION",
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_LOCATION",
)

# An AVD reboot is effective when Android's instrumentation bookkeeping is
# wedged, but repeating it for every task makes the test device unusable.  The
# worker is single-process, so an in-memory, per-device cooldown is sufficient
# to protect a running audit queue without ever affecting a physical device.
_UIA_REBOOT_COOLDOWNS: dict[str, float] = {}


def is_local_emulator_udid(udid: str) -> bool:
    """Return whether an ADB serial is a local emulator transport.

    Android may expose the same AVD as ``emulator-5554`` when it registers
    directly with ADB, or as ``127.0.0.1:5555``/``[::1]:5555`` after the ADB
    daemon is restarted and the emulator is reconnected over its console
    port.  Both forms are local and safe for the opt-in recovery operations;
    a physical or remote device must never be rebooted implicitly.
    """
    value = str(udid or "").strip().lower()
    if value.startswith("emulator-"):
        # Keep compatibility with existing emulator aliases used by tests and
        # local AVD wrappers; only the numeric form can be mapped to a TCP
        # console port below.
        return True
    return bool(re.fullmatch(r"(?:127\.0\.0\.1|localhost|\[::1\]):55\d{2}", value))


class AndroidDevice:
    def __init__(self, config: dict, *, runner=None, sleeper=time.sleep, clock=time.monotonic, wall_clock=time.time) -> None:
        self.config = config
        self._runner = runner or self._run
        self._custom_runner = runner is not None
        self._sleep = sleeper
        self._clock = clock
        self._wall_clock = wall_clock

    @property
    def udid(self) -> str:
        return str(self.config.get("udid") or "")

    @property
    def is_local_emulator(self) -> bool:
        return is_local_emulator_udid(self.udid)

    def resolve_udid(self) -> str:
        """Resolve a configured serial against the current ADB transports.

        AVDs normally appear as ``emulator-5554``.  If the ADB daemon is
        restarted independently, the same running emulator can instead be
        reachable as ``127.0.0.1:5555``.  Reconnect that local console port and
        adopt the resulting serial so Appium and Frida address one device.
        """
        configured = self.udid
        devices = self.list_devices()
        ready = [item["serial"] for item in devices if item["state"] == "device"]
        if configured and configured in ready:
            console_port = _emulator_console_port(configured)
            if console_port is not None:
                aliases = [
                    serial for serial in ready
                    if _same_emulator_transport(serial, console_port)
                ]
                return self._adopt_local_transport(aliases or [configured])
            return configured

        if is_local_emulator_udid(configured):
            console_port = _emulator_console_port(configured)
            if console_port is not None:
                transport = f"127.0.0.1:{console_port + 1}"
                if transport not in ready:
                    try:
                        self._run_global(["connect", transport])
                    except Exception:
                        pass
                    devices = self.list_devices()
                    ready = [item["serial"] for item in devices if item["state"] == "device"]
                matching = [serial for serial in ready if _same_emulator_transport(serial, console_port)]
                if matching:
                    return self._adopt_local_transport(matching)

        if configured and not is_local_emulator_udid(configured):
            raise RuntimeError(f"配置设备 {configured} 不可用；ADB 未发现该设备")

        if not configured and len(ready) == 1:
            self.config["udid"] = ready[0]
            return ready[0]
        if len(ready) == 1 and is_local_emulator_udid(configured):
            self.config["udid"] = ready[0]
            return ready[0]
        if not ready:
            target = configured or "（未指定）"
            raise RuntimeError(f"配置设备 {target} 不可用；ADB 未发现已连接且在线的 Android 设备")
        raise RuntimeError(
            f"配置设备 {configured or '（未指定）'} 不可用；ADB 发现多个在线设备，无法安全自动选择"
        )

    def _adopt_local_transport(self, aliases: list[str]) -> str:
        """Choose one transport and remove only aliases of the same AVD."""
        preferred = _prefer_local_transport(aliases)
        # AVDs may be registered simultaneously through IPv4 and IPv6
        # loopback. Appium sees those as two devices and can start competing
        # UiAutomator2 instrumentations. Keep one stable transport and
        # disconnect only aliases of this same console.
        for alias in aliases:
            if alias != preferred:
                try:
                    self._run_global(["disconnect", alias])
                except Exception:
                    pass
        self.config["udid"] = preferred
        return preferred

    def list_devices(self) -> list[dict[str, str]]:
        """Return ADB transports without applying the configured ``-s`` filter."""
        output = self._run_global(["devices", "-l"])
        devices: list[dict[str, str]] = []
        for line in str(output or "").splitlines():
            parts = line.strip().split()
            if len(parts) < 2 or parts[0].lower() == "list":
                continue
            state = parts[1].lower()
            if state not in {"device", "offline", "unauthorized", "unknown"}:
                continue
            devices.append({"serial": parts[0], "state": state, "details": " ".join(parts[2:])})
        return devices

    def prepare(self) -> None:
        """Restore ADB root only for an opted-in local root AVD.

        Appium starts instrumentation through the shared ADB daemon.  After an
        AVD reboot that daemon can silently fall back to shell mode; in this
        project that state caused UiAutomator2 to hang without a useful error.
        """
        if self.config.get("auto_recover", False) and self.is_local_emulator:
            if self.config.get("ensure_appium_helpers", False):
                self.wait_for_transport()
            self._runner(["root"])
            # Android can leave Appium Settings disabled after a failed
            # instrumentation run (``enabled=0``).  UiAutomator2 then reports
            # the misleading "Appium Settings app is not running" error even
            # though the package is installed.  Re-enable only Appium's own
            # helper packages on the opted-in local AVD; never touch a real
            # device or the audited application's package.
            if self.config.get("ensure_appium_helpers", False):
                for package in _APPIUM_HELPER_PACKAGES:
                    try:
                        self._runner(["shell", "pm", "enable", package])
                    except Exception:
                        continue
                # On Android 14/15, io.appium.settings is a location-typed
                # foreground service.  Missing runtime grants make it crash
                # immediately; Appium then times out with "Settings app is
                # not running after 30000ms".  pm grant is idempotent.
                for permission in _APPIUM_SETTINGS_RUNTIME_PERMISSIONS:
                    try:
                        self._runner(["shell", "pm", "grant", "io.appium.settings", permission])
                    except Exception:
                        continue
                self._start_appium_settings()
            if self.config.get("ensure_webview_provider", False):
                self._ensure_webview_provider()

    def _ensure_webview_provider(self) -> None:
        """Enable the installed system WebView before UiAutomator2 starts.

        Some emulator snapshots leave WebView installed but disabled. Apps that
        open an in-app policy then crash in ``WebViewFactory`` with a missing
        ``libmonochrome`` error, which looks like an Appium page-read failure.
        Only the system provider package is touched; the audited app is never
        modified.
        """
        for package in _WEBVIEW_PROVIDER_PACKAGES:
            try:
                installed = self._runner(["shell", "pm", "path", package])
            except Exception:
                continue
            if "package:" not in str(installed or ""):
                continue
            try:
                self._runner(["shell", "pm", "enable", package])
                self._runner(["shell", "settings", "put", "global", "webview_provider", package])
            except Exception:
                pass
            return

    def clear_app_data(self, package: str) -> bool:
        """Clear one audited package's data while keeping its APK installed.

        ``pm clear`` resets the app's files, databases, preferences and
        runtime permission state without uninstalling the package.  Keeping
        the package installed avoids needless APK churn and preserves the
        exact version selected for the audit.  The command is passed as an
        argument list, never interpolated into a shell command.
        """
        package_name = str(package or "").strip()
        if not package_name:
            return False
        output = self._runner(["shell", "pm", "clear", package_name])
        normalized = str(output or "").strip().lower()
        failure_markers = ("failed", "unknown package", "not found", "error:")
        if any(marker in normalized for marker in failure_markers):
            raise RuntimeError(f"pm clear failed for {package_name}: {str(output).strip()[:300]}")
        # AOSP returns ``Success``.  Some OEM/ADB wrappers return an empty
        # success response, so only explicit failure text is treated as an
        # error here.
        return True

    def wait_for_transport(self, timeout_seconds: int | None = None) -> bool:
        """Wait only when a local emulator ADB transport is explicitly offline."""
        if not self.is_local_emulator:
            return False
        try:
            state = self._runner(["get-state"]).strip().lower()
        except Exception:
            state = ""
        if state == "device":
            return True
        if state != "offline":
            return False
        timeout = max(5, int(timeout_seconds or 45))
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            try:
                if self._runner(["get-state"]).strip().lower() == "device":
                    return True
            except Exception:
                pass
            self._sleep(2)
        return False

    def _start_appium_settings(self) -> None:
        """Bring io.appium.settings to a running process before session create.

        Appium's own 30s wait only succeeds if the helper can stay alive.
        Starting it here after grants avoids the first-session race.
        """
        try:
            self._runner([
                "shell", "am", "start", "-n", "io.appium.settings/.Settings",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER",
            ])
        except Exception:
            return
        try:
            if self._runner(["shell", "pidof", "io.appium.settings"]).strip():
                return
        except Exception:
            return
        try:
            self._runner([
                "shell", "am", "start-foreground-service",
                "-n", "io.appium.settings/.ForegroundService",
            ])
        except Exception:
            return

    def wait_until_ready(
        self,
        timeout_seconds: int | None = None,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        """Wait for a local AVD that is already rebooting to finish booting.

        This never issues a reboot.  It is used after a live UiAutomator2
        session disappears, where forcing another reboot would turn one
        transient system restart into a longer outage.
        """
        if not self.is_local_emulator:
            return False
        timeout = max(15, int(timeout_seconds or self.config.get("uiautomator2_reboot_timeout_seconds", 120)))
        deadline = self._clock() + timeout
        stable_checks = max(1, int(self.config.get("android_service_ready_checks", 2)))
        stable_count = 0
        while self._clock() < deadline:
            if callable(should_stop) and should_stop():
                return False
            try:
                booted = self._runner(["shell", "getprop", "sys.boot_completed"]).strip() == "1"
            except Exception:
                booted = False
            if booted:
                # ``sys.boot_completed=1`` can remain true while system_server
                # is being restarted.  In that window Appium's hidden-api
                # cleanup reports ``Can't find service: settings`` and a fresh
                # UiAutomator2 session is guaranteed to fail.  Require the
                # service registry to answer for consecutive polls before
                # handing control back to Appium.  The flag is enabled by the
                # production config; unit-test devices can omit it.
                if self.config.get("wait_for_android_services", False):
                    if self._android_services_ready():
                        stable_count += 1
                    else:
                        stable_count = 0
                    if stable_count < stable_checks:
                        self._sleep(2)
                        continue
                self.prepare()
                return True
            stable_count = 0
            self._sleep(2)
        return False

    def _android_services_ready(self) -> bool:
        """Return false while Android's system service registry is missing."""
        try:
            settings = self._runner(["shell", "settings", "get", "global", "airplane_mode_on"])
            if "can't find service" in settings.lower() or "unknown service" in settings.lower():
                return False
            # A running system_server is a second cheap guard against a stale
            # settings shell response during an emulator restart.
            system_server = self._runner(["shell", "pidof", "system_server"])
            return bool(system_server.strip())
        except Exception:
            return False

    def recover_uiautomator2(self) -> None:
        """Clear Appium automation leftovers without churning helper APKs.

        Reinstalling the two UiAutomator2 packages on every retry creates new
        instrumentation records on some Android 15 AVDs.  Stopping and
        clearing them gives Appium a clean server state while keeping the
        verified helper APKs in place.
        """
        if not self.config.get("auto_recover", False):
            return
        if self.is_local_emulator:
            self.prepare()
        for package in _UIA_PACKAGES:
            self._runner(["shell", "am", "force-stop", package])
        self._runner(["shell", "pkill", "-f", "uiautomator"])
        self._runner(["forward", "--remove-all"])
        for package in _UIA_PACKAGES:
            self._runner(["shell", "pm", "clear", package])
        if self.config.get("ensure_appium_helpers", False):
            self._start_appium_settings()

    def reboot_after_uiautomator2_failure(self) -> bool:
        """Reboot a configured local AVD and wait until Android is usable.

        This is deliberately narrow: it is an opt-in last resort after a
        UiAutomator2 startup error and never targets a physical device or
        wipes its data.  ``False`` lets the caller preserve the original
        diagnostic if the AVD fails to boot in time.
        """
        enabled = bool(self.config.get("auto_reboot_on_uiautomator2_failure", False))
        if not (enabled and self.is_local_emulator):
            return False
        cooldown = max(0, int(self.config.get("uiautomator2_reboot_cooldown_seconds", 900)))
        now = self._wall_clock()
        if now < _UIA_REBOOT_COOLDOWNS.get(self.udid, 0):
            return False
        _UIA_REBOOT_COOLDOWNS[self.udid] = now + cooldown
        try:
            self._runner(["reboot"])
        except Exception:
            _UIA_REBOOT_COOLDOWNS.pop(self.udid, None)
            return False
        return self.wait_until_ready(self.config.get("uiautomator2_reboot_timeout_seconds", 120))

    def revoke_runtime_permissions(self, package: str, permissions: list[str] | None = None) -> list[str]:
        """Revoke previously granted dangerous permissions for a clean audit start.

        Never clears app data or touches packages other than the audited app.
        First-run permission dialogs (2.2 / 4.1 / 4.2) need phone and location
        denied; SDK observation grants those later in a second phase.
        Failures are ignored so a managed profile / OEM policy cannot abort
        the whole detection run.
        """
        package_name = str(package or "").strip()
        if not package_name:
            return []
        targets = [
            str(item) for item in (permissions or [])
            if str(item).startswith("android.permission.")
        ]
        if not targets and not permissions:
            from agent.detection_engines.static_analyzer import DANGEROUS_PERMISSIONS
            targets = sorted(DANGEROUS_PERMISSIONS)
        revoked: list[str] = []
        for permission in targets:
            try:
                self._runner(["shell", "pm", "revoke", package_name, permission])
                revoked.append(permission)
            except Exception:
                continue
        return revoked

    def grant_runtime_permissions(self, package: str, permissions: list[str] | None = None) -> list[str]:
        """Grant permissions needed to observe first-run SDK collection.

        Phase A revokes dangerous permissions so 2.2 / 4.1 / 4.2 dialogs can
        appear.  Phase B grants only the listed observability permissions;
        camera/mic stay denied for denial probes.  Failures are ignored.
        """
        package_name = str(package or "").strip()
        if not package_name:
            return []
        allowed = set(_KEEP_FOR_COLLECTION_OBSERVABILITY)
        targets = [
            str(item) for item in (permissions or list(allowed))
            if str(item) in allowed
        ]
        granted: list[str] = []
        for permission in targets:
            try:
                self._runner(["shell", "pm", "grant", package_name, permission])
                granted.append(permission)
            except Exception:
                continue
        return granted

    def grant_selected_runtime_permissions(self, package: str, permissions: list[str]) -> list[str]:
        """Grant only explicitly selected manifest permissions for allow replay."""
        package_name = str(package or "").strip()
        targets = [
            str(item) for item in (permissions or [])
            if str(item).startswith("android.permission.")
        ]
        if not package_name:
            return []
        granted: list[str] = []
        for permission in targets:
            try:
                self._runner(["shell", "pm", "grant", package_name, permission])
                if self.runtime_permission_states(package_name, [permission]).get(permission) is True:
                    granted.append(permission)
            except Exception:
                continue
        return granted

    def runtime_permission_states(self, package: str, permissions: list[str]) -> dict[str, bool | None]:
        """Read Android's effective grant state without opening Settings UI."""
        package_name = str(package or "").strip()
        result: dict[str, bool | None] = {}
        if not package_name:
            return result
        for permission in permissions or []:
            name = str(permission or "").strip()
            if not name.startswith("android.permission."):
                continue
            try:
                output = self._runner([
                    "shell", "cmd", "package", "check-permission", name, package_name, "0",
                ]).strip().lower()
            except Exception:
                result[name] = None
                continue
            if "granted" in output:
                result[name] = True
            elif "denied" in output:
                result[name] = False
            else:
                result[name] = None
        return result

    def ensure_frida_server(self, server_path: str, startup_timeout_seconds: int = 12) -> bool:
        """Ensure the configured Frida server is alive on a local root AVD.

        Frida can still discover an Android device through its helper package
        after an emulator reboot, even though the root server required for
        reliable ``spawn`` is gone.  Only a local ``emulator-*`` target is
        allowed to be repaired automatically; physical devices are never
        altered by the audit worker.
        """
        if not self.is_local_emulator or not server_path:
            return False
        self.prepare()
        try:
            if self._runner(["shell", "pidof", "frida-server"]).strip():
                return True
        except Exception:
            pass
        quoted_path = shlex.quote(server_path)
        try:
            self._runner(["shell", f"nohup {quoted_path} >/data/local/tmp/frida-server.log 2>&1 &"])
        except Exception:
            return False
        timeout = max(3, int(startup_timeout_seconds))
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            try:
                if self._runner(["shell", "pidof", "frida-server"]).strip():
                    return True
            except Exception:
                pass
            self._sleep(1)
        return False

    def recent_app_crash(self, package_name: str) -> str | None:
        """Return a concise recent app crash signature from local logcat.

        This is diagnostic-only: it reads the emulator log and never changes
        the target application.  It is used when Android has already returned
        to Launcher and its transient crash overlay is no longer in the page
        source.
        """
        if not package_name:
            return None
        try:
            output = self._runner(["logcat", "-d", "-t", "1000", "-v", "brief"])
        except Exception:
            return None
        lines = output.splitlines()
        package_positions = [
            index for index, line in enumerate(lines)
            if f"Process: {package_name}" in line or package_name in line and "FATAL EXCEPTION" in line
        ]
        if not package_positions:
            return None
        index = package_positions[-1]
        window = lines[max(0, index - 8): min(len(lines), index + 18)]
        fatal = next((line.strip() for line in window if "FATAL EXCEPTION" in line), "")
        exception = next((line.strip() for line in window if "Exception" in line or "Error" in line), "")
        library = next((line.strip() for line in window if "UnsatisfiedLinkError" in line or ".so" in line), "")
        parts = [part for part in (fatal, exception, library) if part]
        if not parts:
            return "检测到应用进程异常退出（logcat 未提供可归类异常）"
        return "应用崩溃日志：" + " | ".join(parts)[:700]

    def _adb(self) -> str:
        explicit = str(self.config.get("adb_path") or "").strip()
        candidates = [explicit] if explicit else []
        sdk_root = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        if sdk_root:
            candidates.append(str(Path(sdk_root) / "platform-tools" / "adb.exe"))
        local_sdk = os.environ.get("LOCALAPPDATA")
        if local_sdk:
            candidates.append(str(Path(local_sdk) / "Android" / "Sdk" / "platform-tools" / "adb.exe"))
        return next((path for path in candidates if path and Path(path).exists()), "adb")

    def _run(self, args: list[str]) -> str:
        command = [self._adb()]
        if self.udid:
            command.extend(["-s", self.udid])
        command.extend(args)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            check=False,
        )
        return (completed.stdout or "") + (completed.stderr or "")

    def _run_global(self, args: list[str]) -> str:
        """Run an ADB command that must not inherit ``-s <configured udid>``."""
        if self._custom_runner:
            return self._runner(args)
        command = [self._adb(), *args]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        return (completed.stdout or "") + (completed.stderr or "")


def _emulator_console_port(udid: str) -> int | None:
    value = str(udid or "").strip().lower()
    match = re.fullmatch(r"emulator-(\d+)", value)
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"(?:127\.0\.0\.1|localhost|\[::1\]):(\d+)", value)
    if match:
        return int(match.group(1)) - 1
    return None


def _same_emulator_transport(serial: str, console_port: int) -> bool:
    value = str(serial or "").strip().lower()
    if value == f"emulator-{console_port}":
        return True
    return value in {
        f"127.0.0.1:{console_port + 1}",
        f"localhost:{console_port + 1}",
        f"[::1]:{console_port + 1}",
    }


def _prefer_local_transport(serials: list[str]) -> str:
    order = {"127.0.0.1": 0, "localhost": 1, "[::1]": 2}
    return sorted(serials, key=lambda value: (
        0 if str(value).lower().startswith("emulator-") else 1,
        next((rank for host, rank in order.items() if str(value).lower().startswith(host + ":")), 9),
        str(value),
    ))[0]
