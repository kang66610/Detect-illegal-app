from pathlib import Path
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.app.api import apk, report, review, task
from backend.app.config import config
from backend.app.db import init_db

app = FastAPI(title="App 隐私合规自动化检测平台", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # 开发期 vite
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

app.include_router(apk.router)
app.include_router(task.router)
app.include_router(report.router)
app.include_router(review.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/system/runtime")
def runtime_info():
    """Expose the non-sensitive production capabilities used by every task."""
    llm = config["llm"]
    return {
        "explorer": "real",
        "monitor": "real",
        "llm_configured": bool(os.environ.get(llm["api_key_env"])),
    }


# 生产构建产物托管（frontend/dist 存在时）
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_index = _dist / "index.html"


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """SPA history 路由回退：前端深链（如 /report/1）刷新时由前端 router 接管。

    - api 前缀与文档页（docs/redoc/openapi.json）不在回退范围，
      文档页 V1.0 暂不可用，返回 404 可接受；
    - dist 中真实存在的静态文件（js/css 等）直接返回；
    - 其余路径回退 dist/index.html，未构建（index 不存在）则 404。
    """
    if full_path.startswith("api") or full_path in ("docs", "redoc", "openapi.json"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    target = (_dist / full_path).resolve()
    try:
        target.relative_to(_dist.resolve())  # 防目录穿越，限定在 dist 内
    except ValueError:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    if target.is_file():
        return FileResponse(target)
    if _index.exists():
        return FileResponse(_index)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})
