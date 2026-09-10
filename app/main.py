from fastapi import FastAPI

from app.db import init_db


def create_app() -> FastAPI:
    app = FastAPI(title="Test Runner Bot")

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
