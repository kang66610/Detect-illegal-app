"""Screenshot text recovery when the accessibility tree is empty or unlabeled.

Backends are optional: pytesseract when installed, otherwise an injectable
extractor for tests.  Missing OCR never invents violations — it only restores
labels so role classification and policy capture can run.
"""
from __future__ import annotations

import re
from pathlib import Path

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_PRIVACY_HINTS = (
    "隐私", "政策", "协议", "条款", "设置", "我的", "账号", "注销", "投诉", "举报",
    "撤回", "授权", "同意", "客服", "sdk", "个性化", "广告", "关于",
    "未登录", "未登陆", "登录", "privacy", "policy", "terms", "settings", "account", "agree",
    # 4.2 / 客服媒体形态族：树缺标签时 OCR 合成可点目标
    "语音", "麦克风", "按住说话", "录音", "拍照", "相机", "相册", "图片", "上传", "附件",
    "voice", "microphone", "camera", "gallery", "album", "upload", "attach",
    # 条款意图族（披露/清单）
    "收集清单", "共享清单", "sdk目录", "sdk清单", "第三方",
)


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = _BOUNDS_RE.search(str(value or ""))
    if not match:
        return None
    left, top, right, bottom = (int(match.group(i)) for i in range(1, 5))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


last_ocr_error_text = ""


def last_ocr_error() -> str:
    return last_ocr_error_text


def extract_words_from_image(path: Path, *, backend=None) -> list[dict]:
    """Return OCR words with optional boxes: {text, left, top, width, height}."""
    global last_ocr_error_text
    last_ocr_error_text = ""
    if backend is not None:
        return list(backend(path) or [])
    return _extract_with_pytesseract(path)


def _configure_pytesseract(pytesseract_module) -> None:
    """Point pytesseract at a Windows install when PATH is stale/missing."""
    import os
    import shutil

    configured = str(getattr(pytesseract_module.pytesseract, "tesseract_cmd", "") or "")
    if configured and configured != "tesseract" and Path(configured).is_file():
        pass
    else:
        cmd = shutil.which("tesseract") or ""
        if not cmd:
            for candidate in (
                os.environ.get("TESSERACT_CMD", ""),
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ):
                if candidate and Path(candidate).is_file():
                    cmd = candidate
                    break
        if cmd:
            pytesseract_module.pytesseract.tesseract_cmd = cmd

    # Prefer project/local tessdata (chi_sim) when Program Files is not writable.
    # This Tesseract build treats TESSDATA_PREFIX as the tessdata directory itself.
    if not os.environ.get("TESSDATA_PREFIX"):
        root = Path(__file__).resolve().parents[2]
        local_tessdata = root / "tools" / "tesseract" / "tessdata"
        if (local_tessdata / "eng.traineddata").is_file():
            os.environ["TESSDATA_PREFIX"] = str(local_tessdata) + os.sep


def _extract_with_pytesseract(path: Path) -> list[dict]:
    global last_ocr_error_text
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        last_ocr_error_text = f"pytesseract_missing:{exc}"
        return []
    _configure_pytesseract(pytesseract)
    try:
        image = Image.open(path)
        data = pytesseract.image_to_data(image, lang="chi_sim+eng", output_type=pytesseract.Output.DICT)
    except Exception as exc:
        try:
            image = Image.open(path)
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except Exception as fallback_exc:
            last_ocr_error_text = f"{type(fallback_exc).__name__}:{fallback_exc}"
            return []
        last_ocr_error_text = f"chi_sim_failed:{type(exc).__name__}:{exc}"
    words: list[dict] = []
    for index, text in enumerate(data.get("text") or []):
        value = str(text or "").strip()
        if not value:
            continue
        try:
            conf = float(data["conf"][index])
        except (KeyError, TypeError, ValueError):
            conf = -1
        if conf >= 0 and conf < 40:
            continue
        words.append({
            "text": value,
            "left": int(data["left"][index]),
            "top": int(data["top"][index]),
            "width": int(data["width"][index]),
            "height": int(data["height"][index]),
            "confidence": conf,
        })
    return words


def tree_needs_screen_text(elements: list[dict], *, force: bool = False) -> bool:
    """True when the accessibility tree is empty/sparse or a caller forces OCR."""
    if force:
        return True
    if not elements:
        return True
    clickable = [item for item in elements if item.get("clickable")]
    if not clickable:
        return False
    labeled = [
        item for item in clickable
        if str(item.get("text") or "").strip() or str(item.get("content_desc") or "").strip()
    ]
    # At most ~25% of clickables carry a label → recover from screenshot.
    # A single well-labeled button must not trigger OCR (1/1 would fail a
    # naive ``labeled <= 1`` threshold).
    return len(labeled) * 4 <= len(clickable)


def merge_ocr_into_elements(elements: list[dict], words: list[dict]) -> list[dict]:
    """Attach OCR labels to unlabeled clickables and synthesize privacy targets."""
    if not words:
        return elements
    enriched = [dict(item) for item in elements]
    claimed: set[int] = set()
    for item in enriched:
        if not item.get("clickable"):
            continue
        if str(item.get("text") or "").strip() or str(item.get("content_desc") or "").strip():
            continue
        box = parse_bounds(str(item.get("bounds") or ""))
        if not box:
            continue
        hits = []
        for index, word in enumerate(words):
            if index in claimed:
                continue
            center_x = int(word.get("left") or 0) + int(word.get("width") or 0) // 2
            center_y = int(word.get("top") or 0) + int(word.get("height") or 0) // 2
            if box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]:
                hits.append(str(word.get("text") or "").strip())
                claimed.add(index)
        if hits:
            label = " ".join(hits)[:80]
            item["text"] = label
            item["content_desc"] = item.get("content_desc") or label
            if not item.get("target") or str(item.get("target")).startswith("bounds:"):
                item["target"] = label
            item["ocr_enriched"] = True
    for index, word in enumerate(words):
        if index in claimed:
            continue
        text = str(word.get("text") or "").strip()
        if not text or not _looks_privacy_related(text):
            continue
        left = int(word.get("left") or 0)
        top = int(word.get("top") or 0)
        right = left + max(1, int(word.get("width") or 1))
        bottom = top + max(1, int(word.get("height") or 1))
        bounds = f"[{left},{top}][{right},{bottom}]"
        enriched.append({
            "resource_id": "",
            "text": text,
            "content_desc": text,
            "target": f"bounds:{bounds}",
            "clickable": True,
            "bounds": bounds,
            "class_name": "ocr.SyntheticLabel",
            "checked": False,
            "checkable": False,
            "scrollable": False,
            "ocr_sourced": True,
        })
    return enriched


def ocr_text_blob(words: list[dict]) -> str:
    return " ".join(str(word.get("text") or "").strip() for word in words if str(word.get("text") or "").strip())


def _looks_privacy_related(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in _PRIVACY_HINTS)
