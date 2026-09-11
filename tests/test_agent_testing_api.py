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
