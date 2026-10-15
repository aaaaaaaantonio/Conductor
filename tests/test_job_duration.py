from datetime import UTC, datetime, timedelta

from app.models.jobs import Job, duration_seconds
from app.templating import format_duration

START = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)


def test_finished_vm_job_lasts_from_creation_to_last_update():
    job = Job(source="python", status="success", params_json="{}", log_path="/x.log",
              created_at=START, updated_at=START + timedelta(minutes=4, seconds=12))
    assert duration_seconds(job) == 252


def test_running_job_lasts_until_now():
    job = Job(source="agent_test", status="running", params_json="{}", log_path="/x.log", created_at=START)
    assert duration_seconds(job, now=START + timedelta(seconds=37)) == 37


def test_naive_timestamps_from_sqlite_are_utc():
    job = Job(source="python", status="failed", params_json="{}", log_path="/x.log",
              created_at=START.replace(tzinfo=None), updated_at=(START + timedelta(seconds=5)).replace(tzinfo=None))
    assert duration_seconds(job) == 5


def test_jenkins_runs_have_no_duration():
    # Conductor doesn't track Jenkins builds, so it can't know how long they took.
    for status in ("triggering", "triggered", "failed"):
        job = Job(source="java", status=status, params_json="{}", created_at=START, updated_at=START)
        assert duration_seconds(job) is None


def test_format_duration():
    assert format_duration(None) == ""
    assert format_duration(0) == "0:00"
    assert format_duration(37) == "0:37"
    assert format_duration(252) == "4:12"
    assert format_duration(3723) == "1:02:03"
