from app.models.jobs import Job


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
    test_type = client.post(
        "/api/references", json={"category": "test_type", "value": "Регресс"}
    ).json()

    resp = client.post(
        "/python/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "test_type_id": test_type["id"],
            "regression_type": "regression",
            "execution_mode": "vm",
        },
    )
    assert resp.status_code == 200
    assert "job-" in resp.text


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
