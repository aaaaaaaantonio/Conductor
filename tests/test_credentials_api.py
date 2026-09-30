import base64
import time

import httpx
import pytest
from sqlmodel import select

from app import config
from app.credentials import COOKIE_NAME, Credentials, decode, encode
from app.models.jobs import Job

TABS = ["java", "python"]
# Patching `<module>.httpx.AsyncClient` replaces it on the shared httpx
# module, so build mock clients from the original class.
RealAsyncClient = httpx.AsyncClient


def _mock_http(monkeypatch, module: str, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(
        f"{module}.httpx.AsyncClient",
        lambda *a, **kw: RealAsyncClient(transport=httpx.MockTransport(recording)),
    )
    return requests


def _basic(user: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()


def _cookie(resp: httpx.Response) -> str:
    return next(v for v in resp.headers.get_list("set-cookie") if v.startswith(COOKIE_NAME))


def _restart(client, tab):
    return client.post(f"/{tab}/restart", data={"build_number": "5"})


# ---------- the "Доступы" page ----------


def test_credentials_page_renders_form_without_tokens(client):
    resp = client.get("/credentials")
    assert resp.status_code == 200
    assert 'name="jenkins_user"' in resp.text
    assert 'name="jenkins_token" type="password"' in resp.text
    assert 'name="allure_token" type="password"' in resp.text
    assert 'name="remember"' in resp.text
    assert "ci-user" in resp.text
    assert "ci-token" not in resp.text


def test_sidebar_links_to_credentials_page(client):
    assert 'href="/credentials"' in client.get("/python").text


def test_save_checks_jenkins_and_sets_encrypted_httponly_cookie(client, monkeypatch):
    client.cookies.clear()
    requests = _mock_http(
        monkeypatch,
        "app.execution.credential_checks",
        lambda r: httpx.Response(200, json={"id": "bob"}),
    )

    resp = client.post(
        "/credentials",
        data={"jenkins_user": "bob", "jenkins_token": "tok-1", "allure_token": ""},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/credentials?saved=1"
    assert requests[0].url.path == "/me/api/json"
    assert requests[0].headers["Authorization"] == _basic("bob", "tok-1")

    cookie = _cookie(resp)
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie.replace("Strict", "strict")
    assert "tok-1" not in cookie
    # Without "remember" it is a browser-session cookie.
    assert "Max-Age" not in cookie

    creds = decode(client.cookies[COOKIE_NAME]).creds
    assert (creds.jenkins_user, creds.jenkins_token, creds.remember) == ("bob", "tok-1", False)
    assert creds.allure_token is None


def test_remember_sets_persistent_cookie(client, monkeypatch):
    client.cookies.clear()
    _mock_http(monkeypatch, "app.execution.credential_checks", lambda r: httpx.Response(200))

    resp = client.post(
        "/credentials",
        data={"jenkins_user": "bob", "jenkins_token": "t", "remember": "on"},
        follow_redirects=False,
    )

    assert f"Max-Age={config.CREDS_REMEMBER_IDLE_TTL}" in _cookie(resp)
    assert decode(client.cookies[COOKIE_NAME]).creds.remember is True


def test_rejected_jenkins_token_is_not_saved(client, monkeypatch):
    client.cookies.clear()
    _mock_http(monkeypatch, "app.execution.credential_checks", lambda r: httpx.Response(401))

    resp = client.post(
        "/credentials", data={"jenkins_user": "bob", "jenkins_token": "bad"}
    )

    assert resp.status_code == 400
    assert "Jenkins отклонил логин или токен" in resp.text
    assert "bad" not in resp.text
    assert COOKIE_NAME not in client.cookies


def test_unreachable_jenkins_is_reported(client, monkeypatch):
    client.cookies.clear()

    def boom(request):
        raise httpx.ConnectError("refused")

    _mock_http(monkeypatch, "app.execution.credential_checks", boom)

    resp = client.post("/credentials", data={"jenkins_user": "bob", "jenkins_token": "t"})

    assert resp.status_code == 400
    assert "Не удалось подключиться к Jenkins" in resp.text


def test_allure_token_checked_when_allure_configured(client, monkeypatch):
    client.cookies.clear()
    monkeypatch.setattr("app.execution.credential_checks.ALLURE_BASE_URL", "http://allure")

    def handler(request):
        if request.url.host == "allure":
            return httpx.Response(401)
        return httpx.Response(200)

    requests = _mock_http(monkeypatch, "app.execution.credential_checks", handler)

    resp = client.post(
        "/credentials",
        data={"jenkins_user": "bob", "jenkins_token": "t", "allure_token": "al-bad"},
    )

    assert resp.status_code == 400
    assert "Allure TestOps отклонил токен" in resp.text
    allure_req = next(r for r in requests if r.url.host == "allure")
    assert allure_req.url.path == "/api/uaa/oauth/token"
    assert b"token=al-bad" in allure_req.content
    assert COOKIE_NAME not in client.cookies


def test_forget_clears_cookie(client):
    resp = client.post("/credentials/forget", follow_redirects=False)
    assert resp.status_code == 303
    assert COOKIE_NAME not in client.cookies
    assert "Токены не заданы" in client.get("/credentials").text


# ---------- launches use the user's tokens ----------


@pytest.mark.parametrize("tab", TABS)
def test_restart_sends_users_basic_auth_to_jenkins(client, monkeypatch, tab):
    requests = _mock_http(
        monkeypatch,
        "app.execution.jenkins_launch",
        lambda r: httpx.Response(201, headers={"Location": "https://jenkins/queue/item/1/"}),
    )

    _restart(client, tab)

    assert requests[0].headers["Authorization"] == _basic("ci-user", "ci-token")


@pytest.mark.parametrize("tab", TABS)
def test_launch_without_tokens_asks_for_them(client, session, monkeypatch, tab):
    client.cookies.clear()
    requests = _mock_http(
        monkeypatch, "app.execution.jenkins_launch", lambda r: httpx.Response(201)
    )

    resp = _restart(client, tab)

    assert requests == []
    assert "Токены Jenkins не заданы" in resp.text
    assert 'href="/credentials"' in resp.text
    job = session.exec(select(Job)).one()
    session.refresh(job)
    assert job.status == "failed"


@pytest.mark.parametrize("tab", TABS)
def test_jenkins_401_asks_to_update_token(client, monkeypatch, tab):
    _mock_http(monkeypatch, "app.execution.jenkins_launch", lambda r: httpx.Response(401))

    resp = _restart(client, tab)

    assert "Jenkins отклонил токен" in resp.text
    assert 'href="/credentials"' in resp.text


# ---------- sliding expiry ----------


def _stale_cookie(age: int) -> str:
    creds = Credentials(jenkins_user="ci-user", jenkins_token="ci-token", issued_at=int(time.time()) - age)
    return encode(creds, now=int(time.time()) - age)


def test_activity_reissues_cookie(client):
    client.cookies.set(COOKIE_NAME, _stale_cookie(config.CREDS_REFRESH_AFTER + 5), domain="testserver.local")

    resp = client.get("/python")

    decoded = decode(_cookie(resp).split(";")[0].split("=", 1)[1])
    assert decoded is not None
    assert decoded.refreshed_at >= int(time.time()) - 2


def test_recent_cookie_is_not_reissued(client):
    resp = client.get("/python")
    assert not any(v.startswith(COOKIE_NAME) for v in resp.headers.get_list("set-cookie"))


def test_expired_cookie_is_deleted(client):
    client.cookies.set(COOKIE_NAME, _stale_cookie(config.CREDS_SESSION_IDLE_TTL + 5), domain="testserver.local")

    resp = client.get("/credentials")

    assert "Токены не заданы" in resp.text
    assert 'Max-Age=0' in _cookie(resp) or "expires=Thu, 01 Jan 1970" in _cookie(resp)
