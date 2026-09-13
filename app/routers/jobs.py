import asyncio
import html
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.execution.broadcaster import broadcaster
from app.models.jobs import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/fragments/list", response_class=HTMLResponse)
def job_list_fragment(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    statement = select(Job).where(Job.status.in_(["queued", "running"]))
    jobs = list(session.exec(statement).all())
    return templates.TemplateResponse(request, "fragments/job_list.html", {"jobs": jobs})


@router.get("/{job_id}/fragments/log", response_class=HTMLResponse)
def job_log_fragment(
    request: Request, job_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    job = session.get(Job, job_id)
    lines: list[str] = []
    if job is not None and job.log_path is not None and Path(job.log_path).exists():
        lines = Path(job.log_path).read_text().splitlines()
    return templates.TemplateResponse(
        request, "fragments/job_log.html", {"lines": lines, "job": job}
    )


@router.get("/stream")
async def stream_events() -> StreamingResponse:
    queue = broadcaster.subscribe()

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event["type"] == "log-line":
                    # sse-swap="log-line" appends this data verbatim as HTML
                    # (hx-swap="beforeend") — render a single escaped,
                    # job-labeled line instead of raw event JSON. SSE `data:`
                    # fields can't contain literal newlines, so collapse any
                    # embedded ones first.
                    job_id = event["job_id"]
                    line = event["line"].replace("\r", "").replace("\n", " ")
                    data = f'<div data-job="{job_id}">[job {job_id}] {html.escape(line)}</div>'
                else:
                    data = json.dumps(event)
                yield f"event: {event['type']}\ndata: {data}\n\n"
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
