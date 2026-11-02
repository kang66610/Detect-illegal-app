from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from agent.common.exceptions import TaskStateError
from agent.common.backend_ports import DetectionTask

STATUS_FLOW = {
    "queued": {"preparing", "paused", "canceled"},
    "preparing": {"installing", "paused", "failed", "canceled"},
    "installing": {"static_analysis", "paused", "failed", "canceled"},
    "static_analysis": {"traversing", "paused", "failed", "canceled"},
    "traversing": {"analyzing", "paused", "failed", "canceled"},
    "analyzing": {"reporting", "paused", "failed", "canceled"},
    "reporting": {"completed", "paused", "failed", "canceled"},
    "paused": {"queued", "canceled"},
    "completed": set(),
    "failed": set(),
    "canceled": set(),
}

TIMING_ACTIVE_SECONDS = "timing_active_seconds"
TIMING_SEGMENT_STARTED_AT = "timing_segment_started_at"
TIMING_PAUSED_AT = "timing_paused_at"
TIMING_FINALIZED_AT = "timing_finalized_at"
TIMING_PROGRESS_KEYS = (
    TIMING_ACTIVE_SECONDS,
    TIMING_SEGMENT_STARTED_AT,
    TIMING_PAUSED_AT,
    TIMING_FINALIZED_AT,
)


def _as_utc_naive(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _timing_iso(value: datetime) -> str:
    return _as_utc_naive(value).isoformat(timespec="milliseconds")


def _timing_number(value: float) -> int | float:
    rounded = round(max(0.0, float(value)), 3)
    return int(rounded) if rounded.is_integer() else rounded


def active_duration_seconds(
    progress: dict | None,
    started_at: datetime | None,
    now: datetime | None = None,
) -> int | float:
    """Return effective running time, excluding paused intervals."""
    current = _as_utc_naive(now) or datetime.utcnow()
    values = dict(progress or {})
    has_total = TIMING_ACTIVE_SECONDS in values
    try:
        total = float(values.get(TIMING_ACTIVE_SECONDS) or 0)
    except (TypeError, ValueError):
        total = 0.0
    segment_started = _as_utc_naive(values.get(TIMING_SEGMENT_STARTED_AT))
    if segment_started is None and not has_total and not values.get(TIMING_PAUSED_AT):
        segment_started = _as_utc_naive(started_at)
    if segment_started is not None:
        total += max(0.0, (current - segment_started).total_seconds())
    return _timing_number(total)


def begin_active_timing(progress: dict | None, at: datetime | None = None) -> dict:
    """Start a new active segment while preserving prior active seconds."""
    values = dict(progress or {})
    try:
        existing = float(values.get(TIMING_ACTIVE_SECONDS) or 0)
    except (TypeError, ValueError):
        existing = 0.0
    values[TIMING_ACTIVE_SECONDS] = _timing_number(existing)
    values[TIMING_SEGMENT_STARTED_AT] = _timing_iso(_as_utc_naive(at) or datetime.utcnow())
    values[TIMING_PAUSED_AT] = None
    values.pop(TIMING_FINALIZED_AT, None)
    return values


def freeze_active_timing(
    progress: dict | None,
    started_at: datetime | None,
    at: datetime | None = None,
    *,
    finalized: bool = False,
) -> dict:
    """Freeze the active segment for pause or terminal task states."""
    current = _as_utc_naive(at) or datetime.utcnow()
    values = dict(progress or {})
    values[TIMING_ACTIVE_SECONDS] = active_duration_seconds(values, started_at, current)
    values[TIMING_SEGMENT_STARTED_AT] = None
    values[TIMING_PAUSED_AT] = _timing_iso(current) if not finalized else None
    if finalized:
        values[TIMING_FINALIZED_AT] = _timing_iso(current)
    else:
        values.pop(TIMING_FINALIZED_AT, None)
    return values


def can_transition(current: str, nxt: str) -> bool:
    return nxt in STATUS_FLOW.get(current, set())


def set_status(session: Session, task: DetectionTask, status: str, reason: str | None = None) -> None:
    if not can_transition(task.status, status):
        raise TaskStateError(f"非法状态流转：{task.status} -> {status}（task_id={task.id}）")
    now = datetime.utcnow()
    task.status = status
    if status == "preparing":
        task.started_at = task.started_at or now
        task.progress = begin_active_timing(task.progress, now)
    if status in ("completed", "failed", "canceled"):
        task.progress = freeze_active_timing(
            task.progress, task.started_at, now, finalized=True,
        )
        task.finished_at = now
    if reason:
        task.failure_reason = reason
    session.commit()


def claim_next_task(session: Session, max_attempts: int = 3) -> int | None:
    """原子领取一个排队任务：候选行 + 条件 UPDATE，rowcount==1 才算领取成功。

    候选被其他 worker 抢走时重试下一个候选（最多 max_attempts 次），
    避免「候选被抢 → 本次白跑一趟」导致领取率下降。
    """
    for _ in range(max_attempts):
        candidate = (
            session.query(DetectionTask)
            .filter(DetectionTask.status == "queued")
            .order_by(DetectionTask.created_at, DetectionTask.id)
            .first()
        )
        if candidate is None:
            return None
        now = datetime.utcnow()
        claimed_progress = begin_active_timing(candidate.progress, now)
        claimed_progress.update({
            "stage": "preparing",
            "percent": 8,
            "message": "任务已被检测 Worker 领取，正在准备检测环境",
        })
        result = session.execute(
            update(DetectionTask)
            .where(DetectionTask.id == candidate.id, DetectionTask.status == "queued")
            .values(
                status="preparing",
                started_at=candidate.started_at or now,
                queue_position=None,
                progress=claimed_progress,
            )
        )
        if result.rowcount == 1:
            # 领取成功：其余排队任务的排队位置整体前移一位（表达式自减，原子更新）
            session.execute(
                update(DetectionTask)
                .where(DetectionTask.status == "queued", DetectionTask.queue_position.isnot(None))
                .values(queue_position=DetectionTask.queue_position - 1)
            )
            session.commit()
            return candidate.id
        # 被其他 worker 抢走：提交释放写事务，重试下一个候选
        session.commit()
    return None
