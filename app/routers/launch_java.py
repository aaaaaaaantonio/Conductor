import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.config import JENKINS_JOB_NAMES
from app.db import get_session
from app.templating import templates
from app.models.jobs import Job
from app.models.reference import ReferenceItem, active_references

router = APIRouter(tags=["launch-java"])
LOG_DIR = Path("job_logs")


@router.get("/java", response_class=HTMLResponse)
def java_tab(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    teams = active_references(session, "team")
    return templates.TemplateResponse(request, "java_tab.html", {"teams": teams})


@router.post("/java/launch", response_class=HTMLResponse)
async def java_launch(
    request: Request,
    team_id: int = Form(...),
    stand_id: int = Form(...),
    regression_type: str = Form(...),
    part: str = Form(...),
    test_name_id: int | None = Form(None),
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
        "part": part,
        "test_name_id": test_name_id,
        "test_command": test_command,
    }
    # "triggering" keeps Jenkins jobs out of the active job list (queued/running).
    job = Job(source="java", status="triggering", params_json=json.dumps(params))
    session.add(job)
    session.commit()
    session.refresh(job)

    jenkins_params = {k: v for k, v in params.items() if v is not None}

    from app.routers.jobs import jenkins_launch_response

    return await jenkins_launch_response(
        request, session, job, JENKINS_JOB_NAMES["java"], jenkins_params
    )
