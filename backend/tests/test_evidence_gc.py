import os
import time
from pathlib import Path

from backend.app.services.evidence_gc import (
    purge_quarantined_evidence,
    quarantine_orphan_directories,
    scan_orphan_directories,
)


def _age(path: Path, seconds: int) -> None:
    timestamp = time.time() - seconds
    os.utime(path, (timestamp, timestamp))


def test_scan_orphan_directories_keeps_live_recent_and_unknown_entries(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    stale_orphan = root / "101"
    stale_orphan.mkdir()
    _age(stale_orphan, 4 * 24 * 3600)
    recent_orphan = root / "102"
    recent_orphan.mkdir()
    live_task = root / "103"
    live_task.mkdir()
    legacy_orphan = root / "104_paused_20260821"
    legacy_orphan.mkdir()
    _age(legacy_orphan, 4 * 24 * 3600)
    unknown = root / "not-a-task"
    unknown.mkdir()

    candidates = scan_orphan_directories(
        root,
        live_task_ids={103},
        now=time.time(),
        grace_seconds=72 * 3600,
    )

    assert [path.name for path in candidates] == ["101", "104_paused_20260821"]


def test_quarantine_orphan_directories_moves_only_validated_children(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    stale = root / "201"
    stale.mkdir()
    (stale / "timeline.json").write_text("{}", encoding="utf-8")

    result = quarantine_orphan_directories([stale], root, now=time.time())

    assert result["moved"] == 1
    assert not stale.exists()
    trash_entries = list((root / ".trash").iterdir())
    assert len(trash_entries) == 1
    assert trash_entries[0].is_dir()
    assert (trash_entries[0] / "timeline.json").read_text(encoding="utf-8") == "{}"


def test_purge_quarantined_evidence_removes_only_expired_managed_entries(tmp_path):
    trash = tmp_path / ".trash"
    trash.mkdir()
    expired = trash / "orphan-20200101T000000Z-deadbeef--301"
    expired.mkdir()
    keep = trash / "orphan-20990101T000000Z-deadbeef--302"
    keep.mkdir()
    unknown = trash / "manual-review"
    unknown.mkdir()

    result = purge_quarantined_evidence(trash, now=time.time(), retention_seconds=1)

    assert result["deleted"] == 1
    assert not expired.exists()
    assert keep.exists()
    assert unknown.exists()


def test_worker_gc_is_best_effort_and_passes_configured_limits(monkeypatch):
    import worker.main as worker_main

    calls = {}

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_cleanup(session, **kwargs):
        calls["session"] = session
        calls["kwargs"] = kwargs
        return {"candidate_count": 2, "moved": 2, "purged": 0, "errors": []}

    monkeypatch.setattr(worker_main, "SessionLocal", lambda: Session())
    monkeypatch.setattr(worker_main, "cleanup_orphan_evidence", fake_cleanup)
    monkeypatch.setitem(worker_main.config["storage"], "evidence_gc_enabled", True)
    monkeypatch.setitem(worker_main.config["storage"], "evidence_gc_grace_hours", 48)
    monkeypatch.setitem(worker_main.config["storage"], "evidence_gc_trash_retention_days", 5)
    monkeypatch.setitem(worker_main.config["storage"], "evidence_gc_max_dirs_per_run", 12)

    result = worker_main.run_evidence_gc()

    assert result["moved"] == 2
    assert calls["kwargs"] == {
        "grace_hours": 48.0,
        "trash_retention_days": 5.0,
        "max_dirs": 12,
    }
