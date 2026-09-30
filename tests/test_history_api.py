import re
from datetime import datetime, timedelta, timezone

from app.models.jobs import Job


def _job(session, source="python", status="success", created_at=None, **kw):
    job = Job(
        source=source,
        status=status,
        params_json=kw.pop("params_json", "{}"),
        created_at=created_at or datetime.now(timezone.utc),
        **kw,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _ids(html: str) -> list[int]:
    return [int(i) for i in re.findall(r'id="hist-job-(\d+)"', html)]


def test_history_page_renders_filters_and_nav(client):
    resp = client.get("/history")
    assert resp.status_code == 200
    assert 'href="/history"' in resp.text
    for name in ("source", "status", "date_from", "date_to"):
        assert f'name="{name}"' in resp.text
    assert 'hx-get="/history/fragments/list"' in resp.text


def test_history_lists_finished_jobs_newest_first(client, session):
    now = datetime.now(timezone.utc)
    older = _job(session, status="success", created_at=now - timedelta(hours=2))
    newer = _job(session, status="failed", created_at=now - timedelta(hours=1))
    running = _job(session, status="running", created_at=now)

    resp = client.get("/history")

    assert _ids(resp.text) == [running.id, newer.id, older.id]


def test_filter_by_source(client, session):
    py = _job(session, source="python")
    _job(session, source="java")
    agent = _job(session, source="agent_test")

    assert _ids(client.get("/history/fragments/list?source=python").text) == [py.id]
    assert _ids(client.get("/history/fragments/list?source=agent_test").text) == [agent.id]


def test_filter_by_status(client, session):
    _job(session, status="success")
    failed = _job(session, status="failed")

    assert _ids(client.get("/history/fragments/list?status=failed").text) == [failed.id]


def test_filter_by_date_range_in_server_local_time(client, session):
    local = datetime.now().astimezone()
    today_noon = local.replace(hour=12, minute=0, second=0, microsecond=0)
    yesterday = _job(session, created_at=(today_noon - timedelta(days=1)).astimezone(timezone.utc))
    today = _job(session, created_at=today_noon.astimezone(timezone.utc))
    d_today = today_noon.date().isoformat()
    d_yesterday = (today_noon - timedelta(days=1)).date().isoformat()

    only_today = client.get(f"/history/fragments/list?date_from={d_today}&date_to={d_today}")
    only_yesterday = client.get(f"/history/fragments/list?date_to={d_yesterday}")
    both = client.get(f"/history/fragments/list?date_from={d_yesterday}")

    assert _ids(only_today.text) == [today.id]
    assert _ids(only_yesterday.text) == [yesterday.id]
    assert _ids(both.text) == [today.id, yesterday.id]


def test_empty_filters_mean_all(client, session):
    job = _job(session)
    resp = client.get("/history/fragments/list?source=&status=&date_from=&date_to=")
    assert resp.status_code == 200
    assert _ids(resp.text) == [job.id]


def test_bad_date_is_rejected(client):
    assert client.get("/history/fragments/list?date_from=yesterday").status_code == 422


def test_no_matches_shows_empty_state(client, session):
    _job(session, source="java")
    resp = client.get("/history/fragments/list?source=python")
    assert "Ничего не найдено" in resp.text


def test_row_opens_log_and_shows_retention_note(client, session):
    job = _job(session)
    resp = client.get("/history")
    assert f'hx-get="/jobs/{job.id}/fragments/log"' in resp.text
    assert "5 дн" in resp.text


def test_jenkins_job_log_fragment_links_to_build(client, session):
    job = _job(
        session,
        source="java",
        status="triggered",
        jenkins_build_id="https://jenkins/queue/item/9/",
        params_json='{"stand_id": 3}',
    )

    resp = client.get(f"/jobs/{job.id}/fragments/log")

    assert 'href="https://jenkins/queue/item/9/"' in resp.text
    assert "stand_id" in resp.text
    assert "Лог пока пуст" not in resp.text


def test_queued_vm_job_log_is_just_empty(client, session):
    job = _job(session, status="queued")
    resp = client.get(f"/jobs/{job.id}/fragments/log")
    assert "Лог пока пуст" in resp.text
    assert "Jenkins" not in resp.text


def test_history_list_refreshes_on_job_status_with_filters(client):
    resp = client.get("/history")
    assert 'hx-trigger="change, sse:job-status"' in resp.text
    assert 'sse-connect="/jobs/stream"' in resp.text
