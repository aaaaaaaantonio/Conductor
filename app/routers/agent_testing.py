import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.templating import templates
from app.execution.command_builder import FieldSpec, build_command
from app.execution.runner import start_local_job_with_own_session
from app.grouping import group_by
from app.models.agent_testing import Agent, AgentTest
from app.models.jobs import Job
from app.models.reference import ReferenceItem, active_references

router = APIRouter(tags=["agent-testing"])

LOG_DIR = Path("job_logs")


class AgentCreateRequest(BaseModel):
    team_id: int
    name: str


class FlagPayload(BaseModel):
    name: str
    kind: str
    default: Optional[str] = None


class FieldPayload(BaseModel):
    label: str
    flag_name: str
    type: str
    required: bool
    options: Optional[list[str]] = None


class AgentTestPayload(BaseModel):
    path: str
    flags: list[FlagPayload]
    fields: list[FieldPayload]


@router.post("/api/agents", response_model=Agent, status_code=201)
def create_agent(payload: AgentCreateRequest, session: Session = Depends(get_session)) -> Agent:
    agent = Agent(team_id=payload.team_id, name=payload.name)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


@router.get("/api/agents", response_model=list[Agent])
def list_agents(team_id: int, session: Session = Depends(get_session)) -> list[Agent]:
    statement = select(Agent).where(Agent.team_id == team_id)
    return list(session.exec(statement).all())


def _agent_test_to_dict(agent_test: AgentTest) -> dict:
    return {
        "id": agent_test.id,
        "agent_id": agent_test.agent_id,
        "path": agent_test.path,
        "flags": json.loads(agent_test.flags_json),
        "fields": json.loads(agent_test.fields_json),
    }


def _encode_payload(payload: AgentTestPayload) -> tuple[str, str]:
    flags_json = json.dumps([f.model_dump() for f in payload.flags])
    fields_json = json.dumps([f.model_dump() for f in payload.fields])
    return flags_json, fields_json


@router.post("/api/agents/{agent_id}/tests", status_code=201)
def create_agent_test(
    agent_id: int, payload: AgentTestPayload, session: Session = Depends(get_session)
) -> dict:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    flags_json, fields_json = _encode_payload(payload)
    agent_test = AgentTest(
        agent_id=agent_id,
        path=payload.path,
        flags_json=flags_json,
        fields_json=fields_json,
    )
    session.add(agent_test)
    session.commit()
    session.refresh(agent_test)
    return _agent_test_to_dict(agent_test)


@router.get("/api/agent-tests/{test_id}")
def get_agent_test(test_id: int, session: Session = Depends(get_session)) -> dict:
    agent_test = session.get(AgentTest, test_id)
    if agent_test is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _agent_test_to_dict(agent_test)


@router.put("/api/agent-tests/{test_id}")
def update_agent_test(
    test_id: int, payload: AgentTestPayload, session: Session = Depends(get_session)
) -> dict:
    agent_test = session.get(AgentTest, test_id)
    if agent_test is None:
        raise HTTPException(status_code=404, detail="Not found")
    flags_json, fields_json = _encode_payload(payload)
    agent_test.path = payload.path
    agent_test.flags_json = flags_json
    agent_test.fields_json = fields_json
    session.add(agent_test)
    session.commit()
    session.refresh(agent_test)
    return _agent_test_to_dict(agent_test)


class LaunchRequest(BaseModel):
    values: dict


@router.post("/api/agent-tests/{test_id}/launch", status_code=202)
async def launch_agent_test(
    test_id: int,
    payload: LaunchRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    agent_test = session.get(AgentTest, test_id)
    if agent_test is None:
        raise HTTPException(status_code=404, detail="Not found")

    fields = [FieldSpec(**f) for f in json.loads(agent_test.fields_json)]
    try:
        command = build_command(agent_test.path, fields, payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = Job(source="agent_test", status="queued", params_json=json.dumps(payload.values))
    session.add(job)
    session.commit()
    session.refresh(job)

    background_tasks.add_task(start_local_job_with_own_session, job.id, command, LOG_DIR)
    return {"job_id": job.id}


@router.get("/agent-testing", response_class=HTMLResponse)
def agent_testing_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    teams = active_references(session, "team")
    agents = list(session.exec(select(Agent)).all())
    tests = list(session.exec(select(AgentTest)).all())

    agents_by_team = group_by(agents, lambda a: a.team_id)
    tests_by_agent = group_by(tests, lambda t: t.agent_id)

    return templates.TemplateResponse(
        request,
        "agent_testing.html",
        {"teams": teams, "agents_by_team": agents_by_team, "tests_by_agent": tests_by_agent},
    )


@router.get("/agent-testing/tests/{test_id}/fragments/card", response_class=HTMLResponse)
def agent_test_card_fragment(
    request: Request, test_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    agent_test = session.get(AgentTest, test_id)
    if agent_test is None:
        raise HTTPException(status_code=404, detail="Not found")
    data = _agent_test_to_dict(agent_test)
    return templates.TemplateResponse(
        request,
        "fragments/agent_test_card.html",
        {"test": data},
    )


@router.get("/agent-testing/teams/{team_id}/fragments/new-agent", response_class=HTMLResponse)
def new_agent_fragment(
    request: Request, team_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    team = session.get(ReferenceItem, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return templates.TemplateResponse(request, "fragments/new_agent_form.html", {"team": team})


@router.get("/agent-testing/agents/{agent_id}/fragments/new-test", response_class=HTMLResponse)
def new_test_fragment(
    request: Request, agent_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return templates.TemplateResponse(request, "fragments/new_test_form.html", {"agent": agent})
