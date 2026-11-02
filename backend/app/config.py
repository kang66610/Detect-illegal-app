import os
from collections.abc import Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 默认配置（与 .env.example 保持一致；.env 中的同名项会覆盖这里，缺 .env 时按此运行）
_DEFAULTS: dict = {
    "storage": {
        "db_path": "data/app.db",
        "apk_dir": "data/apks",
        "evidence_dir": "data/evidence",
        # Reconcile task evidence directories against the DB on Worker start.
        # Orphans are quarantined first and only purged after retention.
        "evidence_gc_enabled": True,
        "evidence_gc_grace_hours": 72,
        "evidence_gc_trash_retention_days": 7,
        "evidence_gc_max_dirs_per_run": 500,
        "evidence_gc_interval_hours": 6,
        "export_dir": "data/exports",
        "log_dir": "data/logs",
        "retention_days": 90,
    },
    "worker": {"max_concurrent": 3, "poll_interval_seconds": 2},
    "detection": {
        "engines": {"explorer": "real", "monitor": "real"},
        "permission_probe_action": "deny",
        "permission_probe_post_steps": 6,
        # Logout rows are observation-only by default because some Apps log out
        # immediately instead of showing a reversible confirmation dialog.
        "explore_logout_confirmation": False,
        # A deep run may compare several safe, visible sensitive features
        # (voice/upload/camera/scan). The bound prevents looped probing while
        # avoiding a single-app hard-coded path.
        # Legacy minimum; exploration now applies the budget per observed
        # redress/business context so two feedback pages may reuse the same IDs.
        "max_sensitive_permission_probes": 6,
        "max_sensitive_permission_probes_per_context": 6,
        "max_generic_page_scrolls": 2,
        "document_blank_retries": 3,
        "document_blank_wait_seconds": 2,
        # A single unchanged WebView can be a transient render/input stall.
        # Confirm a driver-reported bottom twice; otherwise retry and retain an
        # incomplete marker rather than falsely claiming full-document coverage.
        "document_bottom_confirmations": 2,
        "document_stuck_retries": 3,
        "document_stuck_wait_seconds": 2,
        "document_stuck_seconds": 12,
        "no_effect_attempts": 2,
        "page_settle_retries": 4,
        "page_settle_wait_seconds": 3.0,
        # One cold restart is allowed after every stable reread still shows a
        # generic loading shell. App data is preserved and DFS route replayed.
        "loading_shell_cold_restart_limit": 1,
        # Privacy/terms links may leave the App through Chrome Custom Tabs.
        # Give a real external page a bounded chance to render, then record a
        # coverage gap instead of mistaking a blank browser for a document.
        "external_document_wait_retries": 2,
        "external_document_wait_seconds": 1.5,
        "external_document_identity_wait_retries": 2,
        "external_document_identity_wait_seconds": 1.0,
        "permission_after_consent_window_seconds": 30,
        # The Android permission controller can dismiss before `pm` reports
        # the effective grant. Poll the actual condition instead of declaring
        # allow-phase evidence unverified from one stale read.
        "permission_grant_verify_attempts": 4,
        "permission_grant_verify_interval_seconds": 1.0,
        "manual_login_wait_seconds": 120,
        # Optional dedicated audit account. Values are read on demand from the
        # named environment variables and are never copied into config/logs.
        "test_account_enabled": False,
        "test_account_username_env": "PRIVACY_TEST_ACCOUNT_USERNAME",
        "test_account_password_env": "PRIVACY_TEST_ACCOUNT_PASSWORD",
        # If phase one already exhausted the human-login checkpoint, phase two
        # performs only a short state verification instead of waiting again.
        "subsequent_phase_login_wait_seconds": 5,
        # After first entering the app (or after login), stay on the main
        # content tab so SDK collection can run before the explorer dives into
        # 设置/隐私政策.  Absence of this dwell is not treated as compliance.
        "sdk_observation_dwell_seconds": 8,
        # End-of-run home-screen dwell for background collection signals.
        "background_probe_seconds": 8,
        # Max delta when correlating Frida events to Appium page/action anchors.
        "behavior_correlation_max_delta_seconds": 15,
        # Clicking a span or an in-app exit dialog can send the process to
        # the system launcher. Relaunch and continue; do not fail the task.
        "launcher_relaunch_limit": 12,
        # Screenshot OCR restores labels when accessibility trees are empty or
        # unlabeled; missing OCR never invents violations.
        "screen_ocr_enabled": True,
        # Revoke previously granted dangerous permissions on the audited app
        # before exploration so a prior manual install cannot contaminate consent timing.
        "reset_runtime_permissions": True,
        # A dual run installs cleanly only for phase one. Phase two creates a
        # fresh Appium session and resets runtime permissions, but preserves app
        # data/login so the authenticated DFS route is not destroyed.
        "reuse_app_install_between_probe_phases": True,
        # Chrome/Custom Tab can keep reporting new viewports forever; cap scrolls
        # so one long external clause cannot consume the whole deep budget.
        "mode_limits": {
            "fast": {"max_duration_minutes": 30, "max_pages": 60},
            "deep": {"max_duration_minutes": 120, "max_pages": 300},
        }
    },
    "llm": {
        "provider": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "LLM_API_KEY",
        "model": "qwen3.6-plus",
        "timeout_seconds": 30,
    },
    "appium": {
        "server_url": "http://127.0.0.1:4723",
        "device_name": "Android",
        "platform_version": "",
        "udid": "",
        "no_reset": False,
        # A manual-login window can be 180s. Keep Appium's idle-session
        # watchdog above that window so a stale failed session cannot tear
        # down the active UiAutomator2 session while the tester is working.
        "new_command_timeout_seconds": 600,
        "page_wait_seconds": 1.0,
        # Some Android 15 emulator images keep Appium Settings' recorder
        # service unavailable.  The explorer does not use that service, so it
        # can be bypassed explicitly for a known device.
        "skip_device_initialization": False,
        # Android 15/root AVD images may not expose the ``settings`` service
        # while booting. This policy is optional for our accessibility-only
        # workflow; failing the entire session here leaves orphan sessions.
        "ignore_hidden_api_policy_error": True,
        "uiautomator2_server_launch_timeout_seconds": 90,
        "session_retries": 2,
        "auto_recover": True,
        # Re-enable Appium's helper packages before session creation. Android
        # can disable io.appium.settings after a failed instrumentation run.
        "ensure_appium_helpers": True,
        # Android emulator snapshots may leave the installed WebView disabled;
        # enable the provider before policy pages are opened.
        "ensure_webview_provider": True,
        # A stuck emulator instrumentation service cannot be repaired by
        # reinstalling Appium's APKs alone. This is opt-in and is limited to
        # local AVDs; physical devices are never rebooted by the worker.
        "auto_reboot_on_uiautomator2_failure": False,
        "uiautomator2_reboot_timeout_seconds": 120,
        # A recovery reboot is a last resort, and at most once per local AVD
        # in this interval.  It never wipes data or targets physical devices.
        "uiautomator2_reboot_cooldown_seconds": 900,
        # sys.boot_completed may stay at 1 while system_server is restarting.
        # Wait for the settings service and system_server to be stable before
        # recreating a UiAutomator2 session.
        "wait_for_android_services": True,
        "android_service_ready_checks": 2,
        "adb_path": "",
        # The worker may only launch a loopback Appium server, never a remote
        # device farm. It is opt-in to preserve non-Android installations.
        "auto_start": False,
        "startup_timeout_seconds": 20,
        # Appium 2/3 protects /appium/sessions. This is the only insecure
        # feature needed by the loopback worker to delete orphan sessions.
        "allow_insecure_features": ["*:session_discovery"],
        "server_log_path": "data/logs/appium-4725.log",
    },
    "frida": {
        "device_id": "",
        "spawn_target": True,
        # On a root AVD, keep the real frida-server alive across emulator
        # reboots.  Device discovery alone is not enough: an Android helper
        # may still make Frida list processes while spawn/attach cannot work.
        "auto_start": True,
        "server_path": "/data/local/tmp/frida-server",
        "startup_timeout_seconds": 12,
        "operation_timeout_seconds": 20,
        "monitor_seconds": 0,
        "overseas_domains": [],
    },
    "flowdroid": {
        "enabled": False, "java_path": "java", "jar_path": "",
        "android_platforms": "", "sources_sinks": str(PROJECT_ROOT / "agent" / "config" / "flowdroid" / "SourcesAndSinks.txt"), "timeout_seconds": 900,
        "cache_enabled": True, "cache_dir": str(PROJECT_ROOT / "data" / "static-cache" / "flowdroid"),
    },
    "network": {"third_party_domains": [], "overseas_domains": []},
    "rule_engine": {
        # lenient：证据链准入放宽。attempted 场景默认仍是 not_covered。
        "evidence_chain_mode": "strict",
        "attempted_scenario_as_covered": False,
    },
    "report": {
        "pdf_channel": "msedge",
        "header": {"test_org": "", "subject_org": "", "entrust_org": ""},
    },
    "encryption": {"key_file": "data/fernet.key"},
}

# 环境变量 → 配置路径 与 类型转换（全部可在 .env 中修改）
_ENV_MAP: list[tuple[str, tuple[str, ...], type]] = [
    ("PRIVACY_DB_PATH", ("storage", "db_path"), str),
    ("PRIVACY_APK_DIR", ("storage", "apk_dir"), str),
    ("PRIVACY_EVIDENCE_DIR", ("storage", "evidence_dir"), str),
    ("PRIVACY_EVIDENCE_GC_ENABLED", ("storage", "evidence_gc_enabled"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_EVIDENCE_GC_GRACE_HOURS", ("storage", "evidence_gc_grace_hours"), float),
    ("PRIVACY_EVIDENCE_GC_TRASH_RETENTION_DAYS", ("storage", "evidence_gc_trash_retention_days"), float),
    ("PRIVACY_EVIDENCE_GC_MAX_DIRS_PER_RUN", ("storage", "evidence_gc_max_dirs_per_run"), int),
    ("PRIVACY_EVIDENCE_GC_INTERVAL_HOURS", ("storage", "evidence_gc_interval_hours"), float),
    ("PRIVACY_EXPORT_DIR", ("storage", "export_dir"), str),
    ("PRIVACY_LOG_DIR", ("storage", "log_dir"), str),
    ("PRIVACY_RETENTION_DAYS", ("storage", "retention_days"), int),
    ("PRIVACY_WORKER_MAX_CONCURRENT", ("worker", "max_concurrent"), int),
    ("PRIVACY_WORKER_POLL_INTERVAL", ("worker", "poll_interval_seconds"), float),
    ("PRIVACY_FAST_MAX_MINUTES", ("detection", "mode_limits", "fast", "max_duration_minutes"), int),
    ("PRIVACY_FAST_MAX_PAGES", ("detection", "mode_limits", "fast", "max_pages"), int),
    ("PRIVACY_DEEP_MAX_MINUTES", ("detection", "mode_limits", "deep", "max_duration_minutes"), int),
    ("PRIVACY_DEEP_MAX_PAGES", ("detection", "mode_limits", "deep", "max_pages"), int),
    ("PRIVACY_PERMISSION_PROBE_ACTION", ("detection", "permission_probe_action"), str),
    ("PRIVACY_PERMISSION_PROBE_POST_STEPS", ("detection", "permission_probe_post_steps"), int),
    ("PRIVACY_MAX_SENSITIVE_PERMISSION_PROBES", ("detection", "max_sensitive_permission_probes"), int),
    ("PRIVACY_MAX_SENSITIVE_PERMISSION_PROBES_PER_CONTEXT", ("detection", "max_sensitive_permission_probes_per_context"), int),
    ("PRIVACY_MAX_GENERIC_PAGE_SCROLLS", ("detection", "max_generic_page_scrolls"), int),
    ("PRIVACY_DOCUMENT_BLANK_RETRIES", ("detection", "document_blank_retries"), int),
    ("PRIVACY_DOCUMENT_BLANK_WAIT_SECONDS", ("detection", "document_blank_wait_seconds"), float),
    ("PRIVACY_DOCUMENT_BOTTOM_CONFIRMATIONS", ("detection", "document_bottom_confirmations"), int),
    ("PRIVACY_DOCUMENT_STUCK_RETRIES", ("detection", "document_stuck_retries"), int),
    ("PRIVACY_DOCUMENT_STUCK_WAIT_SECONDS", ("detection", "document_stuck_wait_seconds"), float),
    ("PRIVACY_PAGE_SETTLE_RETRIES", ("detection", "page_settle_retries"), int),
    ("PRIVACY_PAGE_SETTLE_WAIT_SECONDS", ("detection", "page_settle_wait_seconds"), float),
    ("PRIVACY_LOADING_SHELL_COLD_RESTART_LIMIT", ("detection", "loading_shell_cold_restart_limit"), int),
    ("PRIVACY_EXTERNAL_DOCUMENT_WAIT_RETRIES", ("detection", "external_document_wait_retries"), int),
    ("PRIVACY_EXTERNAL_DOCUMENT_WAIT_SECONDS", ("detection", "external_document_wait_seconds"), float),
    ("PRIVACY_EXTERNAL_DOCUMENT_IDENTITY_WAIT_RETRIES", ("detection", "external_document_identity_wait_retries"), int),
    ("PRIVACY_EXTERNAL_DOCUMENT_IDENTITY_WAIT_SECONDS", ("detection", "external_document_identity_wait_seconds"), float),
    ("PRIVACY_PERMISSION_AFTER_CONSENT_WINDOW_SECONDS", ("detection", "permission_after_consent_window_seconds"), int),
    ("PRIVACY_PERMISSION_GRANT_VERIFY_ATTEMPTS", ("detection", "permission_grant_verify_attempts"), int),
    ("PRIVACY_PERMISSION_GRANT_VERIFY_INTERVAL_SECONDS", ("detection", "permission_grant_verify_interval_seconds"), float),
    ("PRIVACY_MANUAL_LOGIN_WAIT_SECONDS", ("detection", "manual_login_wait_seconds"), int),
    ("PRIVACY_TEST_ACCOUNT_ENABLED", ("detection", "test_account_enabled"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_TEST_ACCOUNT_USERNAME_ENV", ("detection", "test_account_username_env"), str),
    ("PRIVACY_TEST_ACCOUNT_PASSWORD_ENV", ("detection", "test_account_password_env"), str),
    ("PRIVACY_SUBSEQUENT_PHASE_LOGIN_WAIT_SECONDS", ("detection", "subsequent_phase_login_wait_seconds"), int),
    ("PRIVACY_SDK_OBSERVATION_DWELL_SECONDS", ("detection", "sdk_observation_dwell_seconds"), float),
    ("PRIVACY_BACKGROUND_PROBE_SECONDS", ("detection", "background_probe_seconds"), float),
    ("PRIVACY_BEHAVIOR_CORRELATION_MAX_DELTA_SECONDS", ("detection", "behavior_correlation_max_delta_seconds"), float),
    ("PRIVACY_LAUNCHER_RELAUNCH_LIMIT", ("detection", "launcher_relaunch_limit"), int),
    ("PRIVACY_SCREEN_OCR_ENABLED", ("detection", "screen_ocr_enabled"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_RESET_RUNTIME_PERMISSIONS", ("detection", "reset_runtime_permissions"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_LLM_PROVIDER", ("llm", "provider"), str),
    ("PRIVACY_LLM_BASE_URL", ("llm", "base_url"), str),
    ("PRIVACY_LLM_MODEL", ("llm", "model"), str),
    ("PRIVACY_LLM_TIMEOUT_SECONDS", ("llm", "timeout_seconds"), float),
    ("PRIVACY_APPIUM_SERVER_URL", ("appium", "server_url"), str),
    ("PRIVACY_APPIUM_DEVICE_NAME", ("appium", "device_name"), str),
    ("PRIVACY_APPIUM_PLATFORM_VERSION", ("appium", "platform_version"), str),
    ("PRIVACY_APPIUM_UDID", ("appium", "udid"), str),
    ("PRIVACY_APPIUM_NO_RESET", ("appium", "no_reset"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_APPIUM_COMMAND_TIMEOUT", ("appium", "new_command_timeout_seconds"), int),
    ("PRIVACY_APPIUM_PAGE_WAIT_SECONDS", ("appium", "page_wait_seconds"), float),
    ("PRIVACY_APPIUM_SKIP_DEVICE_INITIALIZATION", ("appium", "skip_device_initialization"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_APPIUM_IGNORE_HIDDEN_API_POLICY_ERROR", ("appium", "ignore_hidden_api_policy_error"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_APPIUM_UIAUTOMATOR2_LAUNCH_TIMEOUT_SECONDS", ("appium", "uiautomator2_server_launch_timeout_seconds"), int),
    ("PRIVACY_APPIUM_SESSION_RETRIES", ("appium", "session_retries"), int),
    ("PRIVACY_APPIUM_AUTO_RECOVER", ("appium", "auto_recover"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_APPIUM_ENSURE_WEBVIEW_PROVIDER", ("appium", "ensure_webview_provider"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_APPIUM_AUTO_REBOOT_ON_UIAUTOMATOR2_FAILURE", ("appium", "auto_reboot_on_uiautomator2_failure"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_APPIUM_UIAUTOMATOR2_REBOOT_TIMEOUT_SECONDS", ("appium", "uiautomator2_reboot_timeout_seconds"), int),
    ("PRIVACY_APPIUM_UIAUTOMATOR2_REBOOT_COOLDOWN_SECONDS", ("appium", "uiautomator2_reboot_cooldown_seconds"), int),
    ("PRIVACY_APPIUM_WAIT_FOR_ANDROID_SERVICES", ("appium", "wait_for_android_services"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_APPIUM_ANDROID_SERVICE_READY_CHECKS", ("appium", "android_service_ready_checks"), int),
    ("PRIVACY_APPIUM_ADB_PATH", ("appium", "adb_path"), str),
    ("PRIVACY_APPIUM_AUTO_START", ("appium", "auto_start"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_APPIUM_STARTUP_TIMEOUT_SECONDS", ("appium", "startup_timeout_seconds"), float),
    ("PRIVACY_FRIDA_DEVICE_ID", ("frida", "device_id"), str),
    ("PRIVACY_FRIDA_SPAWN_TARGET", ("frida", "spawn_target"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_FRIDA_AUTO_START", ("frida", "auto_start"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_FRIDA_SERVER_PATH", ("frida", "server_path"), str),
    ("PRIVACY_FRIDA_STARTUP_TIMEOUT_SECONDS", ("frida", "startup_timeout_seconds"), int),
    ("PRIVACY_FRIDA_OPERATION_TIMEOUT_SECONDS", ("frida", "operation_timeout_seconds"), int),
    ("PRIVACY_FRIDA_MONITOR_SECONDS", ("frida", "monitor_seconds"), float),
    ("PRIVACY_FRIDA_OVERSEAS_DOMAINS", ("frida", "overseas_domains"), lambda v: [x.strip() for x in v.split(",") if x.strip()]),
    ("PRIVACY_FLOWDROID_ENABLED", ("flowdroid", "enabled"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_FLOWDROID_JAVA_PATH", ("flowdroid", "java_path"), str),
    ("PRIVACY_FLOWDROID_JAR_PATH", ("flowdroid", "jar_path"), str),
    ("PRIVACY_FLOWDROID_ANDROID_PLATFORMS", ("flowdroid", "android_platforms"), str),
    ("PRIVACY_FLOWDROID_SOURCES_SINKS", ("flowdroid", "sources_sinks"), str),
    ("PRIVACY_FLOWDROID_TIMEOUT_SECONDS", ("flowdroid", "timeout_seconds"), int),
    ("PRIVACY_FLOWDROID_CACHE_ENABLED", ("flowdroid", "cache_enabled"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_FLOWDROID_CACHE_DIR", ("flowdroid", "cache_dir"), str),
    ("PRIVACY_NETWORK_THIRD_PARTY_DOMAINS", ("network", "third_party_domains"), lambda v: [x.strip() for x in v.split(",") if x.strip()]),
    ("PRIVACY_NETWORK_OVERSEAS_DOMAINS", ("network", "overseas_domains"), lambda v: [x.strip() for x in v.split(",") if x.strip()]),
    ("PRIVACY_EVIDENCE_CHAIN_MODE", ("rule_engine", "evidence_chain_mode"), str),
    ("PRIVACY_ATTEMPTED_SCENARIO_AS_COVERED", ("rule_engine", "attempted_scenario_as_covered"), lambda v: v.lower() in ("1", "true", "yes")),
    ("PRIVACY_PDF_CHANNEL", ("report", "pdf_channel"), str),
    ("PRIVACY_REPORT_TEST_ORG", ("report", "header", "test_org"), str),
    ("PRIVACY_REPORT_SUBJECT_ORG", ("report", "header", "subject_org"), str),
    ("PRIVACY_REPORT_ENTRUST_ORG", ("report", "header", "entrust_org"), str),
    ("PRIVACY_FERNET_KEY_FILE", ("encryption", "key_file"), str),
]


def _load_dotenv(path: Path | None = None) -> None:
    """极简 .env 加载：KEY=VALUE 每行一条，# 开头为注释；已存在的环境变量不覆盖。"""
    env_path = path or (PROJECT_ROOT / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _apply_env(data: dict, env: Mapping[str, str]) -> dict:
    for env_key, path, cast in _ENV_MAP:
        raw = env.get(env_key)
        if raw is None or raw == "":
            continue
        try:
            value = cast(raw)
        except (ValueError, TypeError):
            continue  # 非法值保持默认
        node = data
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
    return data


def load_config(env: Mapping[str, str] | None = None) -> dict:
    """配置 = 代码默认值 + 环境变量覆盖（.env 已在导入时注入 os.environ）。"""
    import copy

    data = copy.deepcopy(_DEFAULTS)
    return _apply_env(data, env if env is not None else os.environ)


_load_dotenv()
config = load_config()
