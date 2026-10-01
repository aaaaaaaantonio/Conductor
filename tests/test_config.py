import importlib
import time
from pathlib import Path

import pytest

import app.config as config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def reload_config(monkeypatch):
    # Reloading rebinds app.config's module globals; reload once more after
    # the test (with the env restored) so later tests see the real values.
    yield lambda: importlib.reload(config)
    monkeypatch.undo()
    importlib.reload(config)


def test_default_paths_are_anchored_to_project_not_cwd(reload_config, monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JOB_LOG_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    reload_config()
    assert config.BASE_DIR == PROJECT_ROOT
    assert config.DATABASE_URL == f"sqlite:///{PROJECT_ROOT / 'test_runner.db'}"
    assert config.JOB_LOG_DIR == PROJECT_ROOT / "job_logs"


def test_env_overrides_database_url_and_log_dir(reload_config, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:////srv/conductor/conductor.db")
    monkeypatch.setenv("JOB_LOG_DIR", str(tmp_path / "logs"))
    reload_config()
    assert config.DATABASE_URL == "sqlite:////srv/conductor/conductor.db"
    assert config.JOB_LOG_DIR == tmp_path / "logs"


def test_sqlite_only_connect_args():
    from app.db import engine_connect_args

    assert engine_connect_args("sqlite:///x.db") == {"check_same_thread": False}
    assert engine_connect_args("postgresql://u@h/db") == {}


def test_tests_never_write_job_logs_into_project_dir():
    # conftest points JOB_LOG_DIR at a temp dir for every test.
    assert PROJECT_ROOT / "job_logs" != config.JOB_LOG_DIR


def test_local_job_log_goes_to_configured_dir(client, session):
    team = client.post("/api/references", json={"category": "team", "value": "QA"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "a"}).json()
    test = client.post(
        f"/api/agents/{agent['id']}/tests",
        json={"path": "echo", "flags": [], "fields": []},
    ).json()
    job_id = client.post(f"/api/agent-tests/{test['id']}/launch", json={"values": {}}).json()["job_id"]

    from app.models.jobs import Job

    for _ in range(50):
        session.expire_all()
        job = session.get(Job, job_id)
        if job.log_path:
            break
        time.sleep(0.05)
    assert Path(job.log_path).parent == config.JOB_LOG_DIR


def test_pages_render_when_started_outside_project_dir(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert client.get("/references").status_code == 200
    assert client.get("/static/app.js").status_code == 200
