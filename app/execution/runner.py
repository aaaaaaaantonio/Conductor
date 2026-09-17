import asyncio
from pathlib import Path

import httpx
from sqlmodel import Session

from app.execution.broadcaster import EventBroadcaster
from app.execution.broadcaster import broadcaster as default_broadcaster
from app.execution.jenkins_client import poll_build_status, trigger_build
from app.models.jobs import Job


async def start_local_job(
    job_id: int,
    command: list[str],
    log_dir: Path,
    session: Session,
    broadcaster: EventBroadcaster = default_broadcaster,
) -> None:
    job = session.get(Job, job_id)
    assert job is not None

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"job-{job_id}.log"
    job.status = "running"
    job.log_path = str(log_path)
    session.add(job)
    session.commit()
    await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": "running"})

    process: asyncio.subprocess.Process | None = None

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        with log_path.open("w") as log_file:
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="replace").rstrip("\n")
                log_file.write(line + "\n")
                log_file.flush()
                await broadcaster.publish({"type": "log-line", "job_id": job_id, "line": line})

        return_code = await process.wait()
        job.status = "success" if return_code == 0 else "failed"
    except Exception as exc:
        # Whatever went wrong, the job must still land in a terminal state
        # with a broadcast — otherwise any UI waiting on job-status hangs
        # forever with status stuck at "running".
        job.status = "failed"
        if process is None:
            # The subprocess never started at all (e.g. `command[0]` is not
            # a valid executable — a bad path, insufficient host/agent
            # availability, etc.). There's no process to reap, but the
            # failure must still be visible in the job's log rather than
            # silently lost.
            with log_path.open("w") as log_file:
                log_file.write(f"Failed to start process: {exc}\n")
        else:
            # The subprocess started but something went wrong while
            # streaming its output (e.g. a decode error on non-UTF-8
            # output). It must still be reaped so it doesn't zombie.
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
    finally:
        session.add(job)
        session.commit()
        await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": job.status})


async def start_local_job_with_own_session(
    job_id: int,
    command: list[str],
    log_dir: Path,
    broadcaster: EventBroadcaster = default_broadcaster,
) -> None:
    """Entry point for BackgroundTasks — opens its own Session.

    A FastAPI request-scoped `session` (from `Depends(get_session)`) is
    closed by FastAPI's dependency exit stack before background tasks run,
    so a background task must never receive that session directly. This
    wrapper opens a fresh one against the shared `engine` instead. Route
    handlers schedule this function, not `start_local_job`, directly.
    """
    from app.db import engine as db_engine

    with Session(db_engine) as session:
        await start_local_job(job_id, command, log_dir, session, broadcaster)


async def start_jenkins_job(
    job_id: int,
    base_url: str,
    job_name: str,
    params: dict,
    session: Session,
    client: httpx.AsyncClient,
    broadcaster: EventBroadcaster = default_broadcaster,
    poll_interval: float = 5.0,
) -> None:
    job = session.get(Job, job_id)
    assert job is not None

    job.status = "running"
    session.add(job)
    session.commit()
    await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": "running"})

    try:
        build_url = await trigger_build(base_url, job_name, params, client)
        job.jenkins_build_id = build_url
        session.add(job)
        session.commit()

        status = "running"
        while status == "running":
            await asyncio.sleep(poll_interval)
            status = await poll_build_status(base_url, build_url, client)
        job.status = status
    except Exception:
        # A failure to trigger/poll the build must still land the job in a
        # terminal state with a broadcast — otherwise the UI waiting on
        # job-status hangs forever with status stuck at "running".
        job.status = "failed"
    finally:
        session.add(job)
        session.commit()
        await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": job.status})


async def start_jenkins_job_with_own_session(
    job_id: int,
    base_url: str,
    job_name: str,
    params: dict,
    broadcaster: EventBroadcaster = default_broadcaster,
    poll_interval: float = 5.0,
) -> None:
    """Entry point for BackgroundTasks — opens its own Session and http client.

    Mirrors `start_local_job_with_own_session`: a request-scoped `session`
    is closed before background tasks run, so this opens a fresh one
    against the shared `engine` instead.
    """
    from app.db import engine as db_engine

    with Session(db_engine) as session:
        async with httpx.AsyncClient() as client:
            await start_jenkins_job(
                job_id, base_url, job_name, params, session, client, broadcaster, poll_interval
            )
