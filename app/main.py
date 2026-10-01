import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from app.credentials import credentials_middleware
from app.db import init_db
from app.models.jobs import Job
from app.origin_check import origin_check_middleware
from app.retention import purge_loop, run_purge
from app.routers.agent_testing import router as agent_testing_router
from app.routers.credentials import router as credentials_router
from app.routers.history import router as history_router
from app.routers.jobs import router as jobs_router
from app.routers.launch_java import router as launch_java_router
from app.routers.launch_python import router as launch_python_router
from app.routers.references import page_router as references_page_router
from app.routers.references import router as references_router


def recover_stale_jobs(session: Session) -> None:
    statement = select(Job).where(Job.status.in_(["queued", "running", "triggering"]))
    for job in session.exec(statement).all():
        job.status = "failed"
        session.add(job)
    session.commit()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    # Import app.db.engine here, not at module top: tests monkeypatch
    # app.db.engine to an in-memory database (see tests/conftest.py),
    # and a top-level `from app.db import engine` would bind this
    # module's name to the original engine before that monkeypatch runs.
    from app.db import engine

    with Session(engine) as session:
        recover_stale_jobs(session)
    run_purge()
    purge_task = asyncio.create_task(purge_loop())
    try:
        yield
    finally:
        purge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await purge_task


def create_app() -> FastAPI:
    app = FastAPI(title="Test Runner Bot", lifespan=lifespan)
    app.middleware("http")(credentials_middleware)
    # Added last, so it runs first: a rejected request never reaches the app.
    app.middleware("http")(origin_check_middleware)
    app.include_router(references_router)
    app.include_router(references_page_router)
    app.include_router(jobs_router)
    app.include_router(agent_testing_router)
    app.include_router(launch_python_router)
    app.include_router(launch_java_router)
    app.include_router(credentials_router)
    app.include_router(history_router)
    # check_dir=False: the real htmx.min.js/sse.js assets are fetched as a
    # manual deploy step (see the Task 11 brief), so this directory may not
    # exist yet when tests construct the app — a missing directory must not
    # crash app startup.
    app.mount(
        "/static", StaticFiles(directory=Path(__file__).parent / "static", check_dir=False), name="static"
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse(url="/python")

    return app


app = create_app()
