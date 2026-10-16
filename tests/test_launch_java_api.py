import json

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

    async def fake_launch(source, job_name, params, creds):
        return LaunchResult(message="ok")

    # Keep the test off the network: the real hook calls Jenkins.
    monkeypatch.setattr("app.routers.jobs.launch_in_jenkins", fake_launch)

    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "part": "back", "thread_mode": "multi",
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
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "part": "back", "thread_mode": "multi",
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
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "part": "back", "thread_mode": "multi",
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

    async def fake_launch(source, job_name, params, creds):
        calls.append((source, job_name, params))
        return LaunchResult(message="Запуск принят", url="https://ci/job/42")

    monkeypatch.setattr("app.routers.jobs.launch_in_jenkins", fake_launch)

    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "part": "back", "thread_mode": "multi",
        },
    )

    assert calls == [
        (
            "java",
            "java-tests",
            {"team_id": team["id"], "stand_id": stand["id"], "regression_type": "regression",
             "part": "back", "thread_mode": "multi"},
        )
    ]
    assert "Запуск принят" in resp.text
    assert 'href="https://ci/job/42"' in resp.text


def test_launch_forms_opt_into_remembering_values(client):
    assert 'data-remember="java-launch"' in client.get("/java").text
    assert 'data-remember="python-launch"' in client.get("/python").text
    # The restart forms keep nothing: a build number is one-off.
    assert client.get("/java").text.count("data-remember") == 1


def test_python_datasets_reload_when_test_name_changes(client):
    html = client.get("/python").text
    assert 'hx-trigger="htmx:afterSwap from:#test-name-select, change from:#test-name-select"' in html


def test_app_js_restores_remembered_form_values(client):
    js = client.get("/static/app.js").text
    assert "form[data-remember]" in js
    assert "localStorage" in js


def test_dependent_selects_replace_their_options(client):
    # The Java launch form sets hx-swap="afterbegin" for its reply feed; the
    # dependent selects inherit hx-swap, so without their own they'd prepend
    # new options and keep the previous team's stands and tests.
    for tab in ("java", "python"):
        html = client.get(f"/{tab}").text
        selects = html.split('hx-target="this"')[1:]
        assert selects, tab
        for rest in selects:
            assert rest.lstrip().startswith('hx-swap="innerHTML"'), tab


def test_java_launch_rejects_unknown_stand(client, session, monkeypatch):
    calls = []

    async def fake_launch(*args):
        calls.append(args)

    monkeypatch.setattr("app.routers.jobs.launch_in_jenkins", fake_launch)
    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()

    resp = client.post(
        "/java/launch",
        data={"team_id": team["id"], "stand_id": 999, "regression_type": "regression",
             "part": "back", "thread_mode": "multi"},
    )

    assert resp.status_code == 200
    assert resp.headers["HX-Retarget"] == "#job-log-body"
    assert "не найден" in resp.text
    assert calls == []
    assert session.exec(select(Job)).all() == []


def test_java_launch_rejects_test_name_of_another_team(client, session):
    team = client.post("/api/references", json={"category": "team", "value": "QA"}).json()
    other = client.post("/api/references", json={"category": "team", "value": "Other"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "s"}).json()
    test = client.post(
        "/api/references", json={"category": "java_test", "value": "t", "parent_id": other["id"], "part": "back"}
    ).json()

    resp = client.post(
        "/java/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "part": "back", "thread_mode": "multi",
            "test_id": test["id"],
        },
    )

    assert "не найден" in resp.text
    assert session.exec(select(Job)).all() == []


def test_java_launch_with_empty_stand_is_refused_readably(client, session):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Java"}).json()

    resp = client.post(
        "/java/launch",
        data={"team_id": team["id"], "stand_id": "", "regression_type": "regression",
             "part": "back", "thread_mode": "multi"},
    )

    assert resp.status_code == 200
    assert resp.headers["HX-Retarget"] == "#job-log-body"
    assert "Выберите стенд" in resp.text
    assert session.exec(select(Job)).all() == []


def _mock_jenkins(monkeypatch) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/9/"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.execution.jenkins_launch.httpx.AsyncClient", lambda *a, **kw: mock_client
    )
    return requests


def _java_refs(client, part="back", params=None):
    team = client.post("/api/references", json={"category": "team", "value": "QA"}).json()["id"]
    stand = client.post("/api/references", json={"category": "stand", "value": "s"}).json()["id"]
    test = client.post(
        "/api/references",
        json={"category": "java_test", "value": "t", "parent_id": team, "part": part,
              "command": "mvn test", "params": params or []},
    ).json()["id"]
    return team, stand, test


def test_java_launch_sends_thread_mode_and_test_params_to_jenkins(client, session, monkeypatch):
    requests = _mock_jenkins(monkeypatch)
    params = [
        {"key": "retry", "type": "bool", "value": "true"},
        {"key": "env", "type": "text", "value": "a b"},
        {"key": "headless", "type": "flag", "value": None},
    ]
    team, stand, test = _java_refs(client, params=params)

    resp = client.post(
        "/java/launch",
        data={"team_id": team, "stand_id": stand, "regression_type": "regression",
              "part": "back", "thread_mode": "single", "test_id": test},
    )

    assert resp.status_code == 200
    assert requests[0].url.query.decode() == (
        f"team_id={team}&stand_id={stand}&regression_type=regression&part=back&thread_mode=single"
        f"&test_name_id={test}&test_command=mvn%20test&retry=true&env=a%20b&headless"
    )
    job = session.exec(select(Job)).first()
    recorded = json.loads(job.params_json)
    assert recorded["thread_mode"] == "single"
    assert recorded["test_params"] == params


def test_java_launch_refuses_test_of_other_part(client, session):
    team, stand, test = _java_refs(client, part="front")

    resp = client.post(
        "/java/launch",
        data={"team_id": team, "stand_id": stand, "regression_type": "regression",
              "part": "back", "thread_mode": "multi", "test_id": test},
    )

    assert "Тест не найден у этой команды и части" in resp.text
    assert session.exec(select(Job)).all() == []


def test_java_launch_refuses_python_test(client, session):
    team, stand, _ = _java_refs(client)
    py = client.post(
        "/api/references", json={"category": "python_test", "value": "p", "parent_id": team}
    ).json()["id"]

    resp = client.post(
        "/java/launch",
        data={"team_id": team, "stand_id": stand, "regression_type": "regression",
              "part": "back", "thread_mode": "multi", "test_id": py},
    )

    assert "Тест не найден у этой команды и части" in resp.text
    assert session.exec(select(Job)).all() == []


def test_java_launch_rejects_unknown_thread_mode(client, session):
    team, stand, _ = _java_refs(client)

    resp = client.post(
        "/java/launch",
        data={"team_id": team, "stand_id": stand, "regression_type": "regression",
              "part": "back", "thread_mode": "fast"},
    )

    assert resp.status_code == 422
    assert session.exec(select(Job)).all() == []


def test_java_tab_has_thread_mode_and_part_aware_test_select(client):
    html = client.get("/java").text
    assert 'name="thread_mode"' in html
    assert "Многопоточный" in html
    assert "Однопоточный" in html
    assert 'hx-get="/api/references/fragments/java-tests"' in html
    assert 'name="test_id"' in html
    assert "change from:#j-part-select" in html
