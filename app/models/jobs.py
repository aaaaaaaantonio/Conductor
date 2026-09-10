from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str
    status: str = Field(default="queued")
    params_json: str
    log_path: Optional[str] = None
    jenkins_build_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
