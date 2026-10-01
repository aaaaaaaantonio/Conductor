from collections.abc import Generator

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

from app.config import DATABASE_URL


def engine_connect_args(url: str) -> dict:
    # Request handlers and background tasks share SQLite connections across
    # threads; other drivers reject this SQLite-only option.
    return {"check_same_thread": False} if url.startswith("sqlite") else {}


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    # SQLite ignores FOREIGN KEY constraints unless each connection opts in.
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


engine = create_engine(DATABASE_URL, connect_args=engine_connect_args(DATABASE_URL))
enable_sqlite_foreign_keys(engine)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
