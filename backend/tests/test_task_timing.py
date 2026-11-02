from datetime import datetime, timedelta

from agent.agent_core.task_manager import (
    active_duration_seconds,
    begin_active_timing,
    freeze_active_timing,
)


def test_freezing_active_timing_stops_the_clock_while_paused():
    started = datetime(2026, 8, 27, 10, 0, 0)
    running = begin_active_timing({}, started)

    paused = freeze_active_timing(
        running,
        started_at=started,
        at=started + timedelta(seconds=12),
    )

    assert paused["timing_active_seconds"] == 12
    assert paused["timing_segment_started_at"] is None
    assert active_duration_seconds(
        paused,
        started_at=started,
        now=started + timedelta(hours=1),
    ) == 12


def test_resuming_active_timing_continues_from_the_frozen_total():
    started = datetime(2026, 8, 27, 10, 0, 0)
    paused = freeze_active_timing(
        begin_active_timing({}, started),
        started_at=started,
        at=started + timedelta(seconds=12),
    )

    resumed_at = started + timedelta(minutes=5)
    resumed = begin_active_timing(paused, resumed_at)

    assert active_duration_seconds(
        resumed,
        started_at=started,
        now=resumed_at + timedelta(seconds=5),
    ) == 17


def test_pause_task_persists_a_frozen_duration(monkeypatch):
    import uuid

    import backend.app.services.task_service as task_service
    from backend.app.db import SessionLocal, init_db
    from backend.app.models import APKFile, DetectionTask
    from backend.app.services.task_service import pause_task

    init_db()
    frozen_now = datetime(2026, 8, 27, 10, 0, 12)

    class FrozenClock:
        @classmethod
        def utcnow(cls):
            return frozen_now

    monkeypatch.setattr(task_service, "datetime", FrozenClock)
    started = frozen_now - timedelta(seconds=12)
    with SessionLocal() as session:
        apk = APKFile(
            filename=f"timing-{uuid.uuid4().hex}.apk",
            sha256=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            size_bytes=1,
            parse_status="success",
            storage_path="x",
        )
        session.add(apk)
        session.flush()
        task = DetectionTask(
            apk_id=apk.id,
            status="traversing",
            started_at=started,
            progress=begin_active_timing({}, started),
        )
        session.add(task)
        session.commit()
        task_id = task.id

    pause_task(task_id)

    with SessionLocal() as session:
        task = session.query(DetectionTask).filter_by(id=task_id).one()
        assert task.status == "paused"
        assert task.progress["timing_active_seconds"] == 12
        assert task.progress["timing_segment_started_at"] is None
