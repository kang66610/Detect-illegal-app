import threading
import time
from hashlib import sha256
from pathlib import Path

from agent.agent_core.task_manager import claim_next_task
from agent.agent_core.workflow import run_task
from agent.common.logger import get_logger
from backend.app.config import PROJECT_ROOT, config
from backend.app.db import SessionLocal, init_db
from backend.app.models import DetectionTask
from backend.app.services.evidence_gc import cleanup_orphan_evidence
from worker.device_lock import DeviceLock

logger = get_logger("worker")


def uses_real_device(cfg: dict) -> bool:
    return True


def effective_max_concurrent(cfg: dict) -> int:
    """Never let one AVD be driven by parallel task threads."""
    return 1


def device_lock_path(cfg: dict) -> Path:
    appium = cfg.get("appium", {})
    frida = cfg.get("frida", {})
    device_id = str(appium.get("udid") or frida.get("device_id") or "default-device")
    digest = sha256(device_id.encode("utf-8")).hexdigest()[:16]
    return PROJECT_ROOT / "data" / "runtime-locks" / f"device-{digest}.lock"


def worker_lock_path() -> Path:
    """One process may claim tasks from this local workspace at a time."""
    return PROJECT_ROOT / "data" / "runtime-locks" / "worker.loop.lock"


def note_device_lock_wait() -> None:
    """Expose a real device-lock wait instead of silently leaving a task queued."""
    with SessionLocal() as session:
        task = (
            session.query(DetectionTask)
            .filter(DetectionTask.status == "queued")
            .order_by(DetectionTask.created_at, DetectionTask.id)
            .first()
        )
        if task is None:
            return
        progress = dict(task.progress or {})
        message = "检测设备正被其他任务占用，正在等待设备释放"
        if progress.get("waiting_for") == "device_lock" and progress.get("message") == message:
            return
        progress.update({"stage": "queued", "percent": 3, "waiting_for": "device_lock", "message": message})
        task.progress = progress
        task.current_page = "等待检测设备释放"
        session.commit()


def run_evidence_gc() -> dict | None:
    """Reconcile stale evidence directories once per Worker process."""
    storage = config.get("storage", {})
    if not bool(storage.get("evidence_gc_enabled", True)):
        logger.info("证据目录自动清理已禁用")
        return None
    try:
        with SessionLocal() as session:
            result = cleanup_orphan_evidence(
                session,
                grace_hours=float(storage.get("evidence_gc_grace_hours", 72)),
                trash_retention_days=float(storage.get("evidence_gc_trash_retention_days", 7)),
                max_dirs=int(storage.get("evidence_gc_max_dirs_per_run", 500)),
            )
        logger.info(
            "证据目录自动清理完成：发现 %s 个孤儿目录，隔离 %s 个，永久清理 %s 个%s",
            result["candidate_count"], result["moved"], result["purged"],
            f"，错误 {len(result['errors'])} 个" if result["errors"] else "",
        )
        return result
    except Exception:
        # Evidence GC must never prevent the Worker from accepting real tasks.
        logger.exception("证据目录自动清理失败，继续启动 Worker")
        return None


def worker_loop() -> None:
    # A second polling loop in the same SQLite workspace can race task status
    # updates after a restart.  Refuse it before it is able to claim work.
    loop_lock = DeviceLock(worker_lock_path())
    if not loop_lock.acquire():
        logger.warning("A Worker is already active; refusing duplicate polling loop")
        return
    init_db()  # 冷库启动：不经 API 单独拉起 worker 时也保证建表（create_all 幂等）
    run_evidence_gc()

    real_device = uses_real_device(config)
    max_concurrent = effective_max_concurrent(config)
    storage = config.get("storage", {})
    evidence_gc_interval_seconds = max(
        300.0,
        float(storage.get("evidence_gc_interval_hours", 6)) * 3600,
    )
    next_evidence_gc_at = time.monotonic() + evidence_gc_interval_seconds
    if real_device:
        logger.info("真实设备模式已启用：同一设备只允许一个任务，跨 Worker 使用设备锁")
    running: dict[int, tuple[threading.Thread, DeviceLock | None]] = {}
    while True:
        if bool(storage.get("evidence_gc_enabled", True)) and time.monotonic() >= next_evidence_gc_at:
            run_evidence_gc()
            next_evidence_gc_at = time.monotonic() + evidence_gc_interval_seconds
        finished = [tid for tid, (th, _) in running.items() if not th.is_alive()]
        for tid in finished:
            _, lease = running.pop(tid)
            if lease:
                lease.release()
        while len(running) < max_concurrent:
            lease = DeviceLock(device_lock_path(config)) if real_device else None
            if lease and not lease.acquire():
                # Do not claim a queued task until the single AVD is free.
                note_device_lock_wait()
                break
            with SessionLocal() as s:
                task_id = claim_next_task(s)
            if task_id is None:
                if lease:
                    lease.release()
                break
            logger.info("领取任务 %s，当前并发 %s", task_id, len(running) + 1)
            th = threading.Thread(target=run_task, args=(task_id,), daemon=True)
            th.start()
            running[task_id] = (th, lease)
        time.sleep(config["worker"]["poll_interval_seconds"])


if __name__ == "__main__":
    worker_loop()
