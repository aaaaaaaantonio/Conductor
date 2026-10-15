import asyncio
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
    assert {"type": "job-status", "job_id": job.id, "status": "success"}.items() <= status_events[-1].items()


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
    assert {"type": "job-status", "job_id": job.id, "status": "failed"}.items() <= status_events[-1].items()



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
    assert {"type": "job-status", "job_id": job.id, "status": "cancelled"}.items() <= events[-1].items()
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


def test_cancel_job_without_a_runner_is_not_remembered():
    # A "running" job left over from a restart has no runner to consume the
    # request, so it must not linger in _cancel_requested forever.
    from app.execution import runner

    runner.cancel_job(987654)

    assert 987654 not in runner._cancel_requested


@pytest.mark.asyncio
async def test_cancel_before_process_exists_still_stops_job(tmp_path: Path, session: Session, monkeypatch):
    from app.execution import runner

    job = _queued_job(session)
    real_exec = runner.asyncio.create_subprocess_exec

    async def cancel_then_spawn(*args, **kwargs):
        assert runner.cancel_job(job.id) is False
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", cancel_then_spawn)

    await asyncio.wait_for(
        runner.start_local_job(
            job.id, ["python3", "-c", "import time; time.sleep(30)"], tmp_path, session, EventBroadcaster()
        ),
        timeout=5,
    )

    session.refresh(job)
    assert job.status == "cancelled"
    assert job.id not in runner._cancel_requested
    assert job.id not in runner._owned


@pytest.mark.asyncio
async def test_start_local_job_adds_env_on_top_of_server_env(tmp_path: Path, session: Session):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    script = "import os; print(os.environ['ZEPHYR_TOKEN'] == 'ze-1'); print(bool(os.environ.get('PATH')))"
    command = ["python3", "-c", script]
    await start_local_job(
        job_id=job.id,
        command=command,
        log_dir=tmp_path,
        session=session,
        broadcaster=EventBroadcaster(),
        env={"ZEPHYR_TOKEN": "ze-1"},
    )

    session.refresh(job)
    assert job.status == "success"
    assert Path(job.log_path).read_text().splitlines() == ["True", "True"]


async def _run(session, tmp_path, script, env=None, broadcaster=None):
    job = _queued_job(session)
    await start_local_job(
        job.id, ["python3", "-c", script], tmp_path, session, broadcaster or EventBroadcaster(), env=env
    )
    session.refresh(job)
    return job


def _drain(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return [e["line"] for e in events if e and e["type"] == "log-line"]


@pytest.mark.asyncio
async def test_very_long_line_is_kept_whole_in_file_and_tail_shown_live(tmp_path, session, monkeypatch):
    monkeypatch.setattr("app.config.LOG_LINE_MAX_CHARS", 50)
    test_broadcaster = EventBroadcaster()
    queue = test_broadcaster.subscribe()

    job = await _run(
        session, tmp_path, "print('a' * 199_990 + 'END_OF_IT'); print('after')", broadcaster=test_broadcaster
    )

    assert job.status == "success"
    file_lines = Path(job.log_path).read_text().splitlines()
    assert file_lines == ["a" * 199_990 + "END_OF_IT", "after"]
    live = _drain(queue)
    assert live[0].startswith("[начало обрезано")
    assert "199999" in live[0]
    assert live[0].endswith("a" * 41 + "END_OF_IT")
    assert live[1] == "after"


@pytest.mark.asyncio
async def test_last_line_without_newline_is_logged(tmp_path, session):
    job = await _run(session, tmp_path, "import sys; sys.stdout.write('one\\ntwo')")
    assert Path(job.log_path).read_text().splitlines() == ["one", "two"]


@pytest.mark.asyncio
async def test_tokens_are_masked_in_file_and_live_log(tmp_path, session):
    test_broadcaster = EventBroadcaster()
    queue = test_broadcaster.subscribe()

    job = await _run(
        session,
        tmp_path,
        "import os; print('token=' + os.environ['ZEPHYR_TOKEN']); print(os.environ['ALLURE_TOKEN'] + '!')",
        env={"ZEPHYR_TOKEN": "ze-secret-1", "ALLURE_TOKEN": "al-secret-2"},
        broadcaster=test_broadcaster,
    )

    text = Path(job.log_path).read_text()
    assert "secret" not in text
    assert text.splitlines() == ["token=***", "***!"]
    assert _drain(queue) == ["token=***", "***!"]


@pytest.mark.asyncio
async def test_very_short_token_values_are_not_masked(tmp_path, session):
    job = await _run(session, tmp_path, "print('abc def')", env={"ZEPHYR_TOKEN": "abc"})
    assert Path(job.log_path).read_text().splitlines() == ["abc def"]


@pytest.mark.asyncio
async def test_live_log_lines_carry_their_line_number(tmp_path, session):
    # Lets the log panel number live lines correctly while a search filter
    # hides some of them.
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)
    test_broadcaster = EventBroadcaster()
    queue = test_broadcaster.subscribe()
    await start_local_job(job.id, ["printf", "a\\nb\\nc\\n"], tmp_path, session, test_broadcaster)
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [(e["n"], e["line"]) for e in events if e["type"] == "log-line"] == [(1, "a"), (2, "b"), (3, "c")]


@pytest.mark.asyncio
async def test_final_status_event_carries_source_and_duration(tmp_path, session):
    # The browser notification says what finished and how long it took.
    job = Job(source="agent_test", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)
    test_broadcaster = EventBroadcaster()
    queue = test_broadcaster.subscribe()
    await start_local_job(job.id, ["sleep", "1.1"], tmp_path, session, test_broadcaster)
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    final = events[-1]
    assert final["type"] == "job-status"
    assert final["status"] == "success"
    assert final["source"] == "agent_test"
    assert final["duration"] in (1, 2)


@pytest.mark.asyncio
async def test_server_shutdown_kills_job_and_marks_it_failed(tmp_path: Path, session: Session):
    # Shutdown cancels the runner task. The test runs in its own process
    # group, so without an explicit kill it outlives Conductor.
    import os

    from app.execution import runner

    job = _queued_job(session)
    command = ["python3", "-u", "-c", "import time; print('started'); time.sleep(30)"]
    task = asyncio.create_task(runner.start_local_job(job.id, command, tmp_path, session, EventBroadcaster()))
    await _wait_until(lambda: (tmp_path / f"job-{job.id}.log").exists()
                      and "started" in (tmp_path / f"job-{job.id}.log").read_text())
    pid = runner._processes[job.id].pid

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    session.refresh(job)
    assert job.status == "failed"
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
