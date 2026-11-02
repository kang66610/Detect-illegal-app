"""State and identity for document reading sessions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class DocumentScrollDirective(str, Enum):
    CONTINUE = "continue"
    RETRY_STUCK = "retry_stuck"
    RETRY_BOTTOM = "retry_bottom"
    COMPLETE = "complete"
    ABORT_STUCK = "abort_stuck"
    ABORT_UNVERIFIED = "abort_unverified"


@dataclass(frozen=True)
class DocumentIdentity:
    key: str
    kind: str = ""
    title: str = ""
    source: str = ""


@dataclass(frozen=True)
class DocumentIdentityInput:
    activity: str
    elements: list[dict]
    screen_text: str = ""
    document_origin: str = ""
    active_key: str = ""
    last_action: str = ""


@dataclass(frozen=True)
class DocumentIdentityRules:
    consent_dialog: Callable[[list[dict]], bool]
    privacy_dialog_button: Callable[[dict], bool]
    visible_text: Callable[[list[dict]], str]
    rendered_kind: Callable[[str], str | None]
    document_entry_page: Callable[[str, list[dict]], bool]
    login_gate: Callable[[str, list[dict]], bool]
    low_value_kind: Callable[[str, list[dict], str], str | None]
    customer_service_surface: Callable[[str, str, list[dict]], bool]
    has_body_surface: Callable[[str, list[dict]], bool]
    body_kind: Callable[[str], str | None]
    target_is_document_route: Callable[[str], bool]
    infer_kind: Callable[[str], str | None]
    canonical_kind: Callable[[str], str | None]
    title_for_kind: Callable[[str], str]
    login_activity_terms: tuple[str, ...]
    document_terms: tuple[str, ...]
    follow_terms: tuple[str, ...]


class DocumentIdentityResolver:
    """Pure document identity resolution, independent from reading progress."""

    def __init__(self, rules: DocumentIdentityRules) -> None:
        self.rules = rules

    def resolve(self, value: DocumentIdentityInput) -> DocumentIdentity | None:
        rules = self.rules
        activity = str(value.activity or "")
        elements = value.elements
        if any(rules.privacy_dialog_button(item) for item in elements) or rules.consent_dialog(elements):
            return None
        activity_lower = activity.lower()
        visible = f"{rules.visible_text(elements)} {value.screen_text}".strip()
        rendered = rules.rendered_kind(visible)
        if rendered:
            title = rules.title_for_kind(rendered)
            return DocumentIdentity(f"{activity}:document:{title}", rendered, title, "rendered_body")
        if rules.document_entry_page(activity, elements):
            return None
        if value.active_key and value.last_action == "scroll" and not any(
            term in activity_lower for term in rules.login_activity_terms
        ):
            return DocumentIdentity(value.active_key, source="active_scroll")
        origin_is_document = rules.target_is_document_route(value.document_origin)
        if rules.login_gate(activity, elements) and not origin_is_document:
            return None
        has_body = rules.has_body_surface(activity, elements)
        if rules.low_value_kind(activity, elements, value.screen_text) and not (
            value.active_key and value.last_action == "scroll"
        ):
            return None
        if rules.customer_service_surface(activity, visible, elements):
            return None
        if any(term in activity_lower for term in rules.login_activity_terms) and not has_body:
            return None
        if any(term in activity_lower for term in ("welcome", "splash", "guide", "intro", "onboard")) and not has_body:
            return None
        observed = rules.body_kind(visible) if has_body else None
        if observed:
            title = rules.title_for_kind(observed)
            return DocumentIdentity(f"{activity}:document:{title}", observed, title, "body_text")
        if origin_is_document:
            kind = rules.infer_kind(value.document_origin) or ""
            title = rules.title_for_kind(kind) if kind else "body"
            return DocumentIdentity(f"{activity}:document:{title}", kind, title, "origin")
        normalized = " ".join(
            " ".join((str(item.get("text", "")), str(item.get("content_desc", ""))))
            for item in elements if has_body or not item.get("clickable")
        ).lower()
        terms = (*rules.document_terms, *rules.follow_terms, "sdk目录", "第三方sdk", "收集的信息", "使用目的")
        matches = [(normalized.find(term.lower()), term.lower()) for term in terms if term.lower() in normalized]
        if matches:
            _, identity = min(matches, key=lambda item: item[0])
            kind = rules.canonical_kind(identity) or ""
            title = rules.title_for_kind(kind) if kind else identity
            return DocumentIdentity(f"{activity}:document:{title}", kind, title, "document_term")
        if has_body:
            return DocumentIdentity(f"{activity}:document:body", source="body_surface")
        return None


@dataclass(frozen=True)
class DocumentScrollDecision:
    directive: DocumentScrollDirective
    attempt: int = 0
    scrolls: int = 0


@dataclass
class DocumentReadingSession:
    key: str
    kind: str = ""
    title: str = ""
    source_activity: str = ""
    source_target: str = ""
    source_url: str = ""
    entry_clicks: int = 0
    scrolls: int = 0
    viewport_fingerprints: set[str] = field(default_factory=set)
    body_seen: bool = False
    observed_kind: str = ""
    blank_observations: int = 0
    bottom_confirmations: int = 0
    stuck_retries: int = 0
    complete: bool = False
    bottom_confirmed: bool = False
    interrupted: bool = False


class DocumentReadingLedger:
    """Own document progress and prevent stale identity inheritance."""

    def __init__(self) -> None:
        self.sessions: dict[str, DocumentReadingSession] = {}
        self.active_key: str | None = None

    @property
    def active(self) -> DocumentReadingSession | None:
        return self.sessions.get(self.active_key or "")

    def start(
        self,
        key: str,
        *,
        kind: str = "",
        title: str = "",
        source_activity: str = "",
        source_target: str = "",
        source_url: str = "",
        entry_clicks: int = 0,
    ) -> DocumentReadingSession:
        key = str(key or "").strip()
        if not key:
            raise ValueError("document session requires a semantic key")
        session = self.sessions.setdefault(key, DocumentReadingSession(key=key))
        for name, value in {
            "kind": kind, "title": title, "source_activity": source_activity,
            "source_target": source_target, "source_url": source_url,
        }.items():
            if value:
                setattr(session, name, str(value))
        session.entry_clicks = max(session.entry_clicks, int(entry_clicks))
        self.active_key = key
        return session

    def mark_scrolled(self, key: str, viewport_fingerprint: str = "") -> int:
        session = self.start(key)
        session.bottom_confirmations = 0
        session.stuck_retries = 0
        if viewport_fingerprint:
            if viewport_fingerprint in session.viewport_fingerprints:
                return session.scrolls
            session.viewport_fingerprints.add(viewport_fingerprint)
        session.scrolls += 1
        return session.scrolls

    def observe_body(
        self, key: str, *, visible: bool, kind: str = "", viewport_fingerprint: str = "",
    ) -> DocumentReadingSession:
        session = self.start(key, kind=kind)
        session.body_seen = session.body_seen or bool(visible)
        if kind:
            session.observed_kind = str(kind)
        if viewport_fingerprint:
            session.viewport_fingerprints.add(viewport_fingerprint)
        return session

    def observe_blank(self, key: str) -> int:
        session = self.start(key)
        session.blank_observations += 1
        return session.blank_observations

    def record_stuck(self, key: str) -> int:
        session = self.start(key)
        session.bottom_confirmations = 0
        session.stuck_retries += 1
        return session.stuck_retries

    def record_bottom_candidate(self, key: str) -> int:
        session = self.start(key)
        session.stuck_retries = 0
        session.bottom_confirmations += 1
        return session.bottom_confirmations

    def apply_scroll_status(
        self,
        key: str,
        status: str,
        *,
        viewport_fingerprint: str = "",
        stuck_retry_limit: int = 3,
        bottom_confirmations: int = 2,
    ) -> DocumentScrollDecision:
        """Translate driver output into one document-state transition."""
        if status == "moved":
            scrolls = self.mark_scrolled(key, viewport_fingerprint)
            return DocumentScrollDecision(DocumentScrollDirective.CONTINUE, scrolls, scrolls)
        if status == "stuck":
            attempt = self.record_stuck(key)
            directive = (
                DocumentScrollDirective.RETRY_STUCK
                if attempt < max(1, int(stuck_retry_limit))
                else DocumentScrollDirective.ABORT_STUCK
            )
            return DocumentScrollDecision(directive, attempt, self.start(key).scrolls)
        if status in {"bottom", "legacy_bottom"}:
            attempt = self.record_bottom_candidate(key)
            required = 1 if status == "legacy_bottom" else max(2, int(bottom_confirmations))
            directive = (
                DocumentScrollDirective.RETRY_BOTTOM
                if attempt < required else DocumentScrollDirective.COMPLETE
            )
            return DocumentScrollDecision(directive, attempt, self.start(key).scrolls)
        return DocumentScrollDecision(
            DocumentScrollDirective.ABORT_UNVERIFIED, scrolls=self.start(key).scrolls,
        )

    def finish(self, key: str, *, bottom_confirmed: bool) -> None:
        session = self.start(key)
        session.bottom_confirmed = bool(bottom_confirmed)
        session.complete = bool(bottom_confirmed)
        session.interrupted = not session.complete
        if session.complete and self.active_key == key:
            self.active_key = None

    def interrupt(self) -> None:
        if self.active:
            self.active.interrupted = True
        self.active_key = None

    def completed_keys(self) -> set[str]:
        return {key for key, session in self.sessions.items() if session.complete}

    def as_dict(self) -> dict:
        return {
            "active_key": self.active_key,
            "sessions": {
                key: {
                    "key": value.key,
                    "kind": value.kind,
                    "title": value.title,
                    "source_activity": value.source_activity,
                    "source_target": value.source_target,
                    "source_url": value.source_url,
                    "entry_clicks": value.entry_clicks,
                    "scrolls": value.scrolls,
                    "viewport_fingerprints": sorted(value.viewport_fingerprints),
                    "body_seen": value.body_seen,
                    "observed_kind": value.observed_kind,
                    "blank_observations": value.blank_observations,
                    "bottom_confirmations": value.bottom_confirmations,
                    "stuck_retries": value.stuck_retries,
                    "complete": value.complete,
                    "bottom_confirmed": value.bottom_confirmed,
                    "interrupted": value.interrupted,
                }
                for key, value in self.sessions.items()
            },
        }

    def restore(self, value: dict) -> None:
        self.sessions = {}
        for raw_key, raw in dict(value.get("sessions") or {}).items():
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("key") or raw_key or "").strip()
            if not key:
                continue
            self.sessions[key] = DocumentReadingSession(
                key=key,
                kind=str(raw.get("kind") or ""),
                title=str(raw.get("title") or ""),
                source_activity=str(raw.get("source_activity") or ""),
                source_target=str(raw.get("source_target") or ""),
                source_url=str(raw.get("source_url") or ""),
                entry_clicks=int(raw.get("entry_clicks") or 0),
                scrolls=int(raw.get("scrolls") or 0),
                viewport_fingerprints={
                    str(item) for item in raw.get("viewport_fingerprints") or [] if item
                },
                body_seen=bool(raw.get("body_seen")),
                observed_kind=str(raw.get("observed_kind") or raw.get("kind") or ""),
                blank_observations=int(raw.get("blank_observations") or 0),
                bottom_confirmations=int(raw.get("bottom_confirmations") or 0),
                stuck_retries=int(raw.get("stuck_retries") or 0),
                complete=bool(raw.get("complete")),
                bottom_confirmed=bool(raw.get("bottom_confirmed")),
                interrupted=bool(raw.get("interrupted")),
            )
        active = str(value.get("active_key") or "")
        self.active_key = active if active in self.sessions else None
