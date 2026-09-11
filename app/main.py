from fastapi import FastAPI

from app.db import init_db
from app.routers.references import router as references_router
from app.routers.jobs import router as jobs_router
from app.routers.agent_testing import router as agent_testing_router


def create_app() -> FastAPI:
    app = FastAPI(title="Test Runner Bot")
    app.include_router(references_router)
    app.include_router(jobs_router)
    app.include_router(agent_testing_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
