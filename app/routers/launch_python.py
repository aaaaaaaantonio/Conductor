import json
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app import config
from app.config import JENKINS_JOB_NAMES, PYTHON_TEST_RUNNER_PATH
from app.credentials import VM_TOKENS_MISSING, get_credentials
from app.db import get_session
from app.execution.command_builder import FieldSpec, build_command
from app.execution.jenkins_launch import restart_python
from app.execution.runner import start_local_job_with_own_session
from app.models.jobs import Job
from app.models.reference import ReferenceItem, SelectedId, active_references, launch_reference_error
from app.templating import templates

router = APIRouter(tags=["launch-python"])

PYTHON_FIELDS = [
    FieldSpec(label="Team", flag_name="--team", type="number", required=True),
    FieldSpec(label="Stand", flag_name="--stand", type="number", required=True),
    FieldSpec(label="Regression type", flag_name="--regression-type", type="text", required=True),
    FieldSpec(label="Test name", flag_name="--test-name", type="number", required=False),
    FieldSpec(label="Dataset", flag_name="--dataset", type="number", required=False),
]


@router.get("/python", response_class=HTMLResponse)
def python_tab(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    teams = active_references(session, "team")
    return templates.TemplateResponse(request, "python_tab.html", {"teams": teams})


@router.post("/python/launch", response_class=HTMLResponse)
async def python_launch(
    request: Request,
    background_tasks: BackgroundTasks,
    team_id: SelectedId = Form(None),
    stand_id: SelectedId = Form(None),
    regression_type: str = Form(...),
    execution_mode: Literal["jenkins", "vm"] = Form(...),
    test_id: SelectedId = Form(None),
    dataset_id: int | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    from app.routers.jobs import launch_refused_response

    error = launch_reference_error(session, team_id, stand_id, test_id, "python_test", dataset_id=dataset_id)
    if error:
        return launch_refused_response(request, error)
    vm_env = None
    if execution_mode == "vm":
        creds = get_credentials(request)
        vm_env = creds.vm_env() if creds else None
        if vm_env is None:
            return launch_refused_response(request, VM_TOKENS_MISSING, auth_link=True)

    test_command = session.get(ReferenceItem, test_id).command if test_id is not None else None

    params = {
        "team_id": team_id,
        "stand_id": stand_id,
        "regression_type": regression_type,
        "test_name_id": test_id,
        "test_command": test_command,
        "dataset_id": dataset_id,
    }
    # Jenkins jobs start as "triggering" rather than "queued" so they never
    # show up in the active job list (queued/running) — only VM runs do.
    status = "triggering" if execution_mode == "jenkins" else "queued"
    job = Job(source="python", status=status, params_json=json.dumps(params))
    session.add(job)
    session.commit()
    session.refresh(job)

    if execution_mode == "vm":
        values = {
            "--team": team_id,
            "--stand": stand_id,
            "--regression-type": regression_type,
            "--test-name": test_command if test_command else test_id,
            "--dataset": dataset_id,
        }
        command = build_command(PYTHON_TEST_RUNNER_PATH, PYTHON_FIELDS, values)
        background_tasks.add_task(
            start_local_job_with_own_session, job.id, command, config.JOB_LOG_DIR, env=vm_env
        )
    elif execution_mode == "jenkins":
        jenkins_params = {k: v for k, v in params.items() if v is not None}

        from app.routers.jobs import jenkins_launch_response

        return await jenkins_launch_response(
            request, session, job, JENKINS_JOB_NAMES["python"], jenkins_params
        )

    from app.routers.jobs import job_list_fragment

    response = job_list_fragment(request, session)
    if execution_mode == "vm":
        # app.js keeps the ids of jobs launched from this browser to badge the
        # tab and chime when one of them finishes.
        response.headers["HX-Trigger"] = json.dumps({"job-launched": {"id": job.id}})
    return response


@router.post("/python/restart", response_class=HTMLResponse)
async def python_restart(
    request: Request,
    build_number: int = Form(..., ge=1),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    params = {"restart_build": build_number}
    # "triggering" keeps Jenkins jobs out of the active job list (queued/running).
    job = Job(source="python", status="triggering", params_json=json.dumps(params))
    session.add(job)
    session.commit()
    session.refresh(job)

    from app.routers.jobs import jenkins_restart_response

    return await jenkins_restart_response(request, session, job, restart_python, build_number)
