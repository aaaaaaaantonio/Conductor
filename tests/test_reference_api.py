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
