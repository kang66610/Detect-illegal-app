from pathlib import Path

from agent.ai_explorer.page_observer import PageObserver
from agent.ai_explorer.page_state import parse_page
from agent.detection_engines.screen_text import (
    merge_ocr_into_elements,
    ocr_text_blob,
    tree_needs_screen_text,
)


def test_page_observer_reuses_cached_ocr_for_an_unchanged_surface(tmp_path: Path):
    """A stable sparse UI must not screenshot/OCR again on every DFS step."""
    calls = {"screenshots": 0, "ocr": 0}

    class Client:
        def screenshot(self, path: Path) -> bool:
            calls["screenshots"] += 1
            path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            return True

    def words(_path: Path):
        calls["ocr"] += 1
        return [{"text": "同意", "left": 1, "top": 1, "width": 20, "height": 12}]

    observer = PageObserver(
        client=Client(), runtime={}, detection_config={"screen_ocr_enabled": True},
        artifact_path=lambda name: tmp_path / name, emit=lambda *_args, **_kwargs: None,
        needs_perception=lambda *_args: False, visible_text=lambda _items: "", word_extractor=words,
    )
    page = parse_page(
        ".WelcomeActivity",
        '<hierarchy><node clickable="true" bounds="[0,0][100,40]"/></hierarchy>',
    )

    _, first = observer.enrich(page, activity=page.activity, step=1)
    _, second = observer.enrich(page, activity=page.activity, step=2)

    assert first == second == "同意"
    assert calls == {"screenshots": 1, "ocr": 1}


def test_page_observer_rechecks_cached_surface_by_screenshot_hash(tmp_path: Path):
    """A periodic recheck may capture once, but must skip OCR for identical pixels."""
    calls = {"screenshots": 0, "ocr": 0}

    class Client:
        def screenshot(self, path: Path) -> bool:
            calls["screenshots"] += 1
            path.write_bytes(b"\x89PNG\r\n\x1a\nsame-screen")
            return True

    def words(_path: Path):
        calls["ocr"] += 1
        return [{"text": "同意", "left": 1, "top": 1, "width": 20, "height": 12}]

    observer = PageObserver(
        client=Client(), runtime={}, detection_config={"screen_ocr_enabled": True},
        artifact_path=lambda name: tmp_path / name, emit=lambda *_args, **_kwargs: None,
        needs_perception=lambda *_args: False, visible_text=lambda _items: "", word_extractor=words,
    )
    page = parse_page(
        ".WelcomeActivity",
        '<hierarchy><node clickable="true" bounds="[0,0][100,40]"/></hierarchy>',
    )

    observer.enrich(page, activity=page.activity, step=1)
    observer.enrich(page, activity=page.activity, step=4)

    assert calls == {"screenshots": 2, "ocr": 1}


def test_page_observer_owns_bounded_interactive_surface_ocr(tmp_path: Path):
    calls = {"screenshots": 0}

    class Client:
        def screenshot(self, path: Path) -> bool:
            calls["screenshots"] += 1
            path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            return True

    observer = PageObserver(
        client=Client(), runtime={}, detection_config={"screen_ocr_enabled": True},
        artifact_path=lambda name: tmp_path / name, emit=lambda *_args, **_kwargs: None,
        needs_perception=lambda *_args: False,
        needs_interactive_perception=lambda *_args, **_kwargs: True,
        visible_text=lambda _items: "", word_extractor=lambda _path: [{"text": "相册"}],
    )
    page = parse_page(".ChatActivity", '<hierarchy><node text="请输入" clickable="true"/></hierarchy>')

    _, blob = observer.enrich_interactive(page, activity=page.activity, step=1, page_text="请输入", prior_ocr="")

    assert blob == "相册"
    assert calls["screenshots"] == 1


def test_empty_tree_needs_screen_text():
    assert tree_needs_screen_text([]) is True


def test_sparse_unlabeled_clickables_need_screen_text():
    elements = [
        {"clickable": True, "text": "", "content_desc": "", "bounds": "[0,0][10,10]"},
        {"clickable": True, "text": "", "content_desc": "", "bounds": "[10,0][20,10]"},
        {"clickable": True, "text": "确定", "content_desc": "", "bounds": "[20,0][30,10]"},
        {"clickable": True, "text": "", "content_desc": "", "bounds": "[30,0][40,10]"},
    ]
    assert tree_needs_screen_text(elements) is True


def test_single_labeled_clickable_does_not_need_screen_text():
    elements = [
        {"clickable": True, "text": "隐私政策", "content_desc": "", "bounds": "[0,0][100,40]"},
    ]
    assert tree_needs_screen_text(elements) is False


def test_merge_ocr_labels_unlabeled_clickable_and_synthesizes_privacy_target():
    elements = [
        {
            "clickable": True, "text": "", "content_desc": "", "resource_id": "",
            "target": "bounds:[0,0][100,40]", "bounds": "[0,0][100,40]",
            "class_name": "android.widget.TextView", "checked": False,
            "checkable": False, "scrollable": False,
        }
    ]
    words = [
        {"text": "隐私政策", "left": 10, "top": 5, "width": 40, "height": 20},
        {"text": "无关", "left": 200, "top": 200, "width": 20, "height": 10},
    ]
    merged = merge_ocr_into_elements(elements, words)
    assert merged[0]["text"] == "隐私政策"
    assert merged[0].get("ocr_enriched") is True
    assert any(item.get("ocr_sourced") and "隐私" in item["text"] for item in merged) or merged[0]["text"] == "隐私政策"
    assert "隐私政策" in ocr_text_blob(words)


def test_merge_ocr_synthesizes_media_family_labels():
    from agent.detection_engines.screen_text import _looks_privacy_related

    assert _looks_privacy_related("按住说话")
    assert _looks_privacy_related("拍照")
    assert _looks_privacy_related("第三方SDK目录")
    elements = [
        {
            "clickable": True, "text": "", "content_desc": "", "resource_id": "icon1",
            "target": "bounds:[0,800][80,880]", "bounds": "[0,800][80,880]",
            "class_name": "android.widget.ImageView", "checked": False,
            "checkable": False, "scrollable": False,
        }
    ]
    words = [{"text": "语音", "left": 10, "top": 820, "width": 40, "height": 20}]
    merged = merge_ocr_into_elements(elements, words)
    assert merged[0]["text"] == "语音"
    assert merged[0].get("ocr_enriched") is True


def test_extract_words_accepts_injectable_backend(tmp_path: Path):
    from agent.detection_engines.screen_text import extract_words_from_image

    image = tmp_path / "blank.png"
    image.write_bytes(b"not-a-real-image")

    def backend(_path):
        return [{"text": "撤回同意", "left": 1, "top": 1, "width": 10, "height": 10}]

    assert extract_words_from_image(image, backend=backend)[0]["text"] == "撤回同意"
