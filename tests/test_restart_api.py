import httpx
import pytest
from sqlmodel import select

from app.execution.jenkins_launch import LaunchResult
from app.models.jobs import Job

# (tab, Jenkins job it must restart into — the same one its normal launch uses)
TABS = [("java", "java-tests"), ("python", "python-tests")]


def _mock_jenkins(monkeypatch, response: httpx.Response) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.execution.jenkins_launch.httpx.AsyncClient", lambda *a, **kw: mock_client
    )
    return requests


@pytest.mark.parametrize("tab,jenkins_job", TABS)
def test_tab_has_restart_form(client, tab, jenkins_job):
    resp = client.get(f"/{tab}")
    assert f'hx-post="/{tab}/restart"' in resp.text
    assert 'name="build_number"' in resp.text
    assert "Перезапустить" in resp.text


@pytest.mark.parametrize("tab,jenkins_job", TABS)
def test_restart_triggers_same_jenkins_job_with_build_number(
    client, session, monkeypatch, tab, jenkins_job
):
    requests = _mock_jenkins(
        monkeypatch, httpx.Response(201, headers={"Location": "https://jenkins/queue/item/3/"})
    )

    resp = client.post(f"/{tab}/restart", data={"build_number": "1234"})
    assert resp.status_code == 200

    assert len(requests) == 1
    assert requests[0].url.path == f"/job/{jenkins_job}/buildWithParameters"
    assert requests[0].url.params["restart_build"] == "1234"

    job = session.exec(select(Job)).one()
    session.refresh(job)
    assert job.source == tab
    assert job.status == "triggered"
    assert '"restart_build": 1234' in job.params_json
    assert job.jenkins_build_id == "https://jenkins/queue/item/3/"

    # Same feed as a normal launch: prepended to the log panel.
    assert resp.headers["HX-Retarget"] == "#job-log-body"
    assert resp.headers["HX-Reswap"] == "afterbegin"
    assert "перезапуск #1234" in resp.text
    assert 'href="https://jenkins/queue/item/3/"' in resp.text


@pytest.mark.parametrize("tab,jenkins_job", TABS)
def test_restart_calls_tab_specific_hook(client, session, monkeypatch, tab, jenkins_job):
    calls = []

    async def fake_restart(build_number):
        calls.append(build_number)
        return LaunchResult(message="Перезапуск принят", url="https://ci/job/7")

    monkeypatch.setattr(f"app.routers.launch_{tab}.restart_{tab}", fake_restart)

    resp = client.post(f"/{tab}/restart", data={"build_number": "42"})

    assert calls == [42]
    assert "Перезапуск принят" in resp.text
    assert 'href="https://ci/job/7"' in resp.text


@pytest.mark.parametrize("tab,jenkins_job", TABS)
def test_restart_shows_error_when_jenkins_rejects(client, session, monkeypatch, tab, jenkins_job):
    _mock_jenkins(monkeypatch, httpx.Response(500))

    resp = client.post(f"/{tab}/restart", data={"build_number": "1234"})
    assert resp.status_code == 200

    job = session.exec(select(Job)).one()
    session.refresh(job)
    assert job.status == "failed"
    assert "Не удалось перезапустить сборку #1234" in resp.text
    assert 'class="launch-msg failed"' in resp.text


@pytest.mark.parametrize("tab,jenkins_job", TABS)
@pytest.mark.parametrize("value", ["abc", "", "0", "-5"])
def test_restart_rejects_invalid_build_number(client, session, tab, jenkins_job, value):
    resp = client.post(f"/{tab}/restart", data={"build_number": value})
    assert resp.status_code == 422
    assert session.exec(select(Job)).first() is None
