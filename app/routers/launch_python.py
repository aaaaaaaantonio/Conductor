import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.execution.runner import start_local_job_with_own_session
from app.models.jobs import Job
from app.models.reference import ReferenceItem

router = APIRouter(tags=["launch-python"])
templates = Jinja2Templates(directory="app/templates")
LOG_DIR = Path("job_logs")


@router.get("/python", response_class=HTMLResponse)
def python_tab(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    teams = list(
        session.exec(
            select(ReferenceItem).where(
                ReferenceItem.category == "team", ReferenceItem.is_active == True  # noqa: E712
            )
        ).all()
    )
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
    params = {
        "team_id": team_id,
        "stand_id": stand_id,
        "regression_type": regression_type,
        "test_name_id": test_name_id,
        "dataset_id": dataset_id,
    }
    job = Job(source="python", status="queued", params_json=json.dumps(params))
    session.add(job)
    session.commit()
    session.refresh(job)

    if execution_mode == "vm":
        command = ["echo", "python-launch", f"--team={team_id}", f"--stand={stand_id}"]
        background_tasks.add_task(start_local_job_with_own_session, job.id, command, LOG_DIR)

    from app.routers.jobs import job_list_fragment

    return job_list_fragment(request, session)
