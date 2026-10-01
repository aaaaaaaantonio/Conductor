import pytest


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


def test_duplicate_test_name_allowed_across_different_parent_teams(client):
    team_a = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    team_b = client.post("/api/references", json={"category": "team", "value": "QA-Frontend"}).json()

    resp_a = client.post(
        "/api/references",
        json={"category": "test_name", "value": "test_login_flow", "parent_id": team_a["id"]},
    )
    assert resp_a.status_code == 201

    # Same value, different parent team — must not be rejected as a
    # duplicate, since test_name is scoped per-team via parent_id.
    resp_b = client.post(
        "/api/references",
        json={"category": "test_name", "value": "test_login_flow", "parent_id": team_b["id"]},
    )
    assert resp_b.status_code == 201

    # A true duplicate within the same team is still rejected.
    dup = client.post(
        "/api/references",
        json={"category": "test_name", "value": "test_login_flow", "parent_id": team_a["id"]},
    )
    assert dup.status_code == 409


def test_cascading_stand_and_test_name_fragments(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()
    client.post("/api/references", json={"category": "stand", "value": "stage-2"})

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

    client.post(
        "/api/references",
        json={"category": "dataset", "value": "dataset_default", "parent_id": test_name["id"]},
    )

    resp = client.get(
        "/api/references/fragments/datasets", params={"test_name_id": test_name["id"]}
    )
    assert "dataset_default" in resp.text


def test_pages_define_bind_persistent_in_head(client):
    # Page scripts (e.g. references.html) call window.bindPersistent inline;
    # it must be defined in <head>, before the content block, or a full page
    # load throws and no handlers get bound.
    for path in ["/references", "/python", "/java", "/agent-testing"]:
        html = client.get(path).text
        head = html.split("</head>")[0]
        assert "window.bindPersistent = function" in head, path
        assert '<aside class="sb"' in html.split("</head>")[1], path


def test_linking_same_team_and_stand_twice_is_idempotent(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()
    link = {"team_id": team["id"], "stand_id": stand["id"]}

    assert client.post("/api/references/team-stand-links", json=link).status_code == 204
    assert client.post("/api/references/team-stand-links", json=link).status_code == 204

    resp = client.get("/api/references/fragments/stands", params={"team_id": team["id"]})
    assert resp.text.count("stage-1") == 1


def test_renaming_reference_to_existing_value_returns_409(client):
    client.post("/api/references", json={"category": "team", "value": "QA-Backend"})
    other = client.post("/api/references", json={"category": "team", "value": "QA-Frontend"}).json()

    resp = client.put(f"/api/references/{other['id']}", json={"value": "QA-Backend"})
    assert resp.status_code == 409

    # Saving an item under its own current value is not a duplicate.
    resp = client.put(f"/api/references/{other['id']}", json={"value": "QA-Frontend"})
    assert resp.status_code == 200


def test_references_page_reports_errors_inline_not_via_alert(client):
    client.post("/api/references", json={"category": "team", "value": "QA"})
    html = client.get("/references").text
    assert "alert(" not in html
    assert "formError.show(form" in html
    assert "formError.showAfter(" in html


def test_duplicate_reference_error_is_in_russian(client):
    client.post("/api/references", json={"category": "team", "value": "QA"})
    resp = client.post("/api/references", json={"category": "team", "value": "QA"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Такое значение уже есть в этой категории"


def _create(client, category, value, parent_id=None):
    payload = {"category": category, "value": value, "parent_id": parent_id}
    resp = client.post("/api/references", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _values(client, category, parent_id=None):
    params = {"category": category}
    if parent_id is not None:
        params["parent_id"] = parent_id
    return [i["value"] for i in client.get("/api/references", params=params).json()]


def test_new_reference_goes_to_end_of_its_group(client):
    _create(client, "team", "Zeta")
    _create(client, "team", "Alpha")
    assert _values(client, "team") == ["Zeta", "Alpha"]


def test_move_reference_up_and_down(client):
    a = _create(client, "team", "A")
    _create(client, "team", "B")
    c = _create(client, "team", "C")

    resp = client.post(f"/api/references/{c['id']}/move", json={"direction": "up"})
    assert resp.status_code == 204
    assert _values(client, "team") == ["A", "C", "B"]

    resp = client.post(f"/api/references/{a['id']}/move", json={"direction": "down"})
    assert resp.status_code == 204
    assert _values(client, "team") == ["C", "A", "B"]


def test_move_past_the_edge_is_a_no_op(client):
    a = _create(client, "team", "A")
    b = _create(client, "team", "B")
    assert client.post(f"/api/references/{a['id']}/move", json={"direction": "up"}).status_code == 204
    assert client.post(f"/api/references/{b['id']}/move", json={"direction": "down"}).status_code == 204
    assert _values(client, "team") == ["A", "B"]


def test_move_renumbers_legacy_rows_that_all_share_sort_order_zero(client, session):
    from app.models.reference import ReferenceItem

    for value in ["C", "A", "B"]:
        session.add(ReferenceItem(category="stand", value=value, sort_order=0))
    session.commit()
    assert _values(client, "stand") == ["A", "B", "C"]

    c = next(i for i in client.get("/api/references", params={"category": "stand"}).json() if i["value"] == "C")
    client.post(f"/api/references/{c['id']}/move", json={"direction": "up"})
    assert _values(client, "stand") == ["A", "C", "B"]


def test_move_only_reorders_siblings_with_the_same_parent(client):
    team_a = _create(client, "team", "A")
    team_b = _create(client, "team", "B")
    a1 = _create(client, "test_name", "a1", team_a["id"])
    _create(client, "test_name", "a2", team_a["id"])
    _create(client, "test_name", "b1", team_b["id"])
    _create(client, "test_name", "b2", team_b["id"])

    client.post(f"/api/references/{a1['id']}/move", json={"direction": "down"})
    assert _values(client, "test_name", team_a["id"]) == ["a2", "a1"]
    assert _values(client, "test_name", team_b["id"]) == ["b1", "b2"]


def test_move_ignores_soft_deleted_siblings(client):
    _create(client, "team", "A")
    b = _create(client, "team", "B")
    c = _create(client, "team", "C")
    client.delete(f"/api/references/{b['id']}")

    client.post(f"/api/references/{c['id']}/move", json={"direction": "up"})
    assert _values(client, "team") == ["C", "A"]


def test_move_missing_or_deleted_reference_returns_404(client):
    resp = client.post("/api/references/999/move", json={"direction": "up"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Запись не найдена"

    team = _create(client, "team", "A")
    client.delete(f"/api/references/{team['id']}")
    resp = client.post(f"/api/references/{team['id']}/move", json={"direction": "up"})
    assert resp.status_code == 404


def test_move_with_unknown_direction_returns_422(client):
    team = _create(client, "team", "A")
    resp = client.post(f"/api/references/{team['id']}/move", json={"direction": "left"})
    assert resp.status_code == 422


def test_reparenting_puts_reference_at_end_of_new_group(client):
    team_a = _create(client, "team", "A")
    team_b = _create(client, "team", "B")
    moved = _create(client, "test_name", "x", team_a["id"])
    _create(client, "test_name", "b1", team_b["id"])
    _create(client, "test_name", "b2", team_b["id"])

    resp = client.put(
        f"/api/references/{moved['id']}", json={"value": "a-first", "parent_id": team_b["id"]}
    )
    assert resp.status_code == 200
    assert _values(client, "test_name", team_b["id"]) == ["b1", "b2", "a-first"]


def test_dataset_fragment_follows_custom_order(client):
    team = _create(client, "team", "T")
    test = _create(client, "test_name", "t", team["id"])
    _create(client, "dataset", "ds-1", test["id"])
    ds2 = _create(client, "dataset", "ds-2", test["id"])
    client.post(f"/api/references/{ds2['id']}/move", json={"direction": "up"})

    html = client.get("/api/references/fragments/datasets", params={"test_name_id": test["id"]}).text
    assert html.index("ds-2") < html.index("ds-1")


def test_references_page_follows_custom_order(client):
    team_a = _create(client, "team", "Alpha")
    team_z = _create(client, "team", "Zeta")
    _create(client, "stand", "s-alpha")
    s_zeta = _create(client, "stand", "s-zeta")
    _create(client, "test_name", "t-alpha", team_a["id"])
    _create(client, "test_name", "t-zeta", team_z["id"])
    t1 = _create(client, "test_name", "a-1", team_a["id"])
    _create(client, "dataset", "d-1", t1["id"])
    d2 = _create(client, "dataset", "d-2", t1["id"])

    client.post(f"/api/references/{team_z['id']}/move", json={"direction": "up"})
    client.post(f"/api/references/{s_zeta['id']}/move", json={"direction": "up"})
    client.post(f"/api/references/{t1['id']}/move", json={"direction": "up"})
    client.post(f"/api/references/{d2['id']}/move", json={"direction": "up"})

    html = client.get("/references").text
    teams_panel = html[html.index('id="panel-teams"'):html.index('id="panel-stands"')]
    assert teams_panel.index("Zeta") < teams_panel.index("Alpha")
    stands_panel = html[html.index('id="panel-stands"'):html.index('id="panel-test-names"')]
    assert stands_panel.index("s-zeta") < stands_panel.index("s-alpha")
    tests_panel = html[html.index('id="panel-test-names"'):html.index('id="panel-datasets"')]
    # Team groups follow team order; tests inside a team follow their own order.
    assert tests_panel.index(f'id="team-tests-{team_z["id"]}"') < tests_panel.index(f'id="team-tests-{team_a["id"]}"')
    assert tests_panel.index("a-1") < tests_panel.index("t-alpha")
    datasets_panel = html[html.index('id="panel-datasets"'):]
    assert datasets_panel.index("d-2") < datasets_panel.index("d-1")


def test_references_page_renders_move_buttons_with_edges_disabled(client):
    a = _create(client, "team", "A")
    b = _create(client, "team", "B")
    html = client.get("/references").text
    assert f'class="ref-move" data-move-url="/api/references/{a["id"]}/move" data-direction="up" disabled' in html
    assert f'class="ref-move" data-move-url="/api/references/{b["id"]}/move" data-direction="down" disabled' in html
    assert f'class="ref-move" data-move-url="/api/references/{a["id"]}/move" data-direction="down" title=' in html


# ---------- input validation ----------


@pytest.mark.parametrize(
    "payload",
    [
        {"category": "bogus", "value": "z"},
        {"category": "team", "value": ""},
        {"category": "team", "value": "   "},
    ],
)
def test_create_rejects_bad_category_or_blank_value(client, payload):
    assert client.post("/api/references", json=payload).status_code == 422


def test_create_strips_value(client):
    assert _create(client, "team", "  QA  ")["value"] == "QA"


def test_update_rejects_blank_value(client):
    team = _create(client, "team", "QA")
    resp = client.put(f"/api/references/{team['id']}", json={"value": " ", "parent_id": None})
    assert resp.status_code == 422


def test_item_cannot_be_its_own_parent(client):
    test_name = _create(client, "test_name", "t", _create(client, "team", "QA")["id"])
    resp = client.put(
        f"/api/references/{test_name['id']}", json={"value": "t", "parent_id": test_name["id"]}
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("category", "parent_category"),
    [
        ("test_name", "stand"),
        ("test_name", None),
        ("dataset", "team"),
        ("team", "team"),
        ("stand", "team"),
    ],
)
def test_parent_must_match_category(client, category, parent_category):
    parent_id = _create(client, parent_category, "p")["id"] if parent_category else None
    resp = client.post("/api/references", json={"category": category, "value": "x", "parent_id": parent_id})
    assert resp.status_code == 422


def test_parent_must_exist(client):
    resp = client.post("/api/references", json={"category": "test_name", "value": "x", "parent_id": 999})
    assert resp.status_code == 422


def test_soft_deleted_parent_still_accepted_for_orphans(client):
    team = _create(client, "team", "QA")
    test_name = _create(client, "test_name", "t", team["id"])
    client.delete(f"/api/references/{team['id']}")

    resp = client.put(
        f"/api/references/{test_name['id']}", json={"value": "t2", "parent_id": team["id"]}
    )

    assert resp.status_code == 200


def test_link_requires_existing_team_and_stand(client):
    team = _create(client, "team", "QA")
    stand = _create(client, "stand", "s")
    for link in ({"team_id": 999, "stand_id": stand["id"]}, {"team_id": team["id"], "stand_id": team["id"]}):
        assert client.post("/api/references/team-stand-links", json=link).status_code == 404


def test_sqlite_enforces_foreign_keys(session):
    from sqlalchemy import text

    assert session.exec(text("PRAGMA foreign_keys")).one()[0] == 1
