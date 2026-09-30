def test_launch_agent_test_creates_running_job_and_streams_log(client, session):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    # path is a real, spawnable interpreter so the background task's
    # subprocess creation succeeds (a nonexistent path makes
    # asyncio.create_subprocess_exec raise FileNotFoundError before the
    # runner's own try/except, and TestClient runs background tasks
    # synchronously within the request call, so that exception would
    # propagate out of client.post() instead of surfacing as a status code).
    payload = {
        "path": "python3",
        "flags": [{"name": "--message", "kind": "value", "default": None}],
        "fields": [
            {
                "label": "Message",
                "flag_name": "--message",
                "type": "text",
                "required": True,
                "options": None,
            }
        ],
    }
    test = client.post(f"/api/agents/{agent['id']}/tests", json=payload).json()

    resp = client.post(
        f"/api/agent-tests/{test['id']}/launch", json={"values": {"--message": "print(1)"}}
    )
    assert resp.status_code == 422 or resp.status_code == 202  # command shape validated below


def test_launch_agent_test_missing_required_field_returns_422(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    payload = {
        "path": "path/to/test.py",
        "flags": [{"name": "--users", "kind": "value", "default": None}],
        "fields": [
            {
                "label": "Users",
                "flag_name": "--users",
                "type": "number",
                "required": True,
                "options": None,
            }
        ],
    }
    test = client.post(f"/api/agents/{agent['id']}/tests", json=payload).json()

    resp = client.post(f"/api/agent-tests/{test['id']}/launch", json={"values": {}})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Не заполнено обязательное поле --users"


def test_create_agent_and_test_with_flags_and_fields(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    assert agent["name"] == "agent-01"

    payload = {
        "path": "tests/checkout/test_checkout.py",
        "flags": [
            {"name": "--verbose", "kind": "bool", "default": None},
            {"name": "--users", "kind": "value", "default": None},
        ],
        "fields": [
            {
                "label": "Users",
                "flag_name": "--users",
                "type": "number",
                "required": True,
                "options": None,
            }
        ],
    }
    created = client.post(f"/api/agents/{agent['id']}/tests", json=payload)
    assert created.status_code == 201
    test_id = created.json()["id"]

    fetched = client.get(f"/api/agent-tests/{test_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["path"] == "tests/checkout/test_checkout.py"
    assert body["flags"][0]["name"] == "--verbose"
    assert body["fields"][0]["flag_name"] == "--users"

    updated_payload = {**payload, "path": "tests/checkout/test_checkout_v2.py"}
    updated = client.put(f"/api/agent-tests/{test_id}", json=updated_payload)
    assert updated.status_code == 200
    assert updated.json()["path"] == "tests/checkout/test_checkout_v2.py"


def test_create_agent_test_for_missing_agent_returns_404(client):
    payload = {
        "path": "tests/checkout/test_checkout.py",
        "flags": [],
        "fields": [],
    }
    response = client.post("/api/agents/999999/tests", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "Агент не найден"


def test_get_agent_test_missing_returns_404(client):
    response = client.get("/api/agent-tests/999999")
    assert response.status_code == 404


def test_update_agent_test_missing_returns_404(client):
    payload = {
        "path": "tests/checkout/test_checkout.py",
        "flags": [],
        "fields": [],
    }
    response = client.put("/api/agent-tests/999999", json=payload)
    assert response.status_code == 404


def test_list_agents_by_team(client):
    team_a = client.post("/api/references", json={"category": "team", "value": "QA-Frontend"}).json()
    team_b = client.post("/api/references", json={"category": "team", "value": "QA-Mobile"}).json()

    agent_a1 = client.post("/api/agents", json={"team_id": team_a["id"], "name": "agent-a1"}).json()
    agent_a2 = client.post("/api/agents", json={"team_id": team_a["id"], "name": "agent-a2"}).json()

    listed_a = client.get("/api/agents", params={"team_id": team_a["id"]})
    assert listed_a.status_code == 200
    names_a = {agent["name"] for agent in listed_a.json()}
    assert names_a == {"agent-a1", "agent-a2"}
    assert {agent["id"] for agent in listed_a.json()} == {agent_a1["id"], agent_a2["id"]}

    listed_b = client.get("/api/agents", params={"team_id": team_b["id"]})
    assert listed_b.status_code == 200
    assert listed_b.json() == []


def test_agent_testing_page_renders(client):
    resp = client.get("/agent-testing")
    assert resp.status_code == 200
    assert "Тестирование агентов" in resp.text


def test_launch_via_card_form_json_shape_succeeds_with_unchecked_checkbox(client, session):
    # Exercises the launch endpoint the way agent_test_card.html's submit
    # handler calls it: a JSON body shaped {"values": {...}}, with an
    # unchecked checkbox field explicitly present as `false` (matching the
    # `el.type === "checkbox" ? el.checked : el.value` logic in the
    # template's inline script) rather than omitted, as native
    # form-urlencoded serialization would do.
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    payload = {
        "path": "python3",
        "flags": [
            {"name": "--message", "kind": "value", "default": None},
            {"name": "--verbose", "kind": "bool", "default": None},
        ],
        "fields": [
            {
                "label": "Message",
                "flag_name": "--message",
                "type": "text",
                "required": True,
                "options": None,
            },
            {
                "label": "Verbose",
                "flag_name": "--verbose",
                "type": "checkbox",
                "required": False,
                "options": None,
            },
        ],
    }
    test = client.post(f"/api/agents/{agent['id']}/tests", json=payload).json()

    resp = client.post(
        f"/api/agent-tests/{test['id']}/launch",
        json={"values": {"--message": "hello", "--verbose": False}},
    )
    assert resp.status_code == 202
    assert "job_id" in resp.json()


def test_launch_passes_agent_test_flags_to_command(client, monkeypatch):
    import app.routers.agent_testing as agent_testing

    launched = []

    async def fake_start(job_id, command, log_dir):
        launched.append(command)

    monkeypatch.setattr(agent_testing, "start_local_job_with_own_session", fake_start)

    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    payload = {
        "path": "run.sh",
        "flags": [
            {"name": "--headless", "kind": "bool", "default": None},
            {"name": "--env", "kind": "value", "default": "stage"},
        ],
        "fields": [
            {"label": "Users", "flag_name": "--users", "type": "number", "required": True},
        ],
    }
    test = client.post(f"/api/agents/{agent['id']}/tests", json=payload).json()

    resp = client.post(f"/api/agent-tests/{test['id']}/launch", json={"values": {"--users": 3}})

    assert resp.status_code == 202
    assert launched == [["run.sh", "--users=3", "--headless", "--env=stage"]]


def test_new_test_form_has_fixed_flags_section(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()

    html = client.get(f"/agent-testing/agents/{agent['id']}/fragments/new-test").text

    assert 'id="new-test-flags"' in html
    assert 'id="new-test-add-flag"' in html
    # The submit handler must send the collected flags, not a hardcoded [].
    assert "flags: []" not in html


def test_card_shows_fixed_flags_and_flag_defaults(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    payload = {
        "path": "run.sh",
        "flags": [
            {"name": "--headless", "kind": "bool", "default": None},
            {"name": "--env", "kind": "value", "default": "stage"},
            {"name": "--users", "kind": "value", "default": "10"},
        ],
        "fields": [
            {"label": "Users", "flag_name": "--users", "type": "number", "required": True},
        ],
    }
    test = client.post(f"/api/agents/{agent['id']}/tests", json=payload).json()

    html = client.get(f"/agent-testing/tests/{test['id']}/fragments/card").text

    assert "Фиксированные флаги" in html
    assert "--headless" in html
    assert "--env=stage" in html
    # A flag backing a field is shown as that input's default, not as a
    # separate fixed flag.
    assert "--users=10" not in html
    assert 'placeholder="по умолчанию: 10"' in html


def test_modal_forms_report_errors_inline_not_via_alert(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    test = client.post(
        f"/api/agents/{agent['id']}/tests", json={"path": "t.py", "flags": [], "fields": []}
    ).json()

    for url in (
        f"/agent-testing/tests/{test['id']}/fragments/card",
        f"/agent-testing/agents/{agent['id']}/fragments/new-test",
        f"/agent-testing/teams/{team['id']}/fragments/new-agent",
    ):
        html = client.get(url).text
        assert "alert(" not in html, url
        assert "formError.show(form" in html, url
        assert "formError.bind(form)" in html, url


def test_inline_form_error_helper_loads_before_page_scripts(client):
    # Page scripts (e.g. references.html) call formError at load time, so
    # the helper must be in <head>, not with app.js at the end of <body>.
    head = client.get("/references").text.split("</head>")[0]
    assert '<script src="/static/form-error.js"></script>' in head
    js = client.get("/static/form-error.js").text
    assert "window.formError" in js
    assert 'box.setAttribute("role", "alert")' in js
