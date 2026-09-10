def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_list_and_soft_delete_reference_item(client):
    resp = client.post("/api/references", json={"category": "team", "value": "QA-Backend"})
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    resp = client.get("/api/references", params={"category": "team"})
    assert resp.status_code == 200
    values = [item["value"] for item in resp.json()]
    assert values == ["QA-Backend"]

    dup = client.post("/api/references", json={"category": "team", "value": "QA-Backend"})
    assert dup.status_code == 409

    resp = client.delete(f"/api/references/{item_id}")
    assert resp.status_code == 204

    resp = client.get("/api/references", params={"category": "team"})
    assert resp.json() == []


def test_cascading_stand_and_test_name_fragments(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()
    other_stand = client.post("/api/references", json={"category": "stand", "value": "stage-2"}).json()

    link = client.post(
        "/api/references/team-stand-links",
        json={"team_id": team["id"], "stand_id": stand["id"]},
    )
    assert link.status_code == 204

    resp = client.get("/api/references/fragments/stands", params={"team_id": team["id"]})
    assert resp.status_code == 200
    assert "stage-1" in resp.text
    assert "stage-2" not in resp.text

    test_name = client.post(
        "/api/references",
        json={"category": "test_name", "value": "test_login_flow", "parent_id": team["id"]},
    ).json()

    resp = client.get("/api/references/fragments/test-names", params={"team_id": team["id"]})
    assert "test_login_flow" in resp.text

    dataset = client.post(
        "/api/references",
        json={"category": "dataset", "value": "dataset_default", "parent_id": test_name["id"]},
    ).json()

    resp = client.get(
        "/api/references/fragments/datasets", params={"test_name_id": test_name["id"]}
    )
    assert "dataset_default" in resp.text
