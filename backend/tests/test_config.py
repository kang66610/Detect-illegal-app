from backend.app.config import load_config


def test_load_config_returns_expected_defaults():
    cfg = load_config(env={})
    assert cfg["worker"]["max_concurrent"] == 3
    assert cfg["storage"]["db_path"] == "data/app.db"
    assert cfg["llm"]["provider"] == "openai_compatible"
    assert cfg["llm"]["model"] == "qwen3.6-plus"
    assert "dashscope" in cfg["llm"]["base_url"]
    assert cfg["report"]["pdf_channel"] == "msedge"
    assert cfg["rule_engine"]["attempted_scenario_as_covered"] is False
    assert cfg["detection"]["page_settle_retries"] == 4
    assert cfg["detection"]["page_settle_wait_seconds"] == 3.0


def test_env_overrides_apply_with_type_coercion():
    cfg = load_config(env={
        "PRIVACY_WORKER_MAX_CONCURRENT": "7",
        "PRIVACY_RETENTION_DAYS": "30",
        "PRIVACY_APPIUM_SKIP_DEVICE_INITIALIZATION": "true",
        "PRIVACY_APPIUM_UIAUTOMATOR2_LAUNCH_TIMEOUT_SECONDS": "90",
        "PRIVACY_APPIUM_AUTO_REBOOT_ON_UIAUTOMATOR2_FAILURE": "true",
        "PRIVACY_APPIUM_UIAUTOMATOR2_REBOOT_TIMEOUT_SECONDS": "75",
        "PRIVACY_FRIDA_AUTO_START": "true",
        "PRIVACY_FRIDA_SERVER_PATH": "/data/local/tmp/custom-frida-server",
        "PRIVACY_FRIDA_STARTUP_TIMEOUT_SECONDS": "15",
        "PRIVACY_FRIDA_OPERATION_TIMEOUT_SECONDS": "25",
        "PRIVACY_PAGE_SETTLE_RETRIES": "6",
        "PRIVACY_PAGE_SETTLE_WAIT_SECONDS": "1.5",
        "PRIVACY_REPORT_TEST_ORG": "示例检测机构",
    })
    assert cfg["worker"]["max_concurrent"] == 7
    assert cfg["storage"]["retention_days"] == 30
    assert cfg["appium"]["skip_device_initialization"] is True
    assert cfg["appium"]["uiautomator2_server_launch_timeout_seconds"] == 90
    assert cfg["appium"]["auto_reboot_on_uiautomator2_failure"] is True
    assert cfg["appium"]["uiautomator2_reboot_timeout_seconds"] == 75
    assert cfg["frida"]["auto_start"] is True
    assert cfg["frida"]["server_path"] == "/data/local/tmp/custom-frida-server"
    assert cfg["frida"]["startup_timeout_seconds"] == 15
    assert cfg["frida"]["operation_timeout_seconds"] == 25
    assert cfg["detection"]["page_settle_retries"] == 6
    assert cfg["detection"]["page_settle_wait_seconds"] == 1.5
    assert cfg["report"]["header"]["test_org"] == "示例检测机构"


def test_invalid_env_values_keep_defaults():
    cfg = load_config(env={"PRIVACY_WORKER_MAX_CONCURRENT": "abc"})
    assert cfg["worker"]["max_concurrent"] == 3
