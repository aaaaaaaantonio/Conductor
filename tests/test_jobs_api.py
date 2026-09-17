import asyncio
import json

import httpx

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
    assert 'hx-trigger="htmx:afterSwap from:#test-name-select"' in resp.text
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


async def test_stream_renders_escaped_labeled_log_line_and_json_status():
    # Regression for finding 2: log-line events must render as an
    # HTML-escaped, per-job-labeled line (not raw event JSON dumped as
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
        assert "[job 7]" in chunk
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


def test_python_launch_jenkins_mode_polls_and_marks_success(client, session, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/buildWithParameters"):
            return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/5/"})
        return httpx.Response(200, json={"building": False, "result": "SUCCESS"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "app.execution.runner.httpx.AsyncClient", lambda *a, **kw: mock_client
    )
    monkeypatch.setattr("app.routers.launch_python.JENKINS_POLL_INTERVAL_SECONDS", 0)

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

    job_id = int(resp.text.split('id="job-')[1].split('"')[0])
    job = session.get(Job, job_id)
    session.refresh(job)
    assert job.status == "success"
    assert job.jenkins_build_id == "https://jenkins/queue/item/5/"


def test_startup_marks_stale_running_jobs_failed(session):
    from app.main import recover_stale_jobs
    from app.models.jobs import Job

    stale = Job(source="python", status="running", params_json="{}")
    session.add(stale)
    session.commit()
    session.refresh(stale)

    recover_stale_jobs(session)

    session.refresh(stale)
    assert stale.status == "failed"
