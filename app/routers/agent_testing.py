import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models.agent_testing import Agent, AgentTest

router = APIRouter(tags=["agent-testing"])


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


@router.post("/api/agents/{agent_id}/tests", status_code=201)
def create_agent_test(
    agent_id: int, payload: AgentTestPayload, session: Session = Depends(get_session)
) -> dict:
    agent_test = AgentTest(
        agent_id=agent_id,
        path=payload.path,
        flags_json=json.dumps([f.model_dump() for f in payload.flags]),
        fields_json=json.dumps([f.model_dump() for f in payload.fields]),
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
    agent_test.path = payload.path
    agent_test.flags_json = json.dumps([f.model_dump() for f in payload.flags])
    agent_test.fields_json = json.dumps([f.model_dump() for f in payload.fields])
    session.add(agent_test)
    session.commit()
    session.refresh(agent_test)
    return _agent_test_to_dict(agent_test)
