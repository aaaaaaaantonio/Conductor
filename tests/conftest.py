import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

import app.db as db
from app.main import create_app


@pytest.fixture(name="session")
def session_fixture(monkeypatch):
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
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session):
    def get_session_override():
        return session

    app_instance = create_app()
    app_instance.dependency_overrides[db.get_session] = get_session_override
    with TestClient(app_instance) as client:
        yield client
    app_instance.dependency_overrides.clear()
