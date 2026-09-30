import asyncio
import json

import httpx
import pytest
from sqlmodel import select

from app.execution.broadcaster import broadcaster
from app.models.jobs import Job
from app.routers.jobs import stream_events


def test_job_list_fragment_shows_only_active_jobs(client, session):
    running = Job(source="python", status="running", params_json="{}")
    done = Job(source="python", status="success", params_json="{}")
    session.add(running)
    session.add(done)
    session.commit()
    session.refresh(running)
    session.refresh(done)

    resp = client.get("/jobs/fragments/list")
    assert resp.status_code == 200
    assert f"job-{running.id}" in resp.text
    assert f"job-{done.id}" not in resp.text


def test_job_list_fragment_has_no_oob_swap_or_wrapper_div(client, session):
    # Regression for the OOB-swap bug: the fragment used to be a top-level
    # <div id="job-list" hx-swap-oob="true">, which HTMX would splice in via
    # outerHTML on the very first `load` fetch, clobbering the live page
    # div's own hx-get/hx-trigger attributes and permanently killing the
    # sse:job-status subscription. The fragment must now be bare content
    # only, swapped into the page's #job-list div via hx-swap="innerHTML".
    running = Job(source="python", status="running", params_json="{}")
    session.add(running)
    session.commit()
    session.refresh(running)

    resp = client.get("/jobs/fragments/list")
    assert resp.status_code == 200
    assert "hx-swap-oob" not in resp.text
    assert 'id="job-list"' not in resp.text


def test_python_tab_job_list_div_has_load_and_sse_trigger(client):
    # The page's live #job-list div must declare hx-get/hx-trigger itself —
    # these must never be reintroduced by (and thus dependent on) a fragment
    # swap, since the fragment now carries no wrapper element at all.
    resp = client.get("/python")
    assert resp.status_code == 200
    assert '<div id="job-list" hx-get="/jobs/fragments/list" hx-trigger="load, sse:job-status" hx-swap="innerHTML">' in resp.text


def test_python_tab_cascading_selects_carry_corrected_triggers(client):
    # Regression for finding 4: stand-select and test-name-select must fire
    # on initial `load` (not just on a later team change), and dataset-select
    # must cascade off test-name-select's swap event rather than a `change`
    # event that a programmatic option-swap never fires.
    resp = client.get("/python")
    assert resp.status_code == 200
    assert 'id="stand-select"' in resp.text
    assert 'hx-trigger="load, change from:#team-select"' in resp.text
    assert 'id="test-name-select"' in resp.text
    assert 'id="dataset-select"' in resp.text
    assert 'hx-trigger="htmx:afterSwap from:#test-name-select, change from:#test-name-select"' in resp.text
    assert 'hx-trigger="change from:#team-select"' not in resp.text
    assert 'hx-trigger="change from:#test-name-select"' not in resp.text


def test_python_launch_response_has_no_oob_wrapper(client, session):
    # The launch response fragment must match the same shape as the
    # periodic SSE-triggered refresh (finding 1): no OOB wrapper, so the
    # page's #job-list div (targeted with hx-swap="innerHTML") keeps its
    # own hx-get/hx-trigger attributes after a launch too.
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()

    resp = client.post(
        "/python/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "execution_mode": "vm",
        },
    )
    assert resp.status_code == 200
    assert "hx-swap-oob" not in resp.text
    assert 'id="job-list"' not in resp.text
    assert "Сборка отправлена в Jenkins" not in resp.text


async def test_stream_renders_escaped_job_tagged_log_line_and_json_status():
    # Regression for finding 2: log-line events must render as an
    # HTML-escaped line tagged with its job (not raw event JSON dumped as
    # text), while job-status events keep their JSON payload for the
    # job-list refresh trigger.
    response = await stream_events()
    gen = response.body_iterator
    try:
        await broadcaster.publish(
            {"type": "log-line", "job_id": 7, "line": "<b>hi</b> & bye"}
        )
        chunk = await asyncio.wait_for(gen.__anext__(), timeout=1)
        assert "event: log-line" in chunk
        assert 'data-job="7"' in chunk
        assert "&lt;b&gt;hi&lt;/b&gt; &amp; bye" in chunk
        assert "<b>hi</b>" not in chunk
        assert '"type"' not in chunk

        status_event = {"type": "job-status", "job_id": 7, "status": "success"}
        await broadcaster.publish(status_event)
        chunk2 = await asyncio.wait_for(gen.__anext__(), timeout=1)
        assert "event: job-status" in chunk2
        assert json.dumps(status_event) in chunk2
    finally:
        await gen.aclose()


def test_job_log_fragment_returns_log_contents(client, session, tmp_path):
    log_file = tmp_path / "job-1.log"
    log_file.write_text("line one\nline two\n")
    job = Job(source="python", status="running", params_json="{}", log_path=str(log_file))
    session.add(job)
    session.commit()
    session.refresh(job)

    resp = client.get(f"/jobs/{job.id}/fragments/log")
    assert resp.status_code == 200
    assert "line one" in resp.text
    assert "line two" in resp.text


def test_python_launch_vm_mode_creates_job_and_returns_list_fragment(client, session):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()

    resp = client.post(
        "/python/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "execution_mode": "vm",
        },
    )
    assert resp.status_code == 200
    assert "job-" in resp.text


def test_python_launch_jenkins_mode_triggers_build(client, session, monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/5/"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.execution.jenkins_launch.httpx.AsyncClient", lambda *a, **kw: mock_client
    )

    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()

    resp = client.post(
        "/python/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "execution_mode": "jenkins",
        },
    )
    assert resp.status_code == 200

    job = session.exec(select(Job)).one()
    session.refresh(job)
    assert job.status == "triggered"
    assert job.jenkins_build_id == "https://jenkins/queue/item/5/"
    # Python builds go to the Python Jenkins job, never the Java one.
    assert [r.url.path for r in requests] == ["/job/python-tests/buildWithParameters"]

    # The reply replaces the log panel instead of the #job-list.
    assert resp.headers["HX-Retarget"] == "#job-log-body"
    assert 'class="job-row' not in resp.text
    assert "Сборка отправлена в Jenkins" in resp.text
    assert 'href="https://jenkins/queue/item/5/"' in resp.text


def test_startup_marks_stale_running_jobs_failed(session):
    from app.main import recover_stale_jobs
    from app.models.jobs import Job

    stale = Job(source="python", status="running", params_json="{}")
    stale_trigger = Job(source="java", status="triggering", params_json="{}")
    session.add(stale)
    session.add(stale_trigger)
    session.commit()
    session.refresh(stale)
    session.refresh(stale_trigger)

    recover_stale_jobs(session)

    session.refresh(stale)
    session.refresh(stale_trigger)
    assert stale.status == "failed"
    assert stale_trigger.status == "failed"



def test_python_launch_rejects_unknown_execution_mode(client, session):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()

    resp = client.post(
        "/python/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "regression_type": "regression",
            "execution_mode": "bogus",
        },
    )

    assert resp.status_code == 422
    # No job may be left behind stuck in "queued" (the active job list).
    assert session.exec(select(Job)).all() == []


def test_job_updated_at_changes_on_update(session):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)
    created_updated_at = job.updated_at

    job.status = "running"
    session.add(job)
    session.commit()
    session.refresh(job)

    assert job.updated_at > created_updated_at


def _job(session, status, **kw):
    job = Job(source="python", status=status, params_json="{}", **kw)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_cancel_queued_job_marks_cancelled_without_process(client, session):
    job = _job(session, "queued")

    resp = client.post(f"/jobs/{job.id}/cancel")

    assert resp.status_code == 200
    session.refresh(job)
    assert job.status == "cancelled"
    assert "cancelled" in resp.text
    assert "Остановить" not in resp.text


def test_cancel_running_job_kills_its_process(client, session, monkeypatch):
    job = _job(session, "running")
    calls = []

    def fake_cancel(job_id):
        calls.append(job_id)
        # What the runner does once the killed process exits.
        job.status = "cancelled"
        session.add(job)
        session.commit()
        return True

    monkeypatch.setattr("app.routers.jobs.cancel_job", fake_cancel)

    resp = client.post(f"/jobs/{job.id}/cancel")

    assert resp.status_code == 200
    assert calls == [job.id]
    assert "Остановить" not in resp.text


def test_running_job_without_process_is_marked_cancelled(client, session, monkeypatch):
    # e.g. the process already exited but the row wasn't updated yet, or a
    # stale "running" row: nothing to kill, still honour the stop.
    job = _job(session, "running")
    monkeypatch.setattr("app.routers.jobs.cancel_job", lambda job_id: False)

    client.post(f"/jobs/{job.id}/cancel")

    session.refresh(job)
    assert job.status == "cancelled"


@pytest.mark.parametrize("status", ["success", "failed", "cancelled", "triggered", "triggering"])
def test_cannot_cancel_finished_or_jenkins_jobs(client, session, status):
    job = _job(session, status)
    resp = client.post(f"/jobs/{job.id}/cancel")
    assert resp.status_code == 409
    session.refresh(job)
    assert job.status == status


def test_cancel_missing_job_is_404(client):
    assert client.post("/jobs/999/cancel").status_code == 404


@pytest.mark.parametrize("status,shown", [("running", True), ("queued", True), ("success", False)])
def test_log_panel_shows_stop_button_only_for_active_jobs(client, session, status, shown):
    job = _job(session, status)
    html = client.get(f"/jobs/{job.id}/fragments/log").text
    assert (f'hx-post="/jobs/{job.id}/cancel"' in html) is shown


def test_history_offers_cancelled_status_filter(client):
    assert '<option value="cancelled"' in client.get("/history").text
