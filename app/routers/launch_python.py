import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.config import JENKINS_JOB_NAMES, PYTHON_TEST_RUNNER_PATH
from app.db import get_session
from app.templating import templates
from app.execution.command_builder import FieldSpec, build_command
from app.execution.runner import start_local_job_with_own_session
from app.models.jobs import Job
from app.models.reference import ReferenceItem, active_references

router = APIRouter(tags=["launch-python"])
LOG_DIR = Path("job_logs")

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
    team_id: int = Form(...),
    stand_id: int = Form(...),
    regression_type: str = Form(...),
    execution_mode: str = Form(...),
    test_name_id: int | None = Form(None),
    dataset_id: int | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    test_command = None
    if test_name_id is not None:
        test_item = session.get(ReferenceItem, test_name_id)
        if test_item is not None:
            test_command = test_item.command

    params = {
        "team_id": team_id,
        "stand_id": stand_id,
        "regression_type": regression_type,
        "test_name_id": test_name_id,
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
            "--test-name": test_command if test_command else test_name_id,
            "--dataset": dataset_id,
        }
        command = build_command(PYTHON_TEST_RUNNER_PATH, PYTHON_FIELDS, values)
        background_tasks.add_task(start_local_job_with_own_session, job.id, command, LOG_DIR)
    elif execution_mode == "jenkins":
        jenkins_params = {k: v for k, v in params.items() if v is not None}

        from app.routers.jobs import jenkins_launch_response

        return await jenkins_launch_response(
            request, session, job, JENKINS_JOB_NAMES["python"], jenkins_params
        )

    from app.routers.jobs import job_list_fragment

    return job_list_fragment(request, session)
