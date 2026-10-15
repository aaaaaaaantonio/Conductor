from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.execution.log_lines import highlight
from app.models.jobs import as_utc, duration_seconds

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def localtime(value: datetime, fmt: str = "%d.%m %H:%M") -> str:
    """Stored timestamps are UTC (naive once read back from SQLite); show
    them in the server's local time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone().strftime(fmt)


def format_duration(seconds: int | None) -> str:
    """0:37, 4:12, 1:02:03 — the same format app.js ticks running jobs in."""
    if seconds is None:
        return ""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


templates.env.filters["localtime"] = localtime
templates.env.filters["duration"] = format_duration
templates.env.filters["highlight"] = highlight
# ISO UTC start time; app.js ticks an active job's duration from it.
templates.env.filters["utc_iso"] = lambda value: as_utc(value).isoformat()
templates.env.globals["job_duration"] = duration_seconds
