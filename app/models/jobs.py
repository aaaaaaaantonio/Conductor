from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source: str
    status: str = Field(default="queued")
    params_json: str
    log_path: str | None = None
    jenkins_build_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )


def duration_seconds(job: Job, now: datetime | None = None) -> int | None:
    """How long a VM job has run: until now while it's active, else until
    its last status change. None for Jenkins runs, which aren't tracked."""
    if job.log_path is None and job.status not in ("queued", "running"):
        return None
    start = as_utc(job.created_at)
    end = (now or datetime.now(UTC)) if job.status in ("queued", "running") else as_utc(job.updated_at)
    return max(0, int((end - start).total_seconds()))


def as_utc(value: datetime) -> datetime:
    # SQLite hands timestamps back naive; they are stored as UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)
