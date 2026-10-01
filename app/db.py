from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import DATABASE_URL


def engine_connect_args(url: str) -> dict:
    # Request handlers and background tasks share SQLite connections across
    # threads; other drivers reject this SQLite-only option.
    return {"check_same_thread": False} if url.startswith("sqlite") else {}


engine = create_engine(DATABASE_URL, connect_args=engine_connect_args(DATABASE_URL))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
