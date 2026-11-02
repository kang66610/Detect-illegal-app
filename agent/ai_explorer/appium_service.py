"""Local Appium health check and optional self-healing startup."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _find_appium_executable() -> str | None:
    """Resolve an already-installed Appium CLI without triggering an npx install.

    ``npx --no-install appium`` is sensitive to the npm cache used by the
    current process.  On Windows it is common for the CLI to be present in a
    previous npx cache while the active npm cache points at a different
    directory (or for the package version in ``package.json`` to be absent).
    Prefer a normal PATH installation, then the newest cached executable.
    """
    for name in ("appium.cmd", "appium"):
        candidate = shutil.which(name)
        if candidate and Path(candidate).name.lower() not in {"npx", "npx.cmd", "npx.ps1"}:
            return candidate

    cache_roots: list[Path] = []
    npm_cache = os.environ.get("npm_config_cache")
    if npm_cache:
        # npm_config_cache already names the cache directory itself.
        cache_roots.append(Path(npm_cache))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        cache_roots.append(Path(local_appdata) / "npm-cache")

    candidates: list[Path] = []
    for root in cache_roots:
        npx_root = root / "_npx"
        if not npx_root.is_dir():
            continue
        # Keep the search scoped to npm's npx cache; do not recurse through
        # the whole user profile or accidentally select an unrelated binary.
        candidates.extend(npx_root.glob("*/node_modules/.bin/appium.cmd"))
        candidates.extend(npx_root.glob("*/node_modules/.bin/appium"))
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        return None
    return str(max(candidates, key=lambda path: path.stat().st_mtime))


class AppiumService:
    """Keep the local Appium prerequisite explicit and observable.

    The audit worker can only start a loopback Appium server. Remote endpoints
    are deliberately never launched by the worker, and are left to the remote
    device-farm operator.
    """

    def __init__(
        self,
        appium_config: dict,
        *,
        probe: Callable[[], bool] | None = None,
        starter: Callable[[], None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = appium_config
        self._probe = probe or self.is_ready
        self._starter = starter or self.start
        self._sleep = sleeper

    @property
    def server_url(self) -> str:
        return str(self.config.get("server_url", "")).rstrip("/")

    @property
    def status_url(self) -> str:
        parsed = urlparse(self.server_url)
        return urlunparse((parsed.scheme, parsed.netloc, "/status", "", "", ""))

    def is_local(self) -> bool:
        parsed = urlparse(self.server_url)
        return parsed.hostname in {"127.0.0.1", "localhost", "::1"} and bool(parsed.port)

    def is_ready(self) -> bool:
        if not self.status_url.startswith(("http://", "https://")):
            return False
        try:
            request = Request(self.status_url, method="GET")
            with urlopen(request, timeout=2) as response:  # noqa: S310 - URL comes from local audit configuration.
                if response.status != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
                value = payload.get("value", payload)
                return bool(value.get("ready", True))
        except Exception:
            return False

    def ensure_ready(self) -> bool:
        """Return whether Appium is ready, starting only an opted-in local server."""
        if self._probe():
            return True
        if not self.config.get("auto_start", False) or not self.is_local():
            return False

        self._starter()
        timeout = max(1.0, float(self.config.get("startup_timeout_seconds", 20)))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._probe():
                return True
            self._sleep(0.5)
        return self._probe()

    @property
    def sessions_url(self) -> str:
        """Appium's session-discovery endpoint (Appium 2/3)."""
        parsed = urlparse(self.server_url)
        return urlunparse((parsed.scheme, parsed.netloc, "/appium/sessions", "", "", ""))

    @property
    def legacy_sessions_url(self) -> str:
        """Legacy endpoint used by older Appium servers."""
        parsed = urlparse(self.server_url)
        return urlunparse((parsed.scheme, parsed.netloc, "/sessions", "", "", ""))

    def cleanup_sessions(self) -> int:
        """Delete stale loopback Appium master sessions before a new run.

        ``webdriver.Remote`` can raise after Appium has registered a master
        session (for example when UiAutomator2 hidden-api setup fails).  That
        orphan is still subject to ``newCommandTimeout`` and may later stop
        the UiAutomator2 instrumentation used by a newer session.  Real-device
        audits run serially, and this method is restricted to loopback
        endpoints, so removing all existing sessions is the least surprising
        recovery policy.  Any health/cleanup error is deliberately ignored;
        session creation remains the authoritative operation.
        """
        if not self.is_local() or not self.sessions_url.startswith(("http://", "https://")):
            return 0
        sessions = None
        # Appium 2/3 protects session discovery behind the explicit
        # ``session_discovery`` insecure feature and moved it to
        # ``/appium/sessions``.  Keep a fallback for Appium 1/legacy servers,
        # but never treat a discovery failure as an instruction to delete an
        # arbitrary session id.
        for endpoint in (self.sessions_url, self.legacy_sessions_url):
            try:
                request = Request(endpoint, method="GET")
                with urlopen(request, timeout=2) as response:  # noqa: S310 - validated loopback URL.
                    payload = json.loads(response.read().decode("utf-8"))
                value = payload.get("value", payload)
                if isinstance(value, list):
                    sessions = value
                    break
            except Exception:
                continue
        if sessions is None:
            return 0
        removed = 0
        parsed = urlparse(self.server_url)
        for session in sessions:
            if not isinstance(session, dict):
                continue
            session_id = session.get("id") or session.get("sessionId")
            if not session_id:
                continue
            url = urlunparse((parsed.scheme, parsed.netloc, f"/session/{session_id}", "", "", ""))
            try:
                with urlopen(Request(url, method="DELETE"), timeout=5):  # noqa: S310 - validated loopback URL.
                    removed += 1
            except Exception:
                # A session can disappear between GET and DELETE; it is
                # already clean for the next connection attempt.
                continue
        return removed

    def start(self) -> None:
        """Start a local Appium CLI without downloading packages."""
        if not self.is_local():
            raise RuntimeError("only a loopback Appium endpoint can be started automatically")
        parsed = urlparse(self.server_url)
        appium = _find_appium_executable()
        npx = None if appium else (shutil.which("npx.cmd") or shutil.which("npx"))
        if not appium and not npx:
            raise RuntimeError("cannot find Appium or npx; install Node.js and Appium first")

        log_path = PROJECT_ROOT / str(self.config.get("server_log_path", "data/logs/appium-4725.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        sdk_root = environment.get("ANDROID_SDK_ROOT") or environment.get("ANDROID_HOME")
        if sdk_root:
            platform_tools = Path(sdk_root) / "platform-tools"
            if platform_tools.is_dir():
                environment["PATH"] = f"{platform_tools}{os.pathsep}{environment.get('PATH', '')}"

        command = [
            appium or npx,
            *( ["server"] if appium else ["--no-install", "appium", "server"] ),
            "--address", parsed.hostname or "127.0.0.1",
            "--port", str(parsed.port),
            # A failed /session POST can leave an internal master session
            # while its UiAutomator2 instrumentation is already dead.  The
            # next local run must replace that orphan instead of contending
            # with it on the same emulator.
            "--session-override",
            "--log", str(log_path), "--log-level", "info",
        ]
        # The worker's endpoint is loopback-only. Enabling only Appium's
        # read/delete session-discovery feature lets us remove orphan master
        # sessions after a failed POST /session without exposing the server
        # to a remote device farm or enabling shell/file-system features.
        insecure = self.config.get("allow_insecure_features", ("*:session_discovery",))
        if isinstance(insecure, str):
            insecure = [item.strip() for item in insecure.split(",") if item.strip()]
        if insecure:
            command.extend(["--allow-insecure", ",".join(str(item) for item in insecure)])
        kwargs: dict = {
            "cwd": str(PROJECT_ROOT),
            "env": environment,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(command, **kwargs)  # noqa: S603 - fixed command plus validated local URL.
