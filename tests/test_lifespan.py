import asyncio
import warnings

from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import create_app
from app.models.jobs import Job


def test_startup_marks_stale_jobs_failed_through_app_lifespan(session):
    session.add(Job(source="python", status="running", params_json="{}"))
    session.commit()

    with TestClient(create_app()):
        pass

    session.expire_all()
    assert [j.status for j in session.exec(select(Job)).all()] == ["failed"]


def test_shutdown_cancels_purge_loop(session, monkeypatch):
    events = []

    async def fake_purge_loop():
        events.append("started")
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("cancelled")
            raise

    monkeypatch.setattr("app.main.purge_loop", fake_purge_loop)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
    assert events == ["started", "cancelled"]


def test_app_does_not_use_deprecated_on_event(session):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with TestClient(create_app()):
            pass
    assert not [w for w in caught if "on_event" in str(w.message)]
