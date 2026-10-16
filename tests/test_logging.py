import logging
import logging.handlers

import httpx
import pytest

from app import config
from app.execution.broadcaster import EventBroadcaster
from app.execution.runner import start_local_job
from app.logging_setup import configure_logging
from app.models.jobs import Job

RealAsyncClient = httpx.AsyncClient


@pytest.fixture(autouse=True)
def capture_app_logs(caplog):
    caplog.set_level(logging.INFO, logger="app")


def _jenkins_replies(monkeypatch, status: int):
    monkeypatch.setattr(
        "app.execution.credential_checks.httpx.AsyncClient",
        lambda *a, **kw: RealAsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))),
    )


def test_rejected_credentials_log_reason_without_token(client, monkeypatch, caplog):
    _jenkins_replies(monkeypatch, 401)
    resp = client.post("/credentials", data={"jenkins_user": "bob", "jenkins_token": "s3cret"})
    assert resp.status_code == 400
    assert "POST /credentials → 400: Jenkins отклонил логин или токен (user bob)" in caplog.text
    assert "s3cret" not in caplog.text


def test_http_exception_is_logged(client, caplog):
    assert client.get("/api/agent-tests/999").status_code == 404
    assert "GET /api/agent-tests/999 → 404: Тест не найден" in caplog.text


def test_validation_error_is_logged_without_input(client, caplog):
    resp = client.post("/credentials", data={"jenkins_user": "bob"})
    assert resp.status_code == 422
    assert "POST /credentials → 422: body.jenkins_token: Field required" in caplog.text


def test_cross_site_request_is_logged(client, caplog):
    resp = client.post("/credentials/forget", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert "POST /credentials/forget → 403: Origin https://evil.example, Host testserver" in caplog.text


def test_refused_launch_is_logged(client, caplog):
    client.post("/java/launch", data={"regression_type": "smoke", "part": "front", "thread_mode": "multi"})
    assert "Launch refused: POST /java/launch:" in caplog.text


@pytest.fixture
def clean_loggers(monkeypatch):
    loggers = [logging.getLogger(name) for name in ("app", "uvicorn", "uvicorn.access")]
    for logger in loggers:
        monkeypatch.setattr(logger, "handlers", [])
        monkeypatch.setattr(logger, "propagate", logger.propagate)
        monkeypatch.setattr(logger, "level", logger.level)
    yield loggers
    for logger in loggers:
        for handler in logger.handlers:
            handler.close()


def test_configure_logging_is_idempotent(clean_loggers):
    app_logger = clean_loggers[0]
    configure_logging("debug")
    configure_logging("debug")
    assert len(app_logger.handlers) == 1
    assert app_logger.level == logging.DEBUG


def test_log_file_takes_app_and_uvicorn_logs(tmp_path, clean_loggers):
    log_file = tmp_path / "testdepot.log"
    # uvicorn sets up its console handlers before it imports the app.
    for name in ("uvicorn", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.INFO)
        logging.getLogger(name).addHandler(logging.StreamHandler())
    configure_logging("info", log_file=str(log_file))

    logging.getLogger("app.requests").warning("refused")
    logging.getLogger("uvicorn.access").info("POST /x 400")
    logging.getLogger("uvicorn.error").info("Started server process")

    text = log_file.read_text()
    assert "WARNING app.requests: refused" in text
    assert "INFO uvicorn.access: POST /x 400" in text
    assert "INFO uvicorn.error: Started server process" in text
    for logger in clean_loggers:
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.handlers.RotatingFileHandler)


def test_log_file_is_cleared_on_start(tmp_path, clean_loggers):
    log_file = tmp_path / "testdepot.log"
    log_file.write_text("old run\n")
    (tmp_path / "testdepot.log.1").write_text("older run\n")
    (tmp_path / "testdepot.log.7").write_text("from bigger LOG_BACKUPS\n")
    (tmp_path / "testdepot.log.bak").write_text("not ours\n")

    configure_logging("info", log_file=str(log_file))
    logging.getLogger("app").info("new run")

    assert log_file.read_text().endswith("new run\n")
    assert "old run" not in log_file.read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["testdepot.log", "testdepot.log.bak"]


def test_log_file_rotates_by_size(tmp_path, clean_loggers):
    log_file = tmp_path / "testdepot.log"
    configure_logging("info", log_file=str(log_file), max_bytes=1000, backups=2)
    for i in range(100):
        logging.getLogger("app").info("line %03d %s", i, "x" * 50)

    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["testdepot.log", "testdepot.log.1", "testdepot.log.2"]
    assert all(p.stat().st_size <= 1000 for p in tmp_path.iterdir())
    assert "line 099" in log_file.read_text()


def test_log_level_setting(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    import importlib

    importlib.reload(config)
    try:
        assert config.LOG_LEVEL == "WARNING"
        assert config.LOG_FILE == ""
        assert config.LOG_MAX_MB == 10
        assert config.LOG_BACKUPS == 2
    finally:
        monkeypatch.delenv("LOG_LEVEL")
        importlib.reload(config)


@pytest.mark.asyncio
async def test_vm_job_start_and_failure_are_logged(tmp_path, session, caplog):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    await start_local_job(
        job_id=job.id,
        command=["python3", "-c", "raise SystemExit(3)"],
        log_dir=tmp_path,
        session=session,
        broadcaster=EventBroadcaster(),
    )

    assert f"Job {job.id} (python): started python3 -c raise SystemExit(3)" in caplog.text
    assert f"Job {job.id}: exited with code 3" in caplog.text
    assert f"Job {job.id} (python): failed" in caplog.text


@pytest.mark.asyncio
async def test_vm_job_missing_executable_is_logged(tmp_path, session, caplog):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    await start_local_job(
        job_id=job.id, command=["/no/such/runner"], log_dir=tmp_path, session=session, broadcaster=EventBroadcaster()
    )

    assert f"Job {job.id}: failed to start /no/such/runner" in caplog.text
