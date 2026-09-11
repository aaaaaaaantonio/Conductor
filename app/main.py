from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers.references import router as references_router
from app.routers.jobs import router as jobs_router
from app.routers.agent_testing import router as agent_testing_router
from app.routers.launch_python import router as launch_python_router


def create_app() -> FastAPI:
    app = FastAPI(title="Test Runner Bot")
    app.include_router(references_router)
    app.include_router(jobs_router)
    app.include_router(agent_testing_router)
    app.include_router(launch_python_router)
    # check_dir=False: the real htmx.min.js/sse.js assets are fetched as a
    # manual deploy step (see the Task 11 brief), so this directory may not
    # exist yet when tests construct the app — a missing directory must not
    # crash app startup.
    app.mount(
        "/static", StaticFiles(directory="app/static", check_dir=False), name="static"
    )

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
