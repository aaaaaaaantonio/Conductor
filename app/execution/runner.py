import asyncio
import os
import signal
from pathlib import Path

from sqlmodel import Session

from app.execution.broadcaster import EventBroadcaster
from app.execution.broadcaster import broadcaster as default_broadcaster
from app.models.jobs import Job

CANCELLED_LOG_LINE = "— Остановлено пользователем —"

# Live subprocesses of running VM jobs, so a "Остановить" request can reach
# them, and jobs asked to stop (possibly before their process exists yet).
_processes: dict[int, asyncio.subprocess.Process] = {}
_cancel_requested: set[int] = set()


def _kill(process: asyncio.subprocess.Process) -> None:
    """Kill the job's whole process group: runner scripts are shell
    wrappers, and killing only the shell would leave the test running."""
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def cancel_job(job_id: int) -> bool:
    """Ask a VM job to stop. Returns True if a live process was killed; a job
    whose process hasn't started yet is stopped as soon as it does."""
    _cancel_requested.add(job_id)
    process = _processes.get(job_id)
    if process is None or process.returncode is not None:
        return False
    _kill(process)
    return True


async def start_local_job(
    job_id: int,
    command: list[str],
    log_dir: Path,
    session: Session,
    broadcaster: EventBroadcaster = default_broadcaster,
    env: dict[str, str] | None = None,
) -> None:
    """`env` is added on top of the server's environment (users' tokens)."""
    job = session.get(Job, job_id)
    assert job is not None
    if job.status == "cancelled" or job_id in _cancel_requested:
        # Stopped while still queued: never start it.
        _cancel_requested.discard(job_id)
        if job.status != "cancelled":
            job.status = "cancelled"
            session.add(job)
            session.commit()
            await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": "cancelled"})
        return

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
            # Own process group, so cancel_job can kill its children too.
            start_new_session=True,
            env={**os.environ, **env} if env else None,
        )
        _processes[job_id] = process
        if job_id in _cancel_requested:
            _kill(process)

        with log_path.open("w") as log_file:
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode(errors="replace").rstrip("\n")
                log_file.write(line + "\n")
                log_file.flush()
                await broadcaster.publish({"type": "log-line", "job_id": job_id, "line": line})

            return_code = await process.wait()
            if job_id in _cancel_requested:
                log_file.write(CANCELLED_LOG_LINE + "\n")
                await broadcaster.publish(
                    {"type": "log-line", "job_id": job_id, "line": CANCELLED_LOG_LINE}
                )
                job.status = "cancelled"
            else:
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
            _kill(process)
            await process.wait()
            raise
    finally:
        _processes.pop(job_id, None)
        _cancel_requested.discard(job_id)
        session.add(job)
        session.commit()
        await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": job.status})


async def start_local_job_with_own_session(
    job_id: int,
    command: list[str],
    log_dir: Path,
    broadcaster: EventBroadcaster = default_broadcaster,
    env: dict[str, str] | None = None,
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
        await start_local_job(job_id, command, log_dir, session, broadcaster, env)

