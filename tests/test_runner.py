from pathlib import Path

import httpx
import pytest
from sqlmodel import Session

from app.execution.broadcaster import EventBroadcaster
from app.execution.runner import start_jenkins_job, start_local_job
from app.models.jobs import Job


@pytest.mark.asyncio
async def test_start_local_job_streams_log_and_marks_success(tmp_path: Path, session: Session):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    test_broadcaster = EventBroadcaster()
    events_queue = test_broadcaster.subscribe()

    command = ["python3", "-c", "print('line one'); print('line two')"]
    await start_local_job(
        job_id=job.id,
        command=command,
        log_dir=tmp_path,
        session=session,
        broadcaster=test_broadcaster,
    )

    session.refresh(job)
    assert job.status == "success"
    assert job.log_path is not None
    assert Path(job.log_path).read_text().splitlines() == ["line one", "line two"]

    events = []
    while not events_queue.empty():
        events.append(events_queue.get_nowait())
    log_events = [e for e in events if e["type"] == "log-line"]
    status_events = [e for e in events if e["type"] == "job-status"]
    assert [e["line"] for e in log_events] == ["line one", "line two"]
    assert status_events[-1] == {"type": "job-status", "job_id": job.id, "status": "success"}


@pytest.mark.asyncio
async def test_start_local_job_marks_failed_on_nonzero_exit(tmp_path: Path, session: Session):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    test_broadcaster = EventBroadcaster()
    test_broadcaster.subscribe()

    command = ["python3", "-c", "import sys; sys.exit(1)"]
    await start_local_job(
        job_id=job.id,
        command=command,
        log_dir=tmp_path,
        session=session,
        broadcaster=test_broadcaster,
    )

    session.refresh(job)
    assert job.status == "failed"


@pytest.mark.asyncio
async def test_start_local_job_marks_failed_when_executable_missing(tmp_path: Path, session: Session):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    test_broadcaster = EventBroadcaster()
    events_queue = test_broadcaster.subscribe()

    command = ["/nonexistent/path/to/nothing", "arg"]
    # Must not raise: a bad executable path should be handled the same way
    # as any other execution failure, not propagate out of start_local_job.
    await start_local_job(
        job_id=job.id,
        command=command,
        log_dir=tmp_path,
        session=session,
        broadcaster=test_broadcaster,
    )

    session.refresh(job)
    assert job.status == "failed"
    assert job.log_path is not None
    log_contents = Path(job.log_path).read_text()
    assert log_contents.strip() != ""

    events = []
    while not events_queue.empty():
        events.append(events_queue.get_nowait())
    status_events = [e for e in events if e["type"] == "job-status"]
    assert status_events[-1] == {"type": "job-status", "job_id": job.id, "status": "failed"}


@pytest.mark.asyncio
async def test_start_jenkins_job_marks_triggered_without_polling(session: Session):
    job = Job(source="java", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/1/"})

    test_broadcaster = EventBroadcaster()
    events_queue = test_broadcaster.subscribe()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await start_jenkins_job(
            job_id=job.id,
            base_url="https://jenkins",
            job_name="java-tests",
            params={"team_id": 1},
            session=session,
            client=client,
            broadcaster=test_broadcaster,
        )

    session.refresh(job)
    assert job.status == "triggered"
    assert job.jenkins_build_id == "https://jenkins/queue/item/1/"
    # Only the trigger call — no follow-up status polling.
    assert len(requests) == 1

    events = []
    while not events_queue.empty():
        events.append(events_queue.get_nowait())
    status_events = [e for e in events if e["type"] == "job-status"]
    assert [e["status"] for e in status_events] == ["triggered"]


@pytest.mark.asyncio
async def test_start_jenkins_job_marks_failed_when_trigger_raises(session: Session):
    job = Job(source="java", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    test_broadcaster = EventBroadcaster()
    events_queue = test_broadcaster.subscribe()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        # Must not raise: a Jenkins-side failure to accept the build must be
        # handled the same way as any other execution failure, not
        # propagate out of start_jenkins_job.
        await start_jenkins_job(
            job_id=job.id,
            base_url="https://jenkins",
            job_name="java-tests",
            params={"team_id": 1},
            session=session,
            client=client,
            broadcaster=test_broadcaster,
        )

    session.refresh(job)
    assert job.status == "failed"
    assert job.jenkins_build_id is None

    events = []
    while not events_queue.empty():
        events.append(events_queue.get_nowait())
    status_events = [e for e in events if e["type"] == "job-status"]
    assert status_events[-1] == {"type": "job-status", "job_id": job.id, "status": "failed"}
