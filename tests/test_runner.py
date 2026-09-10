from pathlib import Path

import pytest
from sqlmodel import Session

from app.execution.broadcaster import EventBroadcaster
from app.execution.runner import start_local_job
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
