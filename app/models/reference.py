from typing import Optional

from sqlmodel import Field, Session, SQLModel, select


class ReferenceItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True)
    value: str
    is_active: bool = Field(default=True)
    sort_order: int = Field(default=0)
    parent_id: Optional[int] = Field(default=None, foreign_key="referenceitem.id")
    command: Optional[str] = Field(default=None)


class TeamStandLink(SQLModel, table=True):
    team_id: Optional[int] = Field(
        default=None, foreign_key="referenceitem.id", primary_key=True
    )
    stand_id: Optional[int] = Field(
        default=None, foreign_key="referenceitem.id", primary_key=True
    )


def active_references(
    session: Session, category: str, parent_id: Optional[int] = None
) -> list[ReferenceItem]:
    statement = select(ReferenceItem).where(
        ReferenceItem.category == category, ReferenceItem.is_active == True  # noqa: E712
    )
    if parent_id is not None:
        statement = statement.where(ReferenceItem.parent_id == parent_id)
    statement = statement.order_by(ReferenceItem.sort_order, ReferenceItem.value)
    return list(session.exec(statement).all())


def sibling_references(
    session: Session, category: str, parent_id: Optional[int]
) -> list[ReferenceItem]:
    """Active items sharing a category and parent, in display order.

    Unlike active_references, a None parent_id here means "top-level items"
    (IS NULL), not "any parent".
    """
    statement = (
        select(ReferenceItem)
        .where(
            ReferenceItem.category == category,
            ReferenceItem.parent_id == parent_id,
            ReferenceItem.is_active == True,  # noqa: E712
        )
        .order_by(ReferenceItem.sort_order, ReferenceItem.value, ReferenceItem.id)
    )
    return list(session.exec(statement).all())


def next_sort_order(session: Session, category: str, parent_id: Optional[int]) -> int:
    siblings = sibling_references(session, category, parent_id)
    return max((s.sort_order for s in siblings), default=-1) + 1
