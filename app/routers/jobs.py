import asyncio
import html
import json
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlmodel import Session, select

from app import config
from app.credentials import Credentials, get_credentials
from app.db import get_session
from app.execution.broadcaster import broadcaster
from app.execution.jenkins_launch import LaunchResult, launch_in_jenkins
from app.execution.log_lines import for_display
from app.execution.runner import cancel_job
from app.models.jobs import Job
from app.templating import templates

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Seconds of silence after which the event stream sends a keep-alive comment,
# so proxies don't drop it and dead clients are noticed on write.
HEARTBEAT_INTERVAL = 15


@router.get("/fragments/list", response_class=HTMLResponse)
def job_list_fragment(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    statement = select(Job).where(Job.status.in_(["queued", "running"]))
    jobs = list(session.exec(statement).all())
    return templates.TemplateResponse(request, "fragments/job_list.html", {"jobs": jobs})


async def jenkins_launch_response(
    request: Request, session: Session, job: Job, job_name: str, params: dict
) -> HTMLResponse:
    return await jenkins_reply_response(
        request,
        session,
        job,
        lambda creds: launch_in_jenkins(job.source, job_name, params, creds),
        error_prefix="Не удалось отправить запуск в Jenkins",
    )


async def jenkins_restart_response(
    request: Request,
    session: Session,
    job: Job,
    restart: Callable[[int, Credentials], Awaitable[LaunchResult]],
    build_number: int,
) -> HTMLResponse:
    return await jenkins_reply_response(
        request,
        session,
        job,
        lambda creds: restart(build_number, creds),
        error_prefix=f"Не удалось перезапустить сборку #{build_number}",
        restart_build=build_number,
    )


async def jenkins_reply_response(
    request: Request,
    session: Session,
    job: Job,
    send: Callable[[Credentials], Awaitable[LaunchResult]],
    error_prefix: str,
    restart_build: int | None = None,
) -> HTMLResponse:
    """Run a Jenkins launch/restart hook with the user's tokens, record the
    outcome on `job` and render its reply card for the log-panel feed."""
    creds = get_credentials(request)
    auth_link = False
    if creds is None:
        job.status = "failed"
        result = LaunchResult(message="Токены Jenkins не заданы — введите их на странице «Доступы»")
        auth_link = True
    else:
        try:
            result = await send(creds)
            job.status = "triggered"
            job.jenkins_build_id = result.url
        except httpx.HTTPStatusError as exc:
            job.status = "failed"
            code = exc.response.status_code
            if code in (401, 403):
                result = LaunchResult(
                    message=f"{error_prefix}: Jenkins отклонил токен ({code}) — обновите его на странице «Доступы»"
                )
                auth_link = True
            else:
                result = LaunchResult(message=f"{error_prefix}: {exc}")
        except Exception as exc:
            job.status = "failed"
            result = LaunchResult(message=f"{error_prefix}: {exc}")
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
            "restart_build": restart_build,
            "auth_link": auth_link,
        },
        headers={"HX-Retarget": "#job-log-body", "HX-Reswap": "afterbegin"},
    )


@router.post("/{job_id}/cancel", response_class=HTMLResponse)
async def cancel_job_endpoint(
    request: Request, job_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    """The "Остановить" button: kill a VM job's process (or keep a queued one
    from starting) and mark it cancelled. Jenkins runs aren't tracked, so
    they can't be stopped from here."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Джоба не найдена")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Джоба уже не выполняется")

    killed = cancel_job(job_id)
    if killed:
        # The runner notices the exit, logs it and sets "cancelled" itself;
        # give it a moment so the panel re-renders in the final state.
        for _ in range(50):
            await asyncio.sleep(0.05)
            session.refresh(job)
            if job.status != "running":
                break
    else:
        # Queued, or "running" with no live process (e.g. left over from a
        # restart): nothing to kill, just record the stop.
        job.status = "cancelled"
        session.add(job)
        session.commit()
        await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": "cancelled"})
    return job_log_fragment(request, job_id, session)


@router.get("/{job_id}/fragments/log", response_class=HTMLResponse)
def job_log_fragment(
    request: Request, job_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    job = session.get(Job, job_id)
    # Only the last lines are kept, each cut for display, so a huge log
    # never sits in memory whole; /jobs/{id}/log.txt has all of it.
    lines: deque[str] = deque(maxlen=config.LOG_TAIL_LINES)
    total = 0
    if job is not None and job.log_path is not None and Path(job.log_path).exists():
        with Path(job.log_path).open() as log_file:
            for line in log_file:
                lines.append(for_display(line.rstrip("\n"), config.LOG_LINE_MAX_CHARS))
                total += 1
    return templates.TemplateResponse(
        request,
        "fragments/job_log.html",
        {
            "lines": lines,
            "job": job,
            "total_lines": total,
            "first_line": total - len(lines) + 1,
            "tail": config.LOG_TAIL_LINES,
        },
    )


def _file_prefix(path: str, length: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while length > 0 and (chunk := f.read(min(64 * 1024, length))):
            length -= len(chunk)
            yield chunk


@router.get("/{job_id}/log.txt")
def job_log_download(job_id: int, session: Session = Depends(get_session)) -> StreamingResponse:
    job = session.get(Job, job_id)
    if job is None or job.log_path is None or not Path(job.log_path).exists():
        raise HTTPException(status_code=404, detail="Лога нет")
    # A running job keeps appending: send exactly what exists now, or the
    # body would outgrow its Content-Length and the download would break.
    size = Path(job.log_path).stat().st_size
    return StreamingResponse(
        _file_prefix(job.log_path, size),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Length": str(size),
            "Content-Disposition": f'attachment; filename="job-{job_id}.log"',
        },
    )


@router.get("/stream")
async def stream_events() -> StreamingResponse:
    queue = broadcaster.subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), HEARTBEAT_INTERVAL)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if event is None:
                    # Fell too far behind; the browser reconnects.
                    return
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
