import asyncio
import html
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.templating import templates
from app.execution.broadcaster import broadcaster
from app.execution.jenkins_launch import LaunchResult, launch_in_jenkins
from app.models.jobs import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/fragments/list", response_class=HTMLResponse)
def job_list_fragment(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    statement = select(Job).where(Job.status.in_(["queued", "running"]))
    jobs = list(session.exec(statement).all())
    return templates.TemplateResponse(request, "fragments/job_list.html", {"jobs": jobs})


async def jenkins_launch_response(
    request: Request, session: Session, job: Job, job_name: str, params: dict
) -> HTMLResponse:
    try:
        result = await launch_in_jenkins(job.source, job_name, params)
        job.status = "triggered"
        job.jenkins_build_id = result.url
    except Exception as exc:
        job.status = "failed"
        result = LaunchResult(message=f"Не удалось отправить запуск в Jenkins: {exc}")
    session.add(job)
    session.commit()

    # The Python tab's launch form targets #job-list (VM runs refresh it); a
    # Jenkins launch only adds its reply to the log panel, newest on top, so
    # earlier replies on the page stay visible as a feed.
    return templates.TemplateResponse(
        request,
        "fragments/jenkins_launched.html",
        {
            "job": job,
            "time": datetime.now().strftime("%H:%M:%S"),
            "message": result.message,
            "url": result.url,
            "failed": job.status == "failed",
        },
        headers={"HX-Retarget": "#job-log-body", "HX-Reswap": "afterbegin"},
    )


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
                    # app.js appends this to the open log panel if data-job
                    # matches the job shown there — render a single escaped
                    # line instead of raw event JSON. SSE `data:` fields
                    # can't contain literal newlines, so collapse any
                    # embedded ones first.
                    job_id = event["job_id"]
                    line = event["line"].replace("\r", "").replace("\n", " ")
                    data = f'<div data-job="{job_id}">{html.escape(line)}</div>'
                else:
                    data = json.dumps(event)
                yield f"event: {event['type']}\ndata: {data}\n\n"
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
