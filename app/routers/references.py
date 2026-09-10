from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.db import get_session
from app.models.reference import ReferenceItem

router = APIRouter(prefix="/api/references", tags=["references"])


@router.get("", response_model=list[ReferenceItem])
def list_reference_items(
    category: str,
    parent_id: Optional[int] = None,
    session: Session = Depends(get_session),
) -> list[ReferenceItem]:
    statement = select(ReferenceItem).where(
        ReferenceItem.category == category, ReferenceItem.is_active == True  # noqa: E712
    )
    if parent_id is not None:
        statement = statement.where(ReferenceItem.parent_id == parent_id)
    statement = statement.order_by(ReferenceItem.sort_order, ReferenceItem.value)
    return list(session.exec(statement).all())


@router.post("", response_model=ReferenceItem, status_code=201)
def create_reference_item(
    item: ReferenceItem, session: Session = Depends(get_session)
) -> ReferenceItem:
    existing = session.exec(
        select(ReferenceItem).where(
            ReferenceItem.category == item.category,
            ReferenceItem.value == item.value,
            ReferenceItem.is_active == True,  # noqa: E712
        )
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Duplicate value in category")
    item.id = None
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=204)
def soft_delete_reference_item(
    item_id: int, session: Session = Depends(get_session)
) -> Response:
    item = session.get(ReferenceItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Not found")
    item.is_active = False
    session.add(item)
    session.commit()
    return Response(status_code=204)
