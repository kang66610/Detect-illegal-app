"""Bounded page reread and cold-restart policy for loading shells."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


class LoadingShellDetector:
    """Pure loading-shell classifier used by bounded reread/restart policy.

    The detector receives structural predicates from the evidence layer so it
    never owns page-role, document, or external-navigation semantics.
    """

    def __init__(
        self,
        *,
        is_external: Callable[[str, list[dict]], bool],
        has_document_body: Callable[[str, list[dict]], bool],
        has_external_document_body: Callable[[list[dict]], bool],
    ) -> None:
        self.is_external = is_external
        self.has_document_body = has_document_body
        self.has_external_document_body = has_external_document_body

    @staticmethod
    def clickable_count(page: object) -> int:
        return sum(
            1 for item in (getattr(page, "elements", None) or [])
            if item.get("clickable")
        )

    def is_loading(self, page: object, *, active_document: bool) -> bool:
        elements = list(getattr(page, "elements", None) or [])
        activity = str(getattr(page, "activity", "") or "")
        if active_document:
            return False
        if self.is_external(activity, elements):
            return False
        if self.has_document_body(activity, elements):
            return False
        if self.has_external_document_body(elements):
            return False
        xml_lower = str(getattr(page, "xml", "") or "").lower()
        if "android.webkit.webview" in xml_lower:
            return False
        if any(item.get("clickable") for item in elements):
            return False
        return not any(
            str(item.get("text") or item.get("content_desc") or "").strip()
            for item in elements
        )


@dataclass(frozen=True)
class PageStabilityResult:
    activity: str
    page: object
    empty_attempts: int
    settle_attempts: int
    cold_restarts: int


class PageStabilityCoordinator:
    """Own empty-tree retries, loading-shell settling and one cold restart."""

    def __init__(
        self,
        *,
        read_page: Callable[[int], tuple[str, str]],
        parse_page: Callable[[str, str], object],
        is_loading: Callable[[object], bool],
        clickable_count: Callable[[object], int],
        client,
        package_name: str,
        config: dict,
        appium_config: dict,
        runtime: dict,
        save_checkpoint: Callable[[], str],
        replay_navigation: Callable[[], bool],
        emit: Callable[..., None],
        note_recovery: Callable[[], None],
        empty_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.read_page = read_page
        self.parse_page = parse_page
        self.is_loading = is_loading
        self.clickable_count = clickable_count
        self.client = client
        self.package_name = package_name
        self.config = config
        self.appium_config = appium_config
        self.runtime = runtime
        self.save_checkpoint = save_checkpoint
        self.replay_navigation = replay_navigation
        self.emit = emit
        self.note_recovery = note_recovery
        self.empty_retries = int(empty_retries)
        self.sleep = sleep

    def stabilize(self, step: int, *, cold_restarts: int) -> PageStabilityResult:
        activity, xml = self.read_page(step)
        page = self.parse_page(activity, xml)
        empty_attempts = 0
        page_wait = max(0.0, float(self.appium_config.get("page_wait_seconds", 1)))
        while not page.elements and empty_attempts < self.empty_retries:
            empty_attempts += 1
            self.emit("page_content_retry", activity=activity, step=step, attempt=empty_attempts)
            self.sleep(page_wait)
            activity, xml = self.read_page(step)
            page = self.parse_page(activity, xml)
        if empty_attempts and page.elements:
            self.emit(
                "page_content_recovered", activity=activity, step=step,
                retries=empty_attempts, element_count=len(page.elements),
            )

        settle_retries = max(0, int(self.config.get("page_settle_retries", 4)))
        settle_wait = max(0.0, float(self.config.get(
            "page_settle_wait_seconds", 0.0 if page_wait == 0 else 3.0,
        )))
        settle_attempts = 0
        while (
            self.is_loading(page)
            and settle_attempts < settle_retries
            and not self.runtime.get("external_document_interrupted_target")
        ):
            settle_attempts += 1
            self.emit(
                "page_settle_retry", activity=activity, step=step,
                attempt=settle_attempts, clickable_count=self.clickable_count(page),
            )
            self.sleep(settle_wait)
            activity, xml = self.read_page(step)
            page = self.parse_page(activity, xml)
        if settle_attempts and not self.is_loading(page):
            self.emit(
                "page_settled", activity=activity, step=step,
                retries=settle_attempts, element_count=len(page.elements),
                clickable_count=self.clickable_count(page),
            )

        restart_limit = max(0, int(self.config.get("loading_shell_cold_restart_limit", 1)))
        restart = getattr(self.client, "restart_app", None)
        if self.is_loading(page) and callable(restart) and cold_restarts < restart_limit:
            checkpoint = self.save_checkpoint()
            self.emit(
                "loading_shell_cold_restart_started", activity=activity, step=step,
                attempt=cold_restarts + 1, navigation_checkpoint=str(checkpoint),
                reason="页面连续稳定重读后仍停留在加载壳，关闭后台进程后重启应用",
            )
            try:
                restart(self.package_name)
                cold_restarts += 1
                self.note_recovery()
                activity, xml = self.read_page(step)
                page = self.parse_page(activity, xml)
                post_attempts = 0
                while self.is_loading(page) and post_attempts < settle_retries:
                    post_attempts += 1
                    self.sleep(settle_wait)
                    activity, xml = self.read_page(step)
                    page = self.parse_page(activity, xml)
                replayed = False
                if not self.is_loading(page):
                    replayed = self.replay_navigation()
                    if replayed:
                        activity, xml = self.read_page(step)
                        page = self.parse_page(activity, xml)
                    self.emit(
                        "loading_shell_cold_restart_completed", activity=activity, step=step,
                        retries=post_attempts, navigation_replayed=replayed,
                    )
                else:
                    self.emit(
                        "loading_shell_cold_restart_still_loading", activity=activity,
                        step=step, retries=post_attempts,
                    )
            except Exception as exc:
                cold_restarts += 1
                self.emit(
                    "loading_shell_cold_restart_failed", activity=activity,
                    step=step, error=str(exc)[:300],
                )
        return PageStabilityResult(
            activity, page, empty_attempts, settle_attempts, cold_restarts,
        )
