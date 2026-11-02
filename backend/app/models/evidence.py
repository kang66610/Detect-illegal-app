from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class Evidence(Base):
    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    violation_id: Mapped[int] = mapped_column(ForeignKey("violations.id"))
    type: Mapped[str] = mapped_column(String(20))  # screenshot/callstack/traffic/timeline
    file_path: Mapped[str] = mapped_column(String(500))
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    violation = relationship("Violation", back_populates="evidences")
