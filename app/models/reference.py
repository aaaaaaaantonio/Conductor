from typing import Optional

from sqlmodel import Field, SQLModel


class ReferenceItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True)
    value: str
    is_active: bool = Field(default=True)
    sort_order: int = Field(default=0)
    parent_id: Optional[int] = Field(default=None, foreign_key="referenceitem.id")


class TeamStandLink(SQLModel, table=True):
    team_id: Optional[int] = Field(
        default=None, foreign_key="referenceitem.id", primary_key=True
    )
    stand_id: Optional[int] = Field(
        default=None, foreign_key="referenceitem.id", primary_key=True
    )
