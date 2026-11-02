from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReviewUpdate(BaseModel):
    status: Literal["pending", "no_evidence_found", "violation", "not_applicable", "needs_server_evidence"]
    notes: str = Field(default="", max_length=4000)
    evidence_ref: str = Field(default="", max_length=255)


class ServerAuditEventIn(BaseModel):
    event_type: str = Field(min_length=1, max_length=64)
    occurred_at: datetime
    outcome: str = Field(default="observed", max_length=48)
    reference: str = Field(default="", max_length=255)
    details: dict = Field(default_factory=dict)


class ServerAuditImport(BaseModel):
    events: list[ServerAuditEventIn] = Field(min_length=1, max_length=1000)
