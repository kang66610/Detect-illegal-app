import json
from datetime import datetime
from types import SimpleNamespace

from agent.common.event_log import record_event


def test_record_event_writes_a_user_visible_audit_record(tmp_path):
    context = SimpleNamespace(data_dir=tmp_path)

    result = record_event(context, "appium", "page_observed", activity="MainActivity", element_count=3)

    saved = list((tmp_path / "timeline").glob("*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text(encoding="utf-8")) == result["meta"]
    assert result["meta"]["source"] == "appium"
    assert result["meta"]["event_type"] == "page_observed"


def test_record_event_never_overwrites_same_type_emitted_in_same_clock_tick(tmp_path, monkeypatch):
    import agent.common.event_log as event_log

    class FixedDatetime:
        @classmethod
        def utcnow(cls):
            return datetime(2026, 8, 28, 12, 0, 0, 123456)

    monkeypatch.setattr(event_log, "datetime", FixedDatetime)
    context = SimpleNamespace(data_dir=tmp_path)

    first = record_event(context, "appium", "app_foreground_recovered", attempt=1)
    second = record_event(context, "appium", "app_foreground_recovered", attempt=2)

    saved = list((tmp_path / "timeline").glob("*.json"))
    assert len(saved) == 2
    assert first["path"] != second["path"]
