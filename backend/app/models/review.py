from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("task_id", "legal_key", name="uq_review_task_legal_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("detection_tasks.id"))
    legal_key: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    notes: Mapped[str] = mapped_column(Text, default="")
    evidence_ref: Mapped[str] = mapped_column(String(255), default="")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ServerAuditEvent(Base):
    __tablename__ = "server_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("detection_tasks.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    outcome: Mapped[str] = mapped_column(String(48), default="observed")
    reference: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
