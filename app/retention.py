"""Keep the job history to JOB_RETENTION_DAYS: finished jobs older than
that are deleted together with their log files. Runs at startup and then
hourly (see app/main.py)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from app import config
from app.config import JOB_RETENTION_DAYS
from app.models.jobs import Job

ACTIVE_STATUSES = ("queued", "running", "triggering")
PURGE_INTERVAL = 3600

logger = logging.getLogger(__name__)


def purge_old_jobs(session: Session, log_dir: Path, now: datetime | None = None) -> int:
    """Delete finished jobs created before the retention cutoff and their
    logs, plus orphaned job-*.log files older than the cutoff. `now` is naive
    UTC, like the stored timestamps. Returns the number of jobs deleted."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    cutoff = now - timedelta(days=JOB_RETENTION_DAYS)

    old = session.exec(
        select(Job).where(Job.created_at < cutoff, Job.status.not_in(ACTIVE_STATUSES))
    ).all()
    for job in old:
        if job.log_path:
            Path(job.log_path).unlink(missing_ok=True)
        session.delete(job)
    session.commit()

    if log_dir.is_dir():
        kept = {Path(p).resolve() for p in session.exec(select(Job.log_path)).all() if p}
        cutoff_ts = cutoff.replace(tzinfo=UTC).timestamp()
        for path in log_dir.glob("job-*.log"):
            if path.resolve() not in kept and path.stat().st_mtime < cutoff_ts:
                path.unlink(missing_ok=True)
    return len(old)


def run_purge() -> None:
    # Resolve app.db.engine at call time: tests monkeypatch it.
    from app.db import engine

    with Session(engine) as session:
        deleted = purge_old_jobs(session, config.JOB_LOG_DIR)
    if deleted:
        logger.info("Deleted %d jobs older than %d days", deleted, JOB_RETENTION_DAYS)


async def purge_loop() -> None:
    while True:
        await asyncio.sleep(PURGE_INTERVAL)
        try:
            run_purge()
        except Exception:
            logger.exception("Job history purge failed")
