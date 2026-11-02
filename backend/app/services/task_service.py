import json
from datetime import datetime, timezone

from agent.agent_core.task_manager import (
    TIMING_ACTIVE_SECONDS,
    TIMING_FINALIZED_AT,
    TIMING_PAUSED_AT,
    TIMING_SEGMENT_STARTED_AT,
    freeze_active_timing,
    set_status,
)
from agent.common.exceptions import TaskStateError
from sqlalchemy.orm import joinedload

from backend.app.db import SessionLocal
from backend.app.config import PROJECT_ROOT, config
from backend.app.models import APKFile, DetectionTask, Report
from backend.app.services.artifact_cleanup import delete_report_artifacts, delete_task_artifacts
from backend.app.services.task_cleanup import delete_task_records
from backend.app.services.timeline_text import describe_event


TERMINAL_STATUSES = {"completed", "failed", "canceled"}
DELETABLE_STATUSES = TERMINAL_STATUSES | {"paused"}
PAUSABLE_STATUSES = {"queued", "preparing", "installing", "static_analysis", "traversing", "analyzing", "reporting"}

_PROBE_LABELS = {
    "allow": ("consent_allow", "同意后收集路径"),
    "deny": ("permission_deny", "拒绝权限路径"),
    "observe": ("observe_only", "仅观察路径"),
}
_PROBE_PROGRESS_KEYS = ("probe_profile", "probe_profiles", "pair_group", "pair_role", "pair_label")


def _timeline_event_sort_key(event: dict) -> datetime:
    """Normalize Appium ISO and Frida epoch/observed timestamps to UTC."""
    value = event.get("observed_at") or event.get("time")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).replace(tzinfo=None)
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return datetime.min


def _probe_progress(profiles: list[str]) -> dict:
    if profiles == ["deny", "allow"]:
        return {
            "probe_profiles": profiles,
            "probe_profile": "dual",
            "pair_role": "dual_path",
            "pair_label": "拒绝权限 + 允许权限",
        }
    profile = profiles[0]
    role, label = _PROBE_LABELS.get(profile, (profile, profile))
    return {
        "probe_profiles": profiles,
        "probe_profile": profile,
        "pair_role": role,
        "pair_label": label,
    }


def _preserve_probe_meta(progress: dict | None) -> dict | None:
    if not progress:
        return None
    meta = {
        key: progress[key]
        for key in _PROBE_PROGRESS_KEYS
        if key in progress
    }
    return meta or None


def _preserve_timing_meta(progress: dict | None) -> dict:
    values = dict(progress or {})
    preserved = {}
    if TIMING_ACTIVE_SECONDS in values:
        preserved[TIMING_ACTIVE_SECONDS] = values[TIMING_ACTIVE_SECONDS]
    # A resumed task starts a fresh active segment when the worker claims it.
    preserved[TIMING_SEGMENT_STARTED_AT] = None
    preserved[TIMING_PAUSED_AT] = None
    preserved.pop(TIMING_FINALIZED_AT, None)
    return preserved


def create_task(
    apk_id: int,
    industry: str = "通用",
    mode: str = "deep",
    probe_profiles: list[str] | None = None,
) -> DetectionTask:
    """Create one task that runs deny then allow in the same report."""
    profiles = list(probe_profiles or ["deny", "allow"])
    if len(profiles) == 2 and set(profiles) == {"allow", "deny"}:
        profiles = ["deny", "allow"]
    for profile in profiles:
        if profile not in _PROBE_LABELS:
            raise TaskStateError("权限探针档位必须是 allow / deny / observe")
    with SessionLocal() as s:
        apk = s.query(APKFile).filter_by(id=apk_id).first()
        if apk is None:
            raise TaskStateError("APK 不存在")
        if apk.parse_status != "success":
            raise TaskStateError("APK 尚未解析成功，不能创建检测任务")
        if mode not in ("fast", "deep"):
            raise TaskStateError("检测档位必须是 fast 或 deep")
        queue_position = s.query(DetectionTask).filter_by(status="queued").count() + 1
        task = DetectionTask(
            apk_id=apk_id,
            industry=industry,
            mode=mode,
            status="queued",
            queue_position=queue_position,
            progress=_probe_progress(profiles),
        )
        s.add(task)
        s.commit()
        s.refresh(task)
        return task


def list_tasks(status: str | None = None) -> list[DetectionTask]:
    with SessionLocal() as s:
        q = s.query(DetectionTask).options(joinedload(DetectionTask.apk)).order_by(DetectionTask.created_at.desc())
        if status:
            q = q.filter(DetectionTask.status == status)
        tasks = q.all()
        for task in tasks:
            task.app_name = task.apk.app_name or task.apk.filename
            task.package_name = task.apk.package_name
        return tasks


def get_task(task_id: int) -> DetectionTask:
    with SessionLocal() as s:
        return s.query(DetectionTask).filter_by(id=task_id).one()


def _attach_event_descriptions(events: list[dict]) -> list[dict]:
    """为可识别的事件就地注入中文 ``text``，其余事件保持原样。"""
    for event in events:
        text = describe_event(event)
        if text:
            event["text"] = text
    return events


def _slice_timeline_events(
    events: list[dict], *, after: int | None, before: int | None, limit: int | None,
) -> dict:
    """时间线游标分页：下标基于全量有序事件（事件只追加、不改序，游标稳定）。

    - ``after=N``：返回 N 之后全部新事件（轮询追加）；
    - ``before=N`` + ``limit=M``：N 之前至多 M 条（向上加载更早）；
    - 仅 ``limit=M``：全量末尾 M 条（首次展开的尾部窗口）。
    调用方在无任何游标参数时必须继续返回纯数组，兼容旧构建的前端。
    """
    total = len(events)
    start, end = 0, total
    if after is not None:
        start = max(0, min(int(after), total))
    if before is not None:
        end = max(start, min(int(before), total))
    if limit is not None:
        start = max(start, end - max(0, int(limit)))
    return {"total": total, "start": start, "events": events[start:end]}


def get_task_timeline(
    task_id: int, *,
    after: int | None = None, before: int | None = None, limit: int | None = None,
) -> list[dict] | dict:
    """Return the complete, chronological audit trail produced for a task."""
    get_task(task_id)
    task_dir = PROJECT_ROOT / config["storage"]["evidence_dir"] / str(task_id)
    timeline_dir = task_dir / "timeline"
    events: list[dict] = []
    if timeline_dir.exists():
        for path in sorted(timeline_dir.glob("*.json")):
            try:
                events.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue

    frida_events = task_dir / "callstack" / "frida-events.json"
    if frida_events.exists():
        try:
            raw_events = json.loads(frida_events.read_text(encoding="utf-8")).get("events", [])
            for event in raw_events:
                time = event.get("observed_at") or event.get("time")
                if isinstance(time, (int, float)):
                    time = datetime.fromtimestamp(
                        time / 1000, tz=timezone.utc,
                    ).replace(tzinfo=None).isoformat()
                events.append({
                    **event,
                    "time": time or "",
                    "source": "frida",
                    "event_type": f"{event.get('type', 'event')}_captured",
                })
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    events = _attach_event_descriptions(sorted(events, key=_timeline_event_sort_key))
    if after is None and before is None and limit is None:
        return events
    return _slice_timeline_events(events, after=after, before=before, limit=limit)


def cancel_task(task_id: int) -> DetectionTask:
    with SessionLocal() as s:
        t = s.query(DetectionTask).filter_by(id=task_id).one()
        set_status(s, t, "canceled")
        return t


def terminate_task(task_id: int) -> DetectionTask:
    """Request cooperative termination and preserve a reportable run boundary.

    Active tasks keep their current status while the worker finishes the
    current safe boundary, consumes evidence gathered so far, and renders a
    partial report.  Workflow finalization then moves the task to ``canceled``;
    the worker thread's ``finally`` path closes Appium/Frida and releases the
    cross-process device lease.  Queued/paused tasks have no live engine, so
    they transition immediately without a report.
    """
    with SessionLocal() as s:
        task = s.query(DetectionTask).filter_by(id=task_id).one()
        if task.status == "canceled":
            return task
        if task.status in TERMINAL_STATUSES:
            raise TaskStateError("已完成或失败的任务不能终止")
        if task.status not in PAUSABLE_STATUSES:
            raise TaskStateError("当前任务状态不支持终止")
        progress = dict(task.progress or {})
        progress.update({
            "termination_requested": True,
            "termination_reason": "用户提前终止检测，等待 Worker 释放设备",
            "message": "终止请求已发送，正在停止遍历并生成终止前报告",
        })
        task.progress = progress
        task.failure_reason = "用户终止检测；Worker 将停止当前遍历并释放设备"
        # Keep an active task in its current stage until the worker has closed
        # Appium/Frida and generated the partial report.  The terminal
        # ``canceled`` transition is performed by workflow.py after reporting.
        # Queued/paused tasks have no live engine that can produce evidence;
        # terminate them immediately and release no device lease.
        if task.status in {"queued", "paused"}:
            set_status(s, task, "canceled", reason=task.failure_reason)
        else:
            s.commit()
        return task


def pause_task(task_id: int) -> DetectionTask:
    with SessionLocal() as s:
        task = s.query(DetectionTask).filter_by(id=task_id).one()
        if task.status not in PAUSABLE_STATUSES:
            raise TaskStateError("仅运行中或排队中的任务可以暂停")
        now = datetime.utcnow()
        progress = freeze_active_timing(task.progress, task.started_at, now)
        progress["paused_from"] = task.status
        task.progress = progress
        set_status(s, task, "paused")
        return task


def resume_task(task_id: int) -> DetectionTask:
    with SessionLocal() as s:
        task = s.query(DetectionTask).filter_by(id=task_id).one()
        if task.status != "paused":
            raise TaskStateError("仅已暂停任务可以继续")
        report_paths = [r.pdf_path for r in s.query(Report).filter_by(task_id=task_id).all()]
        old_progress = dict(task.progress or {})
        probe_meta = dict(_preserve_probe_meta(old_progress) or {})
        probe_meta.update(_preserve_timing_meta(old_progress))
        probe_meta.update({
            "resume_requested": True,
            "resume_count": int(old_progress.get("resume_count") or 0) + 1,
        })
        delete_task_records(s, task_id)
        task.progress = probe_meta
        task.failure_reason = None
        task.queue_position = s.query(DetectionTask).filter_by(status="queued").count() + 1
        set_status(s, task, "queued")
    # A resume is a continuation, not a retry. Keep the Appium timeline and
    # traversal checkpoint; only discard any half-generated report outputs.
    delete_report_artifacts(report_paths)
    return task


def retry_task(task_id: int) -> DetectionTask:
    """失败或已取消任务一键重跑：复用原配置回到排队。"""
    with SessionLocal() as s:
        t = s.query(DetectionTask).filter_by(id=task_id).one()
        if t.status not in {"failed", "canceled"}:
            raise TaskStateError("仅失败或已取消任务可以重跑")
        report_paths = [r.pdf_path for r in s.query(Report).filter_by(task_id=task_id).all()]
        probe_meta = _preserve_probe_meta(t.progress)
        delete_task_records(s, task_id)
        t.status = "queued"
        t.failure_reason = None
        t.finished_at = None
        t.progress = probe_meta
        t.pages_covered = 0
        t.scenarios_triggered = 0
        t.queue_position = s.query(DetectionTask).filter_by(status="queued").count() + 1
        s.commit()
        delete_task_artifacts(task_id, report_paths)
        return t


def delete_task(task_id: int) -> None:
    """Delete a completed, stopped, or paused task and its generated artifacts."""
    with SessionLocal() as s:
        task = s.query(DetectionTask).filter_by(id=task_id).one()
        if task.status not in DELETABLE_STATUSES:
            raise TaskStateError("仅已完成、失败、已取消或已暂停的任务可以删除")
        report_paths = [r.pdf_path for r in s.query(Report).filter_by(task_id=task_id).all()]
        delete_task_records(s, task_id)
        s.delete(task)
        s.commit()
    delete_task_artifacts(task_id, report_paths)
