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
            "execution_mode": "jenkins",
        },
    )
    assert resp.status_code == 200

    job = session.exec(select(Job)).first()
    assert job.source == "java"
    assert "back" in job.params_json


def test_launch_java_jenkins_mode_polls_and_marks_success(client, session, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/buildWithParameters"):
            return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/9/"})
        return httpx.Response(200, json={"building": False, "result": "SUCCESS"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.execution.runner.httpx.AsyncClient", lambda *a, **kw: mock_client
    )
    monkeypatch.setattr("app.routers.launch_java.JENKINS_POLL_INTERVAL_SECONDS", 0)

    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": 1,
            "regression_type": "regression",
            "part": "back",
            "execution_mode": "jenkins",
        },
    )
    assert resp.status_code == 200

    job = session.exec(select(Job)).first()
    session.refresh(job)
    assert job.status == "success"
    assert job.jenkins_build_id == "https://jenkins/queue/item/9/"
