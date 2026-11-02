from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class APKFile(Base):
    __tablename__ = "apk_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    md5: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 报告模板「MD5值」字段
    size_bytes: Mapped[int] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String(20), default="parsing")  # parsing/success/failed/invalid
    parse_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    package_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sdk_list: Mapped[list | None] = mapped_column(JSON, nullable=True)
    static_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policy_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
