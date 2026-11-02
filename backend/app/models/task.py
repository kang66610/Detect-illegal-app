from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class DetectionTask(Base):
    __tablename__ = "detection_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    apk_id: Mapped[int] = mapped_column(ForeignKey("apk_files.id"))
    industry: Mapped[str] = mapped_column(String(32), default="通用")
    mode: Mapped[str] = mapped_column(String(16), default="deep")  # fast/deep
    # queued/preparing/installing/static_analysis/traversing/analyzing/reporting/completed/failed/canceled
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    current_page: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pages_covered: Mapped[int] = mapped_column(Integer, default=0)
    scenarios_triggered: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    apk = relationship("APKFile")
