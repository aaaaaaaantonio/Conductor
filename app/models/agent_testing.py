from typing import Optional

from sqlmodel import Field, SQLModel


class Agent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="referenceitem.id")
    name: str


class AgentTest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id")
    path: str
    flags_json: str
    fields_json: str
