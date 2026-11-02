"""一键启动 API 服务：.venv/Scripts/python scripts/run_api.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根，保证 backend 可导入

import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=False)
