import pytest

POST = ("/credentials/forget", {})


def _post(client, headers):
    return client.post(POST[0], data=POST[1], headers=headers, follow_redirects=False)


def test_same_origin_post_is_allowed(client):
    assert _post(client, {"Origin": "http://testserver"}).status_code == 303


def test_post_without_origin_is_allowed(client):
    # curl, scripts and tests send no Origin.
    assert _post(client, {}).status_code == 303


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://testserver.evil.example"])
def test_cross_site_post_is_rejected(client, origin):
    resp = _post(client, {"Origin": origin})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Запрос с чужого сайта отклонён"


def test_scheme_mismatch_behind_tls_proxy_is_allowed(client):
    assert _post(client, {"Origin": "https://testserver"}).status_code == 303


def test_cross_site_json_and_delete_are_rejected(client):
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/references", json={"category": "team", "value": "x"}, headers=evil).status_code == 403
    assert client.delete("/api/references/1", headers=evil).status_code == 403


def test_get_is_never_checked(client):
    assert client.get("/python", headers={"Origin": "https://evil.example"}).status_code == 200


def test_allowed_origins_setting(client, monkeypatch):
    monkeypatch.setattr("app.config.CONDUCTOR_ALLOWED_ORIGINS", ["https://conductor.company.ru"])
    assert _post(client, {"Origin": "https://conductor.company.ru"}).status_code == 303
    assert _post(client, {"Origin": "http://testserver"}).status_code == 403
