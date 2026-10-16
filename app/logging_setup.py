"""Application logs (logger "app.*") next to uvicorn's access log.

uvicorn configures only its own loggers; without a handler here, app
messages below WARNING are dropped and refused requests show up only as
a bare "POST ... 400" access line.

With LOG_FILE set, app and uvicorn logs go to that file only: rotated by
size so it can't grow without bound, and started afresh on every restart.
"""

import logging
import logging.handlers
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.requests")


FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# uvicorn.error propagates to "uvicorn"; uvicorn.access doesn't propagate.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.access")


def _clear_old_logs(path: Path) -> None:
    # The file and all its numbered backups, even beyond the current
    # LOG_BACKUPS: the previous run may have kept more.
    backup = re.compile(re.escape(path.name) + r"\.\d+")
    for old in path.parent.glob(path.name + ".*"):
        if backup.fullmatch(old.name):
            old.unlink()
    path.unlink(missing_ok=True)


def configure_logging(
    level: str, log_file: str = "", max_bytes: int = 10 * 1024 * 1024, backups: int = 2
) -> None:
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level.upper())
    if app_logger.handlers:
        return  # create_app() runs again (tests): keep the file, don't clear it
    if not log_file:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMAT))
        app_logger.addHandler(handler)
        return

    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    _clear_old_logs(path)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(FORMAT))
    app_logger.addHandler(handler)
    # Replace uvicorn's console output too: under nohup it would be one more
    # file growing without bound.
    for name in UVICORN_LOGGERS:
        logging.getLogger(name).handlers = [handler]
    logging.getLogger("uvicorn.access").propagate = False


def log_refused(request: Request, status_code: int, reason: str) -> None:
    logger.warning("%s %s → %d: %s", request.method, request.url.path, status_code, reason)


def install_error_logging(app: FastAPI) -> None:
    """Log why a request got a 4xx/5xx before the default handlers answer."""

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        log_refused(request, exc.status_code, str(exc.detail))
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # Field locations and messages only: inputs may hold tokens.
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
        )
        log_refused(request, 422, reasons)
        return await request_validation_exception_handler(request, exc)
