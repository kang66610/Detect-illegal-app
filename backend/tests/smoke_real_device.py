"""真机/模拟器冒烟：创建会话 → 启动已安装测试 App → 读取页面 → 一次可逆动作 → 关闭会话。

用法：.venv/Scripts/python backend/tests/smoke_real_device.py
前置：模拟器已启动且出现在 adb devices；Appium 由 PRIVACY_APPIUM_AUTO_START 自动拉起。
目标选用系统设置 App：不产生网络流量与个人数据流，动作全部可逆。
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("PRIVACY_APPIUM_AUTO_START", "true")

from agent.ai_explorer.appium_client import AppiumClient
from agent.ai_explorer.page_state import parse_page
from backend.app.config import load_config

SMOKE_PACKAGE = "com.android.settings"


def smoke() -> dict:
    cfg = load_config()
    client = AppiumClient(cfg)
    steps: list[tuple[str, str]] = []
    result: dict = {"steps": steps}
    try:
        client.connect()
        steps.append(("创建 UiAutomator2 会话", str(client.driver.session_id)))

        client.activate(SMOKE_PACKAGE)
        steps.append((f"启动已安装测试 App {SMOKE_PACKAGE}", "activated"))

        time.sleep(2)
        activity, xml = client.page()
        page = parse_page(activity, xml)
        steps.append((
            "读取页面",
            f"activity={activity} elements={len(page.elements)} "
            f"surface={page.surface_fingerprint[:12]}",
        ))

        client.perform({"action": "back", "target": "", "reason": "真机冒烟：一次可逆动作"})
        steps.append(("执行一次可逆 back 动作", "ok"))

        activity_after, xml_after = client.page()
        page_after = parse_page(activity_after, xml_after)
        steps.append((
            "动作后再次读取页面",
            f"activity={activity_after} elements={len(page_after.elements)} "
            f"surface={page_after.surface_fingerprint[:12]}",
        ))

        result["success"] = True
    except Exception as exc:  # noqa: BLE001 - 冒烟需要完整归因任何失败
        result["success"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            client.close()
            result["session_closed"] = True
        except Exception as exc:  # noqa: BLE001
            result["session_closed"] = f"关闭失败: {exc}"
    return result


if __name__ == "__main__":
    outcome = smoke()
    print("=" * 56)
    print("真机冒烟测试结果（Task 8 Step 5）")
    print("=" * 56)
    for name, detail in outcome["steps"]:
        print(f"  [步骤] {name}: {detail}")
    print(f"  成功: {outcome.get('success')}")
    if "error" in outcome:
        print(f"  错误: {outcome['error']}")
    print(f"  会话已关闭: {outcome.get('session_closed')}")
    sys.exit(0 if outcome.get("success") else 1)
