import httpx

from app.config import ALLURE_BASE_URL, JENKINS_BASE_URL


class CredentialsRejected(Exception):
    """A check failed; the message is shown to the user as-is."""


async def check_jenkins(user: str, token: str) -> None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{JENKINS_BASE_URL}/me/api/json", auth=httpx.BasicAuth(user, token)
            )
    except httpx.HTTPError as exc:
        raise CredentialsRejected(f"Не удалось подключиться к Jenkins: {exc}") from exc
    if response.status_code in (401, 403):
        raise CredentialsRejected("Jenkins отклонил логин или токен")
    if response.is_error:
        raise CredentialsRejected(f"Jenkins ответил ошибкой {response.status_code}")


async def check_allure(token: str) -> None:
    """Exchange the API token for a JWT; skipped when Allure isn't configured."""
    if not ALLURE_BASE_URL:
        return
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ALLURE_BASE_URL}/api/uaa/oauth/token",
                data={"grant_type": "apitoken", "scope": "openid", "token": token},
            )
    except httpx.HTTPError as exc:
        raise CredentialsRejected(f"Не удалось подключиться к Allure TestOps: {exc}") from exc
    if response.status_code in (400, 401, 403):
        raise CredentialsRejected("Allure TestOps отклонил токен")
    if response.is_error:
        raise CredentialsRejected(f"Allure TestOps ответил ошибкой {response.status_code}")
