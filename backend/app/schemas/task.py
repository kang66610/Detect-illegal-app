from datetime import datetime

from pydantic import BaseModel


class TaskCreate(BaseModel):
    apk_id: int
    industry: str = "通用"
    mode: str = "deep"


class TaskOut(BaseModel):
    id: int
    apk_id: int
    app_name: str | None = None
    package_name: str | None = None
    industry: str
    mode: str
    status: str
    queue_position: int | None = None
    progress: dict | None = None
    current_page: str | None = None
    pages_covered: int
    scenarios_triggered: int
    failure_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    class Config:
        from_attributes = True
