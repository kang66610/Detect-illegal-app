from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("detection_tasks.id"))
    category: Mapped[int] = mapped_column(Integer)  # 1..6，对应《认定方法》第一至第六条
    category_name: Mapped[str] = mapped_column(String(100), default="")  # 显式标注第N类名称
    rule_id: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    legal_basis: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(8))  # 高/中/低
    page: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remediation_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    evidences = relationship("Evidence", back_populates="violation", cascade="all, delete-orphan")
