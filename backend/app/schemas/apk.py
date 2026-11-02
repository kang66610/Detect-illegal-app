from datetime import datetime

from pydantic import BaseModel


class APKOut(BaseModel):
    id: int
    filename: str
    sha256: str
    size_bytes: int
    parse_status: str
    parse_message: str | None = None
    app_name: str | None = None
    package_name: str | None = None
    version_name: str | None = None
    permissions: list | None = None
    sdk_list: list | None = None
    static_summary: dict | None = None
    has_policy: bool = False
    uploaded_at: datetime

    class Config:
        from_attributes = True
