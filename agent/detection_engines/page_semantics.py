"""Authoritative, evidence-backed page-role adjudication."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent.ai_explorer.target_catalog import TargetCandidate, build_target_catalog


class PageScope(str, Enum):
    AUDITED_APP = "audited_app"
    ANDROID_SYSTEM = "android_system"
    EXTERNAL_APP = "external_app"


class PageRole(str, Enum):
    SYSTEM_LAUNCHER = "system_launcher"
    SYSTEM_OVERLAY = "system_overlay"
    SYSTEM_PERMISSION = "system_permission"
    SYSTEM_SETTINGS = "system_settings"
    SYSTEM_FILE_PICKER = "system_file_picker"
    SYSTEM_CAMERA = "system_camera"
    EXTERNAL_BROWSER = "external_browser"
    FOREIGN_APP = "foreign_app"
    CRASH = "crash"
    CONSENT_DIALOG = "consent_dialog"
    DOCUMENT_BODY = "document_body"
    LOGIN_GATE = "login_gate"
    LOGGED_OUT_PROFILE = "logged_out_profile"
    SPLASH_OR_GATE = "splash_or_gate"
    LOADING_SHELL = "loading_shell"
    DOCUMENT_HUB = "document_hub"
    MAIN_CONTENT = "main_content"
    LOW_VALUE = "low_value"
    APP_PAGE = "app_page"


class EvidenceSource(str, Enum):
    UI_TREE = "ui_tree"
    OCR = "ocr"
    ROUTE = "route"
    PREVIOUS_ACTION = "previous_action"
    RUNTIME_CHECKPOINT = "runtime_checkpoint"
    LLM_HINT = "llm_hint"


@dataclass(frozen=True)
class PageFacts:
    launcher: bool = False
    system_overlay: bool = False
    permission_prompt: bool = False
    system_settings: bool = False
    file_picker: bool = False
    system_camera: bool = False
    external_browser: bool = False
    foreign_app: bool = False
    crash: bool = False
    consent_dialog: bool = False
    document_body: bool = False
    login_gate: bool = False
    logged_out_profile: bool = False
    splash_or_gate: bool = False
    loading_shell: bool = False
    document_hub: bool = False
    # A document-entry page is not automatically an account/settings hub. The
    # distinction is consumed by traversal policy after role adjudication so a
    # lone privacy-policy link cannot trigger account-hub scrolling.
    privacy_hub: bool = False
    main_content: bool = False
    low_value_kind: str | None = None


@dataclass(frozen=True)
class RoleEvidence:
    """One reproducible reason a page could have a semantic role."""

    role: PageRole
    source: EvidenceSource
    strength: int
    hits: tuple[str, ...] = ()
    target_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PageEvidence:
    """All candidate-role evidence extracted from one stable observation."""

    facts: PageFacts
    candidates: tuple[RoleEvidence, ...] = ()

    @classmethod
    def from_facts(
        cls, facts: PageFacts, *, source: EvidenceSource = EvidenceSource.UI_TREE,
        additional: tuple[RoleEvidence, ...] = (),
    ) -> "PageEvidence":
        mapping = (
            ("launcher", PageRole.SYSTEM_LAUNCHER),
            ("system_overlay", PageRole.SYSTEM_OVERLAY),
            ("permission_prompt", PageRole.SYSTEM_PERMISSION),
            ("system_settings", PageRole.SYSTEM_SETTINGS),
            ("file_picker", PageRole.SYSTEM_FILE_PICKER),
            ("system_camera", PageRole.SYSTEM_CAMERA),
            ("external_browser", PageRole.EXTERNAL_BROWSER),
            ("foreign_app", PageRole.FOREIGN_APP),
            ("crash", PageRole.CRASH),
            ("consent_dialog", PageRole.CONSENT_DIALOG),
            ("document_body", PageRole.DOCUMENT_BODY),
            ("login_gate", PageRole.LOGIN_GATE),
            ("logged_out_profile", PageRole.LOGGED_OUT_PROFILE),
            ("splash_or_gate", PageRole.SPLASH_OR_GATE),
            ("loading_shell", PageRole.LOADING_SHELL),
            ("document_hub", PageRole.DOCUMENT_HUB),
            ("main_content", PageRole.MAIN_CONTENT),
        )
        candidates = [
            RoleEvidence(role=role, source=source, strength=100, hits=(name,))
            for name, role in mapping if bool(getattr(facts, name))
        ]
        if facts.low_value_kind:
            candidates.append(RoleEvidence(
                role=PageRole.LOW_VALUE, source=source, strength=60,
                hits=(str(facts.low_value_kind),),
            ))
        candidates.extend(additional)
        return cls(facts=facts, candidates=tuple(candidates))


@dataclass(frozen=True)
class ResolvedPage:
    """The only page-role result action producers are allowed to consume."""

    scope: PageScope
    role: PageRole
    recoverable: bool
    allow_deep_search: bool
    preferred_exit: str | None = None
    low_value_kind: str | None = None
    privacy_hub: bool = False
    targets: tuple[TargetCandidate, ...] = ()
    evidence: tuple[RoleEvidence, ...] = ()
    blocked_roles: tuple[PageRole, ...] = ()

    @property
    def legacy_role(self) -> str:
        if self.role is PageRole.LOW_VALUE and self.low_value_kind:
            return f"low_value_{self.low_value_kind}"
        return self.role.value

    @property
    def requires_login_wait(self) -> bool:
        return self.role is PageRole.LOGIN_GATE

    @property
    def has_overlay(self) -> bool:
        return self.role is PageRole.CONSENT_DIALOG

    @property
    def targets_by_label(self) -> dict[str, TargetCandidate]:
        return {item.label: item for item in self.targets if item.label}


# Compatibility name used by existing engines and public test contracts.
PageSemantics = ResolvedPage


@dataclass(frozen=True)
class PageObservation:
    activity: str
    elements: tuple[dict, ...]
    facts: PageFacts
    evidence: PageEvidence | None = None


_PRECEDENCE = (
    PageRole.SYSTEM_LAUNCHER,
    PageRole.SYSTEM_OVERLAY,
    PageRole.SYSTEM_PERMISSION,
    PageRole.SYSTEM_SETTINGS,
    PageRole.SYSTEM_FILE_PICKER,
    PageRole.SYSTEM_CAMERA,
    PageRole.EXTERNAL_BROWSER,
    PageRole.FOREIGN_APP,
    PageRole.CRASH,
    PageRole.CONSENT_DIALOG,
    PageRole.DOCUMENT_BODY,
    PageRole.LOGIN_GATE,
    PageRole.LOGGED_OUT_PROFILE,
    PageRole.SPLASH_OR_GATE,
    PageRole.LOADING_SHELL,
    PageRole.DOCUMENT_HUB,
    PageRole.MAIN_CONTENT,
    PageRole.LOW_VALUE,
    PageRole.APP_PAGE,
)
_OVERLAY_BLOCKED_ROLES = frozenset({
    PageRole.DOCUMENT_BODY,
    PageRole.LOGIN_GATE,
    PageRole.LOGGED_OUT_PROFILE,
    PageRole.SPLASH_OR_GATE,
    PageRole.LOADING_SHELL,
    PageRole.DOCUMENT_HUB,
    PageRole.MAIN_CONTENT,
    PageRole.LOW_VALUE,
    PageRole.APP_PAGE,
})


class PageRoleAdjudicator:
    """Select one role and one interaction layer with fixed structural precedence."""

    def resolve(
        self, evidence: PageEvidence, *, elements: tuple[dict, ...] | list[dict],
    ) -> ResolvedPage:
        strongest: dict[PageRole, RoleEvidence] = {}
        for item in evidence.candidates:
            current = strongest.get(item.role)
            if current is None or item.strength > current.strength:
                strongest[item.role] = item
        role = next((candidate for candidate in _PRECEDENCE if candidate in strongest), PageRole.APP_PAGE)
        blocked_roles: tuple[PageRole, ...] = ()
        if role is PageRole.CONSENT_DIALOG:
            blocked_roles = tuple(
                candidate for candidate in _PRECEDENCE
                if candidate in strongest and candidate in _OVERLAY_BLOCKED_ROLES
            )
        return _resolved_for_role(
            role, evidence.facts,
            evidence=tuple(sorted(strongest.values(), key=lambda item: (-item.strength, item.role.value))),
            blocked_roles=blocked_roles,
            elements=tuple(elements),
        )


def _resolved_for_role(
    role: PageRole, facts: PageFacts, *, evidence: tuple[RoleEvidence, ...] = (),
    blocked_roles: tuple[PageRole, ...] = (), elements: tuple[dict, ...] = (),
) -> ResolvedPage:
    if role is PageRole.SYSTEM_LAUNCHER:
        values = (PageScope.ANDROID_SYSTEM, True, False, "reactivate")
    elif role is PageRole.SYSTEM_OVERLAY:
        values = (PageScope.ANDROID_SYSTEM, True, False, "back")
    elif role is PageRole.SYSTEM_PERMISSION:
        values = (PageScope.ANDROID_SYSTEM, False, False, None)
    elif role in {PageRole.SYSTEM_SETTINGS, PageRole.SYSTEM_FILE_PICKER, PageRole.SYSTEM_CAMERA}:
        values = (PageScope.ANDROID_SYSTEM, True, False, "back")
    elif role in {PageRole.EXTERNAL_BROWSER, PageRole.FOREIGN_APP}:
        values = (PageScope.EXTERNAL_APP, True, False, "back")
    elif role is PageRole.CRASH:
        values = (PageScope.AUDITED_APP, True, False, "back")
    elif role is PageRole.CONSENT_DIALOG:
        values = (PageScope.AUDITED_APP, False, False, None)
    elif role is PageRole.DOCUMENT_BODY:
        values = (PageScope.AUDITED_APP, True, False, None)
    elif role is PageRole.LOGIN_GATE:
        values = (PageScope.AUDITED_APP, True, False, "back")
    elif role in {PageRole.LOGGED_OUT_PROFILE, PageRole.DOCUMENT_HUB, PageRole.MAIN_CONTENT, PageRole.APP_PAGE}:
        values = (PageScope.AUDITED_APP, True, True, None)
    elif role in {PageRole.SPLASH_OR_GATE, PageRole.LOADING_SHELL}:
        values = (PageScope.AUDITED_APP, True, False, None)
    else:  # LOW_VALUE
        values = (PageScope.AUDITED_APP, True, False, "back")
    scope, recoverable, allow_deep_search, preferred_exit = values
    return ResolvedPage(
        scope=scope,
        role=role,
        recoverable=recoverable,
        allow_deep_search=allow_deep_search,
        preferred_exit=preferred_exit,
        low_value_kind=facts.low_value_kind if role is PageRole.LOW_VALUE else None,
        privacy_hub=bool(facts.privacy_hub),
        targets=build_target_catalog(elements, role=role.value),
        evidence=evidence,
        blocked_roles=blocked_roles,
    )


def classify_observation(observation: PageObservation) -> ResolvedPage:
    """Resolve one observation into exactly one role and one target catalog."""
    evidence = observation.evidence or PageEvidence.from_facts(observation.facts)
    return PageRoleAdjudicator().resolve(evidence, elements=observation.elements)


def classify_page(facts: PageFacts) -> ResolvedPage:
    """Compatibility entry point for callers that have facts but no UI tree."""
    return PageRoleAdjudicator().resolve(PageEvidence.from_facts(facts), elements=())


def is_system_camera_activity(activity: str) -> bool:
    value = str(activity or "").lower()
    return any(term in value for term in (
        "com.android.camera", "camera.captureactivity", "cameraactivity",
        "mediastore.action_image_capture", "stillimagecamera",
    ))


def is_foreign_package(
    audited_package: str,
    foreground_package: str,
    *,
    allowed_system_surface: bool = False,
) -> bool:
    """Classify package drift without mixing it into page-role precedence."""
    audited = str(audited_package or "").strip().lower()
    foreground = str(foreground_package or "").strip().lower()
    if not audited or not foreground or allowed_system_surface:
        return False
    return foreground != audited and audited not in foreground
