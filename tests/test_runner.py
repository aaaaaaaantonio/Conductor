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



def _queued_job(session: Session) -> Job:
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


async def _wait_until(predicate, timeout=5.0):
    import asyncio

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_cancel_kills_running_job_and_marks_cancelled(tmp_path: Path, session: Session):
    import asyncio

    from app.execution import runner

    job = _queued_job(session)
    test_broadcaster = EventBroadcaster()
    events_queue = test_broadcaster.subscribe()
    command = ["python3", "-u", "-c", "import time; print('started'); time.sleep(30)"]

    task = asyncio.create_task(
        runner.start_local_job(job.id, command, tmp_path, session, test_broadcaster)
    )
    await _wait_until(lambda: (tmp_path / f"job-{job.id}.log").exists()
                      and "started" in (tmp_path / f"job-{job.id}.log").read_text())

    assert runner.cancel_job(job.id) is True
    await asyncio.wait_for(task, timeout=5)

    session.refresh(job)
    assert job.status == "cancelled"
    assert "Остановлено пользователем" in Path(job.log_path).read_text()
    events = []
    while not events_queue.empty():
        events.append(events_queue.get_nowait())
    assert events[-1] == {"type": "job-status", "job_id": job.id, "status": "cancelled"}
    assert job.id not in runner._processes


@pytest.mark.asyncio
async def test_cancel_kills_child_processes_too(tmp_path: Path, session: Session):
    # Runner scripts are shell wrappers: killing only the shell would leave
    # the real test process running.
    import asyncio
    import os

    from app.execution import runner

    job = _queued_job(session)
    pid_file = tmp_path / "child.pid"
    command = ["sh", "-c", f"sleep 30 & echo $! > {pid_file}; echo started; wait"]

    task = asyncio.create_task(
        runner.start_local_job(job.id, command, tmp_path, session, EventBroadcaster())
    )
    await _wait_until(lambda: pid_file.exists() and pid_file.read_text().strip())
    child_pid = int(pid_file.read_text())

    runner.cancel_job(job.id)
    await asyncio.wait_for(task, timeout=5)

    def child_alive():
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return False
        # A killed child may linger as a zombie until reaped by init.
        with open(f"/proc/{child_pid}/stat") as f:
            return f.read().split()[2] != "Z"

    await _wait_until(lambda: not child_alive())


@pytest.mark.asyncio
async def test_cancelled_queued_job_never_starts(tmp_path: Path, session: Session):
    from app.execution import runner

    job = _queued_job(session)
    job.status = "cancelled"
    session.add(job)
    session.commit()

    await runner.start_local_job(
        job.id, ["python3", "-c", "print('ran')"], tmp_path, session, EventBroadcaster()
    )

    session.refresh(job)
    assert job.status == "cancelled"
    assert job.log_path is None


def test_cancel_unknown_job_returns_false():
    from app.execution import runner

    assert runner.cancel_job(987654) is False
