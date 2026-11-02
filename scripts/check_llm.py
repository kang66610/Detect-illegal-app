"""千问（OpenAI 兼容）连通性检查：.venv/Scripts/python scripts/check_llm.py"""
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 控制台中文不乱码

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import config  # noqa: E402


def main() -> int:
    cfg = config["llm"]
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        print("未找到 API key：请在项目根目录 .env 中配置 LLM_API_KEY")
        return 1
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=cfg["base_url"])
    try:
        resp = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "user", "content": "请只回复两个字：正常"}],
            max_tokens=16,
        )
        print("连接成功")
        print("  模型：", resp.model)
        print("  回复：", resp.choices[0].message.content)
        return 0
    except Exception as e:
        print("连接失败：", type(e).__name__, str(e)[:300])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
