"""Per-user Jenkins/Allure tokens kept in an encrypted HttpOnly cookie.

The browser holds the only copy: the cookie is a Fernet token (AES + HMAC)
under CONDUCTOR_SECRET_KEY, so JS can't read it and a copied cookie reveals
nothing. The server decrypts it per request, uses the tokens in memory and
never stores or logs them.

Expiry is sliding: the Fernet timestamp is the time of the last re-issue,
and every request older than CREDS_REFRESH_AFTER re-issues the cookie. The
tokens expire after an idle window (12 h, or 30 days with "remember") and in
any case CREDS_MAX_LIFETIME after they were entered (`issued_at`).
"""

import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request, Response

from app.config import (
    CONDUCTOR_SECRET_KEY,
    COOKIE_SECURE,
    CREDS_MAX_LIFETIME,
    CREDS_REFRESH_AFTER,
    CREDS_REMEMBER_IDLE_TTL,
    CREDS_SESSION_IDLE_TTL,
)

COOKIE_NAME = "conductor_creds"
VM_TOKENS_MISSING = "Для запуска на VM нужны токены Allure TestOps и Jira Zephyr — введите их на странице «Доступы»"
# Tolerated clock skew for a cookie stamped slightly in the future.
_CLOCK_SKEW = 60

logger = logging.getLogger(__name__)
_fernet_instance: Fernet | None = None


@dataclass(frozen=True)
class Credentials:
    jenkins_user: str
    jenkins_token: str = field(repr=False)
    allure_token: str | None = field(default=None, repr=False)
    remember: bool = False
    issued_at: int = 0
    zephyr_token: str | None = field(default=None, repr=False)

    def jenkins_auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(self.jenkins_user, self.jenkins_token)

    def vm_env(self) -> dict[str, str] | None:
        """Environment for a VM run, or None if a required token is missing."""
        if not (self.allure_token and self.zephyr_token):
            return None
        return {"ALLURE_TOKEN": self.allure_token, "ZEPHYR_TOKEN": self.zephyr_token}

    @property
    def idle_ttl(self) -> int:
        return CREDS_REMEMBER_IDLE_TTL if self.remember else CREDS_SESSION_IDLE_TTL

    @property
    def expires_at(self) -> int:
        """Hard deadline, however active the user is."""
        return self.issued_at + CREDS_MAX_LIFETIME


@dataclass(frozen=True)
class Decoded:
    creds: Credentials
    refreshed_at: int


def _fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        secret = CONDUCTOR_SECRET_KEY
        if not secret:
            logger.warning(
                "CONDUCTOR_SECRET_KEY is not set: using a random key, saved "
                "Jenkins/Allure tokens will be lost on restart"
            )
            secret = os.urandom(32).hex()
        # Any string works as the secret; Fernet needs 32 url-safe base64 bytes.
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        _fernet_instance = Fernet(key)
    return _fernet_instance


def encode(creds: Credentials, now: int | None = None) -> str:
    now = int(time.time()) if now is None else now
    payload = json.dumps(asdict(creds)).encode()
    return _fernet().encrypt_at_time(payload, now).decode()


def decode(value: str, now: int | None = None) -> Decoded | None:
    """The cookie's credentials, or None if it is forged, garbled or expired."""
    now = int(time.time()) if now is None else now
    try:
        token = value.encode()
        creds = Credentials(**json.loads(_fernet().decrypt(token)))
        refreshed_at = _fernet().extract_timestamp(token)
    except (InvalidToken, ValueError, TypeError):
        return None
    if refreshed_at > now + _CLOCK_SKEW:
        return None
    if now - refreshed_at > creds.idle_ttl or now > creds.expires_at:
        return None
    return Decoded(creds, refreshed_at)


def set_cookie(response: Response, creds: Credentials) -> None:
    max_age = None
    if creds.remember:
        remaining = creds.expires_at - int(time.time())
        max_age = max(0, min(creds.idle_ttl, remaining))
    response.set_cookie(
        COOKIE_NAME,
        encode(creds),
        max_age=max_age,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME, httponly=True, secure=COOKIE_SECURE, samesite="strict"
    )


def mark_changed(request: Request) -> None:
    """Tell the middleware an endpoint set or cleared the cookie itself."""
    request.state.credentials_changed = True


async def credentials_middleware(request: Request, call_next) -> Response:
    raw = request.cookies.get(COOKIE_NAME)
    decoded = decode(raw) if raw else None
    request.state.credentials = decoded.creds if decoded else None

    response = await call_next(request)

    if getattr(request.state, "credentials_changed", False):
        return response
    if raw and decoded is None:
        clear_cookie(response)
    elif decoded and int(time.time()) - decoded.refreshed_at >= CREDS_REFRESH_AFTER:
        set_cookie(response, decoded.creds)
    return response


def get_credentials(request: Request) -> Credentials | None:
    return getattr(request.state, "credentials", None)
