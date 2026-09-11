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
    assert response.json()["detail"] == "Agent not found"


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
