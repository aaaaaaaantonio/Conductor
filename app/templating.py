from datetime import datetime, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def localtime(value: datetime, fmt: str = "%d.%m %H:%M") -> str:
    """Stored timestamps are UTC (naive once read back from SQLite); show
    them in the server's local time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime(fmt)


templates.env.filters["localtime"] = localtime
