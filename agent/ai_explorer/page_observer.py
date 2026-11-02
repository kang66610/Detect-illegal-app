"""Page observation adapter: screenshot OCR, caching and enriched snapshots."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from agent.ai_explorer.page_state import page_from_elements
from agent.detection_engines.screen_text import (
    extract_words_from_image,
    last_ocr_error,
    merge_ocr_into_elements,
    ocr_text_blob,
    tree_needs_screen_text,
)


class PerceptionOcrPolicy:
    """Pure, bounded OCR triggers for sparse first-run and chat surfaces."""

    def __init__(
        self,
        *,
        has_document_body: Callable[[str, list[dict]], bool],
        is_consent: Callable[[list[dict]], bool],
        is_launch_gate: Callable[[str], bool],
        visible_text: Callable[[list[dict]], str],
        is_settings_hub: Callable[[str, list[dict]], bool],
        element_label: Callable[[dict], str],
    ) -> None:
        self.has_document_body = has_document_body
        self.is_consent = is_consent
        self.is_launch_gate = is_launch_gate
        self.visible_text = visible_text
        self.is_settings_hub = is_settings_hub
        self.element_label = element_label

    def needs_perception(self, activity: str, elements: list[dict]) -> bool:
        if self.has_document_body(activity, elements) and not self.is_consent(elements):
            return False
        if self.is_consent(elements) or self.is_launch_gate(activity):
            return True
        page_text = self.visible_text(elements).lower()
        act = str(activity or "").lower()
        if any(term in act for term in ("kefu", "chat", "imactivity", "customer")):
            return True
        if any(term in page_text for term in ("客服", "请输入", "咨询", "customer service")):
            return not self._has_labeled_media(elements)
        if self.is_settings_hub(activity, elements):
            compact = "".join(self.visible_text(elements).split()).lower()
            return len(compact) < 8
        return False

    def needs_interactive_ocr(
        self, activity: str, page_text: str, elements: list[dict], *, has_ocr: bool,
    ) -> bool:
        if has_ocr:
            return False
        text = str(page_text or "").lower()
        if not (
            "客服" in text
            or "customer service" in text
            or "请输入" in text
            or any(term in str(activity or "").lower() for term in (
                "kefu", "chat", "imactivity", "customer", "support",
            ))
        ):
            return False
        # This mirrors the legacy post-observation chat branch: once a
        # customer-service/chat surface is recognized and OCR has not yet
        # produced text, perform exactly one forced pass even if the tree
        # already labels a media control.
        return True

    def _has_labeled_media(self, elements: list[dict]) -> bool:
        labels = ("语音", "麦克风", "拍照", "相册", "上传", "voice", "camera", "album", "upload")
        return any(
            any(term in self.element_label(item).lower() for term in labels)
            for item in elements if item.get("clickable")
        )


def _raster_ready(path: Path) -> bool:
    try:
        header = path.read_bytes()[:8]
    except OSError:
        return False
    return header.startswith(b"\x89PNG") or header.startswith(b"\xff\xd8")


class PageObserver:
    """Turn an accessibility snapshot into one stable Page observation."""

    def __init__(
        self,
        *,
        client,
        runtime: dict,
        detection_config: dict,
        artifact_path: Callable[[str], Path],
        emit: Callable[..., None],
        needs_perception: Callable[[str, list[dict]], bool],
        visible_text: Callable[[list[dict]], str],
        needs_interactive_perception: Callable[[str, str, list[dict]], bool] | None = None,
        word_extractor: Callable[[Path], list[dict]] = extract_words_from_image,
        ocr_error: Callable[[], str] = last_ocr_error,
    ) -> None:
        self.client = client
        self.runtime = runtime
        self.config = detection_config
        self.artifact_path = artifact_path
        self.emit = emit
        self.needs_perception = needs_perception
        self.needs_interactive_perception = needs_interactive_perception or (
            lambda _activity, _text, _elements: False
        )
        self.visible_text = visible_text
        self.word_extractor = word_extractor
        self.ocr_error = ocr_error

    def enrich(self, page, *, activity: str, step: int):
        key = str(getattr(page, "surface_fingerprint", "") or activity)
        cache = self.runtime.setdefault("screen_text_by_surface", {})
        cached = self._cache_entry(cache.get(key), step=step)
        if cached and not self._cache_recheck_due(cached, step=step):
            blob = str(cached["text"])
            self.emit("screen_text_cache_reused", activity=activity, step=step, reason="stable_surface")
        elif cached:
            shot = self._capture_screenshot(step=step, suffix="recheck")
            screenshot_hash = self._screenshot_hash(shot) if shot else ""
            if screenshot_hash and screenshot_hash == str(cached.get("screenshot_hash") or ""):
                cached["verified_step"] = step
                cache[key] = cached
                blob = str(cached["text"])
                self.emit("screen_text_cache_reused", activity=activity, step=step, reason="same_screenshot")
            else:
                page, blob, screenshot_hash = self._ocr(
                    page, activity=activity, step=step,
                    force=self.needs_perception(activity, page.elements), screenshot_path=shot,
                )
                if blob:
                    cache[key] = self._cache_value(blob, screenshot_hash, step)
        else:
            page, blob, screenshot_hash = self._ocr(page, activity=activity, step=step, force=False)
            if blob:
                cache[key] = self._cache_value(blob, screenshot_hash, step)
            elif self.needs_perception(activity, page.elements):
                page, blob, screenshot_hash = self._ocr(page, activity=activity, step=step, force=True)
                if blob:
                    cache[key] = self._cache_value(blob, screenshot_hash, step)
            if not blob:
                blob = self.visible_text(page.elements)
        self.runtime["last_screen_text"] = blob
        return page, blob

    def force_ocr(self, page, *, activity: str, step: int):
        page, blob, _ = self._ocr(page, activity=activity, step=step, force=True)
        return page, blob

    def enrich_interactive(
        self, page, *, activity: str, step: int, page_text: str, prior_ocr: str,
    ):
        """Run one bounded OCR pass only when the injected policy requires it."""
        if prior_ocr or not self.needs_interactive_perception(activity, page_text, page.elements):
            return page, prior_ocr
        return self.force_ocr(page, activity=activity, step=step)

    def _ocr(self, page, *, activity: str, step: int, force: bool, screenshot_path: Path | None = None):
        if not self.config.get("screen_ocr_enabled", True):
            return page, "", ""
        if not tree_needs_screen_text(page.elements, force=force):
            return page, "", ""
        shot = screenshot_path or self._capture_screenshot(step=step, suffix="ocr")
        if shot is None:
            self.emit("screen_text_capture_failed", activity=activity, step=step)
            return page, "", ""
        if not _raster_ready(shot):
            self.emit("screen_text_unavailable", activity=activity, step=step, reason="invalid_screenshot")
            return page, "", ""
        screenshot_hash = self._screenshot_hash(shot)
        words = self.word_extractor(shot)
        if not words:
            self.emit(
                "screen_text_unavailable", activity=activity, step=step,
                reason=self.ocr_error() or "empty_ocr",
            )
            return page, "", screenshot_hash
        merged = merge_ocr_into_elements(page.elements, words)
        enriched = page_from_elements(page.activity, page.xml, merged)
        blob = ocr_text_blob(words)
        self.emit(
            "screen_text_recovered", activity=activity, step=step,
            word_count=len(words), element_count=len(merged), forced=force,
        )
        return enriched, blob, screenshot_hash

    def _capture_screenshot(self, *, step: int, suffix: str) -> Path | None:
        name = f"ocr-{step:03d}.png" if suffix == "ocr" else f"ocr-{step:03d}-{suffix}.png"
        shot = self.artifact_path(name)
        return shot if self.client.screenshot(shot) else None

    @staticmethod
    def _screenshot_hash(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return ""

    def _cache_recheck_due(self, cached: dict, *, step: int) -> bool:
        interval = max(1, int(self.config.get("screen_ocr_cache_recheck_steps", 3)))
        return step - int(cached.get("verified_step") or step) >= interval

    @staticmethod
    def _cache_entry(value, *, step: int) -> dict | None:
        if isinstance(value, dict) and str(value.get("text") or ""):
            return dict(value)
        if isinstance(value, str) and value:
            # Compatibility with runs created before cache entries carried hashes.
            return {"text": value, "screenshot_hash": "", "verified_step": step}
        return None

    @staticmethod
    def _cache_value(text: str, screenshot_hash: str, step: int) -> dict:
        return {"text": text, "screenshot_hash": screenshot_hash, "verified_step": step}
