from backend.app.services.task_service import (
    _attach_event_descriptions,
    _slice_timeline_events,
    _timeline_event_sort_key,
)


def test_frida_observed_at_is_sorted_with_appium_utc_time():
    before = {"time": "2026-08-25T09:00:00.000000", "source": "appium"}
    frida = {
        "time": 1787648400000,
        "observed_at": "2026-08-25T09:00:01.000000",
        "source": "frida",
    }
    after = {"time": "2026-08-25T09:00:02.000000", "source": "appium"}

    assert sorted([after, frida, before], key=_timeline_event_sort_key) == [before, frida, after]


def test_timeline_events_receive_backend_text_descriptions():
    events = [
        {"time": "2026-08-27T10:00:00", "source": "appium", "event_type": "document_read_complete",
         "document": ".WebViewActivity:document:隐私政策", "document_kind": "privacy_policy", "scrolls": 3},
        {"time": "2026-08-27T10:00:01", "source": "frida", "event_type": "hook_captured",
         "type": "device_id"},
        {"time": "2026-08-27T10:00:02", "source": "appium", "event_type": "brand_new_future_event"},
    ]

    enriched = _attach_event_descriptions(events)

    assert "隐私政策" in enriched[0]["text"]
    assert "已全部阅读" in enriched[0]["text"]
    # 无法描述的事件保持原样，前端回退到本地映射。
    assert "text" not in enriched[1]
    assert "text" not in enriched[2]


_EVENTS = [
    {"time": f"2026-08-27T10:00:{index:02d}", "source": "appium", "event_type": f"e{index}"}
    for index in range(10)
]


def test_timeline_tail_page_is_the_default_cursor_window():
    page = _slice_timeline_events(_EVENTS, after=None, before=None, limit=3)

    assert page["total"] == 10
    assert page["start"] == 7
    assert [row["event_type"] for row in page["events"]] == ["e7", "e8", "e9"]


def test_timeline_after_cursor_returns_everything_new_for_polling():
    page = _slice_timeline_events(_EVENTS, after=7, before=None, limit=None)

    assert page["start"] == 7
    assert page["total"] == 10
    assert [row["event_type"] for row in page["events"]] == ["e7", "e8", "e9"]


def test_timeline_before_with_limit_prepends_older_pages_without_overlap():
    page = _slice_timeline_events(_EVENTS, after=None, before=7, limit=3)

    assert page["start"] == 4
    assert [row["event_type"] for row in page["events"]] == ["e4", "e5", "e6"]


def test_timeline_cursors_are_clamped_to_available_range():
    empty_tail = _slice_timeline_events(_EVENTS, after=99, before=None, limit=None)
    assert empty_tail["events"] == []
    assert empty_tail["start"] == 10

    head = _slice_timeline_events(_EVENTS, after=None, before=0, limit=5)
    assert head["start"] == 0
    assert head["events"] == []


def test_timeline_cursor_pages_carry_descriptions_and_no_legacy_shape_change():
    events = _attach_event_descriptions([{
        "time": "2026-08-27T10:00:00", "source": "appium",
        "event_type": "document_read_complete",
        "document": ".WebViewActivity:document:隐私政策",
        "document_kind": "privacy_policy", "scrolls": 2,
    }])
    page = _slice_timeline_events(events, after=0, before=None, limit=None)

    assert "已全部阅读" in page["events"][0]["text"]
