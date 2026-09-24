import httpx
from sqlmodel import select

from app.models.jobs import Job


def test_java_tab_renders_without_dataset_field(client):
    resp = client.get("/java")
    assert resp.status_code == 200
    assert 'hx-target="#job-log-body" hx-swap="afterbegin"' in resp.text
    assert "Java-запуск" in resp.text
    assert "Часть" in resp.text
    assert "dataset" not in resp.text.lower()
    # Java runs only go through Jenkins, which isn't tracked — no job list.
    assert 'id="job-list"' not in resp.text


def test_launch_java_creates_queued_job(client, session, monkeypatch):
    from app.execution.jenkins_launch import LaunchResult

    async def fake_launch(source, job_name, params):
        return LaunchResult(message="ok")

    # Keep the test off the network: the real hook calls Jenkins.
    monkeypatch.setattr("app.routers.jobs.launch_in_jenkins", fake_launch)

    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": 1,
            "regression_type": "regression",
            "part": "back",
        },
    )
    assert resp.status_code == 200

    job = session.exec(select(Job)).first()
    assert job.source == "java"
    assert "back" in job.params_json


def test_launch_java_jenkins_mode_triggers_build(client, session, monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/9/"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.execution.jenkins_launch.httpx.AsyncClient", lambda *a, **kw: mock_client
    )

    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": 1,
            "regression_type": "regression",
            "part": "back",
        },
    )
    assert resp.status_code == 200

    job = session.exec(select(Job)).first()
    session.refresh(job)
    assert job.status == "triggered"
    assert job.jenkins_build_id == "https://jenkins/queue/item/9/"
    # Java builds go to the Java Jenkins job, never the Python one.
    assert [r.url.path for r in requests] == ["/job/java-tests/buildWithParameters"]

    assert resp.headers["HX-Retarget"] == "#job-log-body"
    assert 'class="job-row' not in resp.text
    assert "Сборка отправлена в Jenkins" in resp.text
    assert 'href="https://jenkins/queue/item/9/"' in resp.text
    # Prepended to the log panel, so earlier replies on the page stay.
    assert resp.headers["HX-Reswap"] == "afterbegin"
    assert f"job #{job.id} · java" in resp.text


def test_launch_java_shows_error_when_jenkins_rejects(client, session, monkeypatch):
    mock_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    monkeypatch.setattr(
        "app.execution.jenkins_launch.httpx.AsyncClient", lambda *a, **kw: mock_client
    )

    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": 1,
            "regression_type": "regression",
            "part": "back",
        },
    )
    assert resp.status_code == 200

    job = session.exec(select(Job)).first()
    session.refresh(job)
    assert job.status == "failed"
    assert job.jenkins_build_id is None
    assert "Не удалось отправить запуск в Jenkins" in resp.text
    assert 'class="launch-msg failed"' in resp.text


def test_launch_java_renders_custom_launch_result(client, session, monkeypatch):
    from app.execution.jenkins_launch import LaunchResult

    calls = []

    async def fake_launch(source, job_name, params):
        calls.append((source, job_name, params))
        return LaunchResult(message="Запуск принят", url="https://ci/job/42")

    monkeypatch.setattr("app.routers.jobs.launch_in_jenkins", fake_launch)

    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": 1,
            "regression_type": "regression",
            "part": "back",
        },
    )

    assert calls == [
        (
            "java",
            "java-tests",
            {"team_id": team["id"], "stand_id": 1, "regression_type": "regression", "part": "back"},
        )
    ]
    assert "Запуск принят" in resp.text
    assert 'href="https://ci/job/42"' in resp.text
