import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

import app.db as db
from app.credentials import COOKIE_NAME, Credentials, encode
from app.main import create_app


def make_test_credentials() -> Credentials:
    return Credentials(
        jenkins_user="ci-user", jenkins_token="ci-token", issued_at=int(time.time())
    )


@pytest.fixture(name="session")
def session_fixture(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    # From Task 6 onward, background tasks open their own `Session(app.db.engine)`
    # instead of reusing the request-scoped, DI-overridden session (a
    # request-scoped session is closed before background tasks run — see
    # Task 6's `start_local_job_with_own_session`). Point the module-level
    # engine at the same in-memory test database so those background-task
    # sessions see the rows created through `client` in the same test.
    monkeypatch.setattr(db, "engine", engine)
    # The startup purge sweeps old log files; keep it off the real job_logs/.
    monkeypatch.setattr("app.retention.LOG_DIR", tmp_path / "job_logs")
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session):
    def get_session_override():
        return session

    app_instance = create_app()
    app_instance.dependency_overrides[db.get_session] = get_session_override
    with TestClient(app_instance) as client:
        # Jenkins launches need a user's tokens; tests that cover the
        # "no tokens" path clear this cookie themselves.
        # Same domain the cookie jar files server-set cookies under, so a
        # Set-Cookie from the app replaces or deletes this one.
        client.cookies.set(
            COOKIE_NAME, encode(make_test_credentials()), domain="testserver.local"
        )
        yield client
    app_instance.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_runner_state():
    # Stopping a queued job records its id until the runner picks the job
    # up. In the app that always happens; tests create queued rows without
    # a runner, and job ids restart at 1 per test database.
    from app.execution import runner

    runner._processes.clear()
    runner._cancel_requested.clear()
    yield
    runner._processes.clear()
    runner._cancel_requested.clear()
