from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm.exc import NoResultFound

from agent.common.exceptions import TaskStateError
from backend.app.schemas.task import TaskCreate, TaskOut
from backend.app.services import task_service

router = APIRouter(prefix="/api/tasks", tags=["task"])


@router.post("", response_model=TaskOut)
def create_task(body: TaskCreate):
    try:
        return task_service.create_task(body.apk_id, body.industry, body.mode)
    except TaskStateError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=list[TaskOut])
def list_tasks(status: str | None = Query(default=None)):
    return task_service.list_tasks(status)


@router.get("/{task_id}/timeline")
def get_task_timeline(
    task_id: int,
    after: int | None = Query(default=None, description="只返回该下标之后的新事件（轮询追加）"),
    before: int | None = Query(default=None, description="只返回该下标之前的事件"),
    limit: int | None = Query(default=None, description="配合 before/单独使用，限制返回条数（尾部窗口）"),
):
    """无游标参数时返回纯数组（兼容旧构建前端）；带游标时返回 {total,start,events}。"""
    try:
        return task_service.get_task_timeline(task_id, after=after, before=before, limit=limit)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="任务不存在")


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int):
    try:
        return task_service.get_task(task_id)
    except Exception:
        raise HTTPException(status_code=404, detail="任务不存在")


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: int):
    try:
        return task_service.cancel_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/terminate", response_model=TaskOut)
def terminate_task(task_id: int):
    """提前终止遍历；Worker 收到后释放 Appium/Frida 设备锁。"""
    try:
        return task_service.terminate_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/pause", response_model=TaskOut)
def pause_task(task_id: int):
    try:
        return task_service.pause_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/resume", response_model=TaskOut)
def resume_task(task_id: int):
    try:
        return task_service.resume_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/retry", response_model=TaskOut)
def retry_task(task_id: int):
    try:
        return task_service.retry_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{task_id}")
def delete_task(task_id: int):
    try:
        task_service.delete_task(task_id)
        return {"ok": True}
    except TaskStateError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NoResultFound:
        raise HTTPException(status_code=404, detail="任务不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除任务失败：{e}")
