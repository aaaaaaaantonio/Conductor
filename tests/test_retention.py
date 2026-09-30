import os
from datetime import datetime, timedelta

from sqlmodel import select

from app.config import JOB_RETENTION_DAYS
from app.models.jobs import Job
from app.retention import purge_old_jobs

NOW = datetime(2026, 9, 30, 12, 0)
OLD = NOW - timedelta(days=JOB_RETENTION_DAYS, minutes=1)
FRESH = NOW - timedelta(days=JOB_RETENTION_DAYS) + timedelta(minutes=1)


def _job(session, status, created_at, log_path=None):
    job = Job(source="python", status=status, params_json="{}", created_at=created_at, log_path=log_path)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_purges_finished_jobs_older_than_retention(session, tmp_path):
    for status in ("success", "failed", "triggered"):
        _job(session, status, OLD)
    keep = _job(session, "success", FRESH)

    assert purge_old_jobs(session, tmp_path, now=NOW) == 3

    assert [j.id for j in session.exec(select(Job)).all()] == [keep.id]


def test_keeps_active_jobs_however_old(session, tmp_path):
    for status in ("queued", "running", "triggering"):
        _job(session, status, OLD)

    assert purge_old_jobs(session, tmp_path, now=NOW) == 0
    assert len(session.exec(select(Job)).all()) == 3


def test_deletes_log_files_of_purged_jobs(session, tmp_path):
    old_log = tmp_path / "job-1.log"
    old_log.write_text("old")
    fresh_log = tmp_path / "job-2.log"
    fresh_log.write_text("fresh")
    _job(session, "success", OLD, log_path=str(old_log))
    _job(session, "success", FRESH, log_path=str(fresh_log))

    purge_old_jobs(session, tmp_path, now=NOW)

    assert not old_log.exists()
    assert fresh_log.exists()


def test_missing_log_file_does_not_break_purge(session, tmp_path):
    _job(session, "failed", OLD, log_path=str(tmp_path / "gone.log"))
    assert purge_old_jobs(session, tmp_path, now=NOW) == 1


def test_sweeps_stale_orphan_log_files(session, tmp_path):
    # Logs left behind by jobs that no longer exist in the database.
    stale = tmp_path / "job-40.log"
    stale.write_text("x")
    old_ts = (NOW - timedelta(days=JOB_RETENTION_DAYS + 1)).timestamp()
    os.utime(stale, (old_ts, old_ts))
    recent = tmp_path / "job-41.log"
    recent.write_text("x")
    os.utime(recent, (NOW.timestamp(), NOW.timestamp()))
    # A stale file that still belongs to a kept (active) job stays.
    active_log = tmp_path / "job-42.log"
    active_log.write_text("x")
    os.utime(active_log, (old_ts, old_ts))
    _job(session, "running", OLD, log_path=str(active_log))
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("x")
    os.utime(unrelated, (old_ts, old_ts))

    purge_old_jobs(session, tmp_path, now=NOW)

    assert not stale.exists()
    assert recent.exists()
    assert active_log.exists()
    assert unrelated.exists()


def test_missing_log_dir_is_fine(session, tmp_path):
    _job(session, "success", OLD)
    assert purge_old_jobs(session, tmp_path / "nope", now=NOW) == 1
