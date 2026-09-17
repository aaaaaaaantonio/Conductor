import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import JAVA_TEST_RUNNER_PATH, JENKINS_BASE_URL, JENKINS_JOB_NAMES, JENKINS_POLL_INTERVAL_SECONDS
from app.db import get_session
from app.execution.command_builder import FieldSpec, build_command
from app.execution.runner import start_jenkins_job_with_own_session, start_local_job_with_own_session
from app.models.jobs import Job
from app.models.reference import ReferenceItem

router = APIRouter(tags=["launch-java"])
templates = Jinja2Templates(directory="app/templates")
LOG_DIR = Path("job_logs")

JAVA_FIELDS = [
    FieldSpec(label="Team", flag_name="--team", type="number", required=True),
    FieldSpec(label="Stand", flag_name="--stand", type="number", required=True),
    FieldSpec(label="Regression type", flag_name="--regression-type", type="text", required=True),
    FieldSpec(label="Part", flag_name="--part", type="text", required=True),
    FieldSpec(label="Test name", flag_name="--test-name", type="number", required=False),
]


@router.get("/java", response_class=HTMLResponse)
def java_tab(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    teams = list(
        session.exec(
            select(ReferenceItem).where(
                ReferenceItem.category == "team", ReferenceItem.is_active == True  # noqa: E712
            )
        ).all()
    )
    return templates.TemplateResponse(request, "java_tab.html", {"teams": teams})


@router.post("/java/launch", response_class=HTMLResponse)
async def java_launch(
    request: Request,
    background_tasks: BackgroundTasks,
    team_id: int = Form(...),
    stand_id: int = Form(...),
    regression_type: str = Form(...),
    part: str = Form(...),
    execution_mode: str = Form(...),
    test_name_id: int | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    params = {
        "team_id": team_id,
        "stand_id": stand_id,
        "regression_type": regression_type,
        "part": part,
        "test_name_id": test_name_id,
    }
    job = Job(source="java", status="queued", params_json=json.dumps(params))
    session.add(job)
    session.commit()
    session.refresh(job)

    if execution_mode == "vm":
        values = {
            "--team": team_id,
            "--stand": stand_id,
            "--regression-type": regression_type,
            "--part": part,
            "--test-name": test_name_id,
        }
        command = build_command(JAVA_TEST_RUNNER_PATH, JAVA_FIELDS, values)
        background_tasks.add_task(start_local_job_with_own_session, job.id, command, LOG_DIR)
    elif execution_mode == "jenkins":
        jenkins_params = {k: v for k, v in params.items() if v is not None}
        background_tasks.add_task(
            start_jenkins_job_with_own_session,
            job.id,
            JENKINS_BASE_URL,
            JENKINS_JOB_NAMES["java"],
            jenkins_params,
            poll_interval=JENKINS_POLL_INTERVAL_SECONDS,
        )

    from app.routers.jobs import job_list_fragment

    return job_list_fragment(request, session)
