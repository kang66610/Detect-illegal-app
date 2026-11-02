import os
import sys
from pathlib import Path

# 测试使用独立数据库 data/test.db，避免污染平台运行库 data/app.db
# （必须在任何 backend 模块 import 之前设置：conftest 先于测试模块加载，
#  且 .env 加载用 setdefault，不会覆盖此处已存在的环境变量）
os.environ.setdefault("PRIVACY_DB_PATH", "data/test.db")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config):
    """把 tmp_path 的基目录固定在项目内，并且每次运行都用唯一子目录。

    两个坑都要绕开：

    1. 本机 ``%TEMP%\\pytest-of-<user>`` 存在 ACL 拒绝访问的历史残留，
       用默认 basetemp 会让上百个用例在 fixture 阶段直接 PermissionError。
    2. 固定 basetemp 目录时，pytest 启动要先清掉上一轮留下的目录；本机删除
       会被安全钩子拦下，于是第二次连续运行时同样整片报 error。改成每次唯一
       目录后不再需要清理，重复运行也不会互相踩。
    """
    if getattr(config.option, "basetemp", None):
        return  # 命令行显式指定时以命令行为准
    base = PROJECT_ROOT / "tmp" / f"pytest-run-{os.getpid()}"
    # tmp/ 被 .gitignore 忽略，干净 clone（CI）里并不存在；
    # 不先建父目录，pytest 会在创建 basetemp 时抛 FileNotFoundError，
    # 表现为上百个用例的 fixture 全部 error。
    base.parent.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(base)
