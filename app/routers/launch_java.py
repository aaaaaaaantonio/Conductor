import json
from typing import Literal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.config import JENKINS_JOB_NAMES
from app.db import get_session
from app.execution.jenkins_launch import restart_java
from app.models.jobs import Job
from app.models.reference import (
    Part,
    ReferenceItem,
    SelectedId,
    active_references,
    item_params,
    launch_reference_error,
)
from app.templating import templates
from app.test_params import jenkins_values

router = APIRouter(tags=["launch-java"])


@router.get("/java", response_class=HTMLResponse)
def java_tab(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    teams = active_references(session, "team")
    return templates.TemplateResponse(request, "java_tab.html", {"teams": teams})


@router.post("/java/launch", response_class=HTMLResponse)
async def java_launch(
    request: Request,
    team_id: SelectedId = Form(None),
    stand_id: SelectedId = Form(None),
    regression_type: str = Form(...),
    part: Part = Form(...),
    thread_mode: Literal["multi", "single"] = Form(...),
    test_id: SelectedId = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    from app.routers.jobs import launch_refused_response

    error = launch_reference_error(session, team_id, stand_id, test_id, "java_test", part=part)
    if error:
        return launch_refused_response(request, error)
    test = session.get(ReferenceItem, test_id) if test_id is not None else None
    test_command = test.command if test is not None else None
    test_params = item_params(test) if test is not None else []

    params = {
        "team_id": team_id,
        "stand_id": stand_id,
        "regression_type": regression_type,
        "part": part,
        "thread_mode": thread_mode,
        "test_name_id": test_id,
        "test_command": test_command,
    }
    # "triggering" keeps Jenkins jobs out of the active job list (queued/running).
    job = Job(
        source="java",
        status="triggering",
        params_json=json.dumps({**params, "test_params": [p.model_dump() for p in test_params]}),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    # Service params with no value are dropped; a test param with no value
    # goes out as a bare key.
    jenkins_params = {k: v for k, v in params.items() if v is not None} | jenkins_values(test_params)

    from app.routers.jobs import jenkins_launch_response

    return await jenkins_launch_response(
        request, session, job, JENKINS_JOB_NAMES["java"], jenkins_params
    )


@router.post("/java/restart", response_class=HTMLResponse)
async def java_restart(
    request: Request,
    build_number: int = Form(..., ge=1),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    params = {"restart_build": build_number}
    # "triggering" keeps Jenkins jobs out of the active job list (queued/running).
    job = Job(source="java", status="triggering", params_json=json.dumps(params))
    session.add(job)
    session.commit()
    session.refresh(job)

    from app.routers.jobs import jenkins_restart_response

    return await jenkins_restart_response(request, session, job, restart_java, build_number)
