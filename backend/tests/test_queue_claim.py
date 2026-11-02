import threading

from agent.agent_core.task_manager import claim_next_task
from backend.app.db import SessionLocal, init_db
from backend.app.models import APKFile, DetectionTask


def test_claim_is_atomic_two_sessions():
    """原子领取不变量（历史无关）：无重复领取、所有 queued 恰好各被领一次、非 queued 不被领取。

    共享 data/app.db 上其他测试会遗留 queued 行，因此不做「恰好 2 个」的精确计数，
    改为领取前统计全部 queued 任务（含遗留），N+1 线程并发领取后主线程补扫一轮
    （循环 claim_next_task 直到 None，即生产 worker 轮询兜底的真实行为），
    最终核对以下三点。
    """
    import uuid
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="a.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}", size_bytes=1, parse_status="success", storage_path="x")
        s.add(apk)
        s.commit()
        t1 = DetectionTask(apk_id=apk.id, status="queued")
        t2 = DetectionTask(apk_id=apk.id, status="queued")
        s.add_all([t1, t2])
        s.commit()
        t3 = DetectionTask(apk_id=apk.id, status="traversing")  # 不可领取
        s.add(t3)
        s.commit()
        queued_ids = {row.id for row in s.query(DetectionTask).filter_by(status="queued").all()}

    claimed = []
    lock = threading.Lock()

    def claim():
        with SessionLocal() as s:
            tid = claim_next_task(s)
            with lock:
                claimed.append(tid)

    # N+1 个线程并发领取 N 个排队任务：保证每个 queued 行都被抢过
    threads = [threading.Thread(target=claim) for _ in range(len(queued_ids) + 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 主线程补扫：败者线程可能耗尽 3 次重试仍漏掉后续候选，补扫保证无遗漏
    with SessionLocal() as s:
        while True:
            tid = claim_next_task(s)
            if tid is None:
                break
            with lock:
                claimed.append(tid)

    got = [c for c in claimed if c is not None]
    assert len(got) == len(set(got))  # ① 并发轮 + 补扫合计无重复领取
    assert set(got) == queued_ids  # ② 每个排队任务恰好被领一次、无遗漏
    assert t3.id not in got  # ③ 非 queued 状态不被领取


def test_claim_decrements_queue_positions_of_remaining_queued():
    """领取成功后，其余排队任务的排队位置整体减 1（被领取者本身不再排队）。"""
    import uuid
    from datetime import datetime
    init_db()
    with SessionLocal() as s:
        apk = APKFile(filename="q.apk", sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
                      size_bytes=1, parse_status="success", storage_path="x")
        s.add(apk)
        s.commit()
        old = datetime(2020, 1, 1)  # 置为最早，保证本轮领取先取到这三个任务（不受遗留行干扰）
        t1 = DetectionTask(apk_id=apk.id, status="queued", queue_position=1, created_at=old)
        t2 = DetectionTask(apk_id=apk.id, status="queued", queue_position=2, created_at=old)
        t3 = DetectionTask(apk_id=apk.id, status="queued", queue_position=3, created_at=old)
        s.add_all([t1, t2, t3])
        s.commit()
        ids = (t1.id, t2.id, t3.id)

    with SessionLocal() as s:
        claimed = claim_next_task(s)

    assert claimed == t1.id  # 按 created_at+id 领取最靠前的任务
    with SessionLocal() as s:
        rows = {t.id: t for t in s.query(DetectionTask).filter(DetectionTask.id.in_(ids)).all()}
    assert rows[t1.id].status == "preparing"
    assert rows[t1.id].queue_position is None
    assert rows[t1.id].progress["message"] == "任务已被检测 Worker 领取，正在准备检测环境"
    assert rows[t2.id].queue_position == 1  # 2 -> 1
    assert rows[t3.id].queue_position == 2  # 3 -> 2


def test_claim_preserves_resume_and_probe_metadata():
    import uuid
    from datetime import datetime

    init_db()
    with SessionLocal() as s:
        apk = APKFile(
            filename="resume-q.apk",
            sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1,
            parse_status="success",
            storage_path="x",
        )
        s.add(apk)
        s.commit()
        task = DetectionTask(
            apk_id=apk.id,
            status="queued",
            created_at=datetime(2019, 1, 1),
            progress={
                "resume_requested": True,
                "probe_profiles": ["deny", "allow"],
                "probe_profile": "dual",
            },
        )
        s.add(task)
        s.commit()
        task_id = task.id

    with SessionLocal() as s:
        assert claim_next_task(s) == task_id

    with SessionLocal() as s:
        progress = s.query(DetectionTask).filter_by(id=task_id).one().progress
        assert progress["resume_requested"] is True
        assert progress["probe_profiles"] == ["deny", "allow"]
        assert progress["probe_profile"] == "dual"
