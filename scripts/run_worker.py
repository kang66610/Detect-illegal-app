"""一键启动检测 Worker：.venv/Scripts/python scripts/run_worker.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根，保证 worker 可导入

from worker.main import worker_loop

if __name__ == "__main__":
    worker_loop()
