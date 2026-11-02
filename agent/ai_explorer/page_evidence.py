"""Pure construction of page-role evidence from already observed signals.

The explorer still owns legacy detector functions during the first migration
step. This module centralizes their output shape without taking ownership of
document progress, navigation state, or role arbitration.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.detection_engines.page_semantics import (
    PageEvidence,
    PageFacts,
    PageObservation,
    RoleEvidence,
)


@dataclass(frozen=True)
class PageEvidenceSignals:
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
    privacy_hub: bool = False
    main_content: bool = False
    low_value_kind: str | None = None

    def as_page_facts(self) -> PageFacts:
        return PageFacts(**self.__dict__)


@dataclass(frozen=True)
class PageEvidenceInput:
    activity: str
    elements: tuple[dict, ...]
    screen_text: str
    previous_action: str
    route: tuple[str, ...]
    signals: PageEvidenceSignals
    supporting_evidence: tuple[RoleEvidence, ...] = ()


class PageEvidenceBuilder:
    """Build the immutable observation consumed by the role adjudicator.

    It deliberately accepts already-computed signals. Moving individual
    legacy detectors here is a later behavior-preserving migration; keeping
    the output construction in one place first prevents a second PageFacts
    representation from emerging.
    """

    def build_observation(self, value: PageEvidenceInput) -> PageObservation:
        facts = value.signals.as_page_facts()
        evidence = PageEvidence.from_facts(
            facts,
            additional=tuple(value.supporting_evidence),
        )
        return PageObservation(
            activity=str(value.activity or ""),
            elements=tuple(value.elements),
            facts=facts,
            evidence=evidence,
        )
