import httpx
from sqlmodel import select

from app.models.jobs import Job


def test_java_tab_renders_without_dataset_field(client):
    resp = client.get("/java")
    assert resp.status_code == 200
    assert "Java-таб" in resp.text
    assert "Часть" in resp.text
    assert "dataset" not in resp.text.lower()


def test_launch_java_creates_queued_job(client, session):
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
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/9/"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.execution.runner.httpx.AsyncClient", lambda *a, **kw: mock_client
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
