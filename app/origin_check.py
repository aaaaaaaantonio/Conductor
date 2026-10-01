"""Reject state-changing requests sent by other sites (CSRF).

Browsers always send Origin on POST/PUT/PATCH/DELETE, so a mismatch means
another site's page made the request. Requests without Origin (curl,
scripts) are let through.
"""

from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app import config

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _allowed(origin: str, request: Request) -> bool:
    if config.CONDUCTOR_ALLOWED_ORIGINS:
        return origin.rstrip("/") in config.CONDUCTOR_ALLOWED_ORIGINS
    # Compare hosts only: behind a TLS-terminating proxy the browser says
    # https while the app sees http.
    return origin != "null" and urlsplit(origin).netloc == request.headers.get("host")


async def origin_check_middleware(request: Request, call_next) -> Response:
    origin = request.headers.get("origin")
    if request.method in UNSAFE_METHODS and origin is not None and not _allowed(origin, request):
        return JSONResponse({"detail": "Запрос с чужого сайта отклонён"}, status_code=403)
    return await call_next(request)
