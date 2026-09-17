from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models.reference import ReferenceItem, TeamStandLink

router = APIRouter(prefix="/api/references", tags=["references"])
page_router = APIRouter(tags=["references-ui"])
templates = Jinja2Templates(directory="app/templates")


class TeamStandLinkRequest(BaseModel):
    team_id: int
    stand_id: int


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
            ReferenceItem.parent_id == item.parent_id,
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


@router.post("/team-stand-links", status_code=204)
def link_team_stand(
    payload: TeamStandLinkRequest, session: Session = Depends(get_session)
) -> Response:
    session.add(TeamStandLink(team_id=payload.team_id, stand_id=payload.stand_id))
    session.commit()
    return Response(status_code=204)


@router.get("/fragments/stands", response_class=HTMLResponse)
def stand_options_fragment(
    request: Request, team_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    statement = (
        select(ReferenceItem)
        .join(TeamStandLink, TeamStandLink.stand_id == ReferenceItem.id)
        .where(
            TeamStandLink.team_id == team_id,
            ReferenceItem.category == "stand",
            ReferenceItem.is_active == True,  # noqa: E712
        )
        .order_by(ReferenceItem.sort_order, ReferenceItem.value)
    )
    stands = list(session.exec(statement).all())
    return templates.TemplateResponse(
        request, "fragments/stand_options.html", {"stands": stands}
    )


@router.get("/fragments/test-names", response_class=HTMLResponse)
def test_name_options_fragment(
    request: Request, team_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    statement = (
        select(ReferenceItem)
        .where(
            ReferenceItem.category == "test_name",
            ReferenceItem.parent_id == team_id,
            ReferenceItem.is_active == True,  # noqa: E712
        )
        .order_by(ReferenceItem.sort_order, ReferenceItem.value)
    )
    test_names = list(session.exec(statement).all())
    return templates.TemplateResponse(
        request, "fragments/test_name_options.html", {"test_names": test_names}
    )


@router.get("/fragments/datasets", response_class=HTMLResponse)
def dataset_options_fragment(
    request: Request, test_name_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    statement = (
        select(ReferenceItem)
        .where(
            ReferenceItem.category == "dataset",
            ReferenceItem.parent_id == test_name_id,
            ReferenceItem.is_active == True,  # noqa: E712
        )
        .order_by(ReferenceItem.sort_order, ReferenceItem.value)
    )
    datasets = list(session.exec(statement).all())
    return templates.TemplateResponse(
        request, "fragments/dataset_options.html", {"datasets": datasets}
    )


@page_router.get("/references", response_class=HTMLResponse)
def references_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    items = list(
        session.exec(
            select(ReferenceItem).where(ReferenceItem.is_active == True)  # noqa: E712
        ).all()
    )
    teams = [i for i in items if i.category == "team"]
    stands = [i for i in items if i.category == "stand"]
    test_names = [i for i in items if i.category == "test_name"]
    datasets = [i for i in items if i.category == "dataset"]

    team_by_id = {t.id: t for t in teams}
    test_name_by_id = {t.id: t for t in test_names}

    links = list(session.exec(select(TeamStandLink)).all())
    stand_team_names: dict[int, list[str]] = defaultdict(list)
    for link in links:
        team = team_by_id.get(link.team_id)
        if team is not None:
            stand_team_names[link.stand_id].append(team.value)

    return templates.TemplateResponse(
        request,
        "references.html",
        {
            "teams": teams,
            "stands": stands,
            "test_names": test_names,
            "datasets": datasets,
            "stand_team_names": stand_team_names,
            "team_by_id": team_by_id,
            "test_name_by_id": test_name_by_id,
        },
    )
