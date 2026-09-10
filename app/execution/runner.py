import asyncio
from pathlib import Path

from sqlmodel import Session

from app.execution.broadcaster import EventBroadcaster
from app.execution.broadcaster import broadcaster as default_broadcaster
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

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        with log_path.open("w") as log_file:
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="replace").rstrip("\n")
                log_file.write(line + "\n")
                log_file.flush()
                await broadcaster.publish({"type": "log-line", "job_id": job_id, "line": line})

        return_code = await process.wait()
        job.status = "success" if return_code == 0 else "failed"
    except Exception:
        # Whatever went wrong (e.g. a decode error on non-UTF-8 output), the
        # subprocess must still be reaped and the job must still land in a
        # terminal state with a broadcast — otherwise the process can zombie
        # and any UI waiting on job-status hangs forever with status stuck
        # at "running".
        job.status = "failed"
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
