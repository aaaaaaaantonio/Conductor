from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.config import JOB_RETENTION_DAYS
from app.db import get_session
from app.models.jobs import Job
from app.templating import templates

router = APIRouter(tags=["history"])

SOURCES = {"python": "Python", "java": "Java", "agent_test": "Тестирование агентов"}
STATUSES = {
    "queued": "В очереди",
    "running": "Выполняется",
    "success": "Успешно",
    "failed": "Ошибка",
    "cancelled": "Остановлено",
    "triggered": "В Jenkins",
}
# Retention keeps the table small; this only guards the page itself.
MAX_ROWS = 500


def _parse_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name}: ожидается дата ГГГГ-ММ-ДД") from None


def _local_midnight_utc(day: date) -> datetime:
    """Start of `day` in the server's local time, as naive UTC like the DB."""
    local = datetime.combine(day, time.min).astimezone()
    return local.astimezone(UTC).replace(tzinfo=None)


def _filtered_jobs(
    session: Session,
    source: str | None,
    status: str | None,
    date_from: str | None,
    date_to: str | None,
) -> list[Job]:
    statement = select(Job)
    if source in SOURCES:
        statement = statement.where(Job.source == source)
    if status in STATUSES:
        statement = statement.where(Job.status == status)
    start = _parse_date(date_from, "date_from")
    end = _parse_date(date_to, "date_to")
    if start:
        statement = statement.where(Job.created_at >= _local_midnight_utc(start))
    if end:
        statement = statement.where(Job.created_at < _local_midnight_utc(end + timedelta(days=1)))
    statement = statement.order_by(Job.created_at.desc(), Job.id.desc()).limit(MAX_ROWS)
    return list(session.exec(statement).all())


def _context(jobs: list[Job], **filters) -> dict:
    return {
        "jobs": jobs,
        "sources": SOURCES,
        "statuses": STATUSES,
        "filters": filters,
        "retention_days": JOB_RETENTION_DAYS,
        "max_rows": MAX_ROWS,
    }


@router.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    source: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    jobs = _filtered_jobs(session, source, status, date_from, date_to)
    return templates.TemplateResponse(
        request,
        "history.html",
        _context(jobs, source=source, status=status, date_from=date_from, date_to=date_to),
    )


@router.get("/history/fragments/list", response_class=HTMLResponse)
def history_list_fragment(
    request: Request,
    source: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    jobs = _filtered_jobs(session, source, status, date_from, date_to)
    return templates.TemplateResponse(request, "fragments/history_list.html", _context(jobs))
