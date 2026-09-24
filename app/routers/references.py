from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.templating import templates
from app.grouping import group_by
from app.models.reference import ReferenceItem, TeamStandLink, active_references

router = APIRouter(prefix="/api/references", tags=["references"])
page_router = APIRouter(tags=["references-ui"])

# Placeholders for children whose parent was soft-deleted while they're
# still active, so they stay visible/editable instead of vanishing from the
# UI (see references_page).
_ORPHAN_TEAM = ReferenceItem(category="team", value="Без команды")
_ORPHAN_TEST_NAME = ReferenceItem(category="test_name", value="Без теста")


class TeamStandLinkRequest(BaseModel):
    team_id: int
    stand_id: int


@router.get("", response_model=list[ReferenceItem])
def list_reference_items(
    category: str,
    parent_id: Optional[int] = None,
    session: Session = Depends(get_session),
) -> list[ReferenceItem]:
    return active_references(session, category, parent_id)


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


class ReferenceItemUpdateRequest(BaseModel):
    value: str
    parent_id: Optional[int] = None
    command: Optional[str] = None


@router.put("/{item_id}", response_model=ReferenceItem)
def update_reference_item(
    item_id: int, payload: ReferenceItemUpdateRequest, session: Session = Depends(get_session)
) -> ReferenceItem:
    item = session.get(ReferenceItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Not found")
    item.value = payload.value
    item.parent_id = payload.parent_id
    item.command = payload.command
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


@router.delete("/team-stand-links/{team_id}/{stand_id}", status_code=204)
def unlink_team_stand(
    team_id: int, stand_id: int, session: Session = Depends(get_session)
) -> Response:
    link = session.get(TeamStandLink, (team_id, stand_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    session.delete(link)
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

    team_by_id: dict[Optional[int], ReferenceItem] = {t.id: t for t in teams}

    links = list(session.exec(select(TeamStandLink)).all())
    stand_teams: dict[int, list[ReferenceItem]] = defaultdict(list)
    for link in links:
        team = team_by_id.get(link.team_id)
        if team is not None and link.stand_id is not None:
            stand_teams[link.stand_id].append(team)

    # Group by parent id; a test_name/dataset whose parent was soft-deleted
    # still has a real parent_id here, it just no longer matches any `team`/
    # `test_name` in the active lists above — that case is handled below by
    # bucketing it under an "orphan" placeholder instead of dropping it.
    tests_by_team_id = group_by(test_names, lambda tn: tn.parent_id)
    tests_by_team: list[tuple[ReferenceItem, list[ReferenceItem]]] = []
    matched_team_ids: set[Optional[int]] = set()
    for team in sorted(teams, key=lambda t: t.value):
        if team.id in tests_by_team_id:
            tests_by_team.append((team, tests_by_team_id[team.id]))
            matched_team_ids.add(team.id)
    orphan_tests = [
        tn
        for parent_id, tns in tests_by_team_id.items()
        if parent_id not in matched_team_ids
        for tn in tns
    ]
    if orphan_tests:
        tests_by_team.append((_ORPHAN_TEAM, orphan_tests))

    datasets_by_test_id = group_by(datasets, lambda ds: ds.parent_id)
    datasets_by_team: list[tuple[ReferenceItem, list[tuple[ReferenceItem, list[ReferenceItem]]]]] = []
    matched_test_ids: set[Optional[int]] = set()
    for team, tests in tests_by_team:
        team_tests = [
            (tn, datasets_by_test_id[tn.id]) for tn in tests if tn.id in datasets_by_test_id
        ]
        matched_test_ids.update(tn.id for tn, _ in team_tests)
        if team_tests:
            datasets_by_team.append((team, team_tests))
    orphan_datasets = [
        ds
        for parent_id, dss in datasets_by_test_id.items()
        if parent_id not in matched_test_ids
        for ds in dss
    ]
    if orphan_datasets:
        datasets_by_team.append((_ORPHAN_TEAM, [(_ORPHAN_TEST_NAME, orphan_datasets)]))

    return templates.TemplateResponse(
        request,
        "references.html",
        {
            "teams": teams,
            "stands": stands,
            "test_names": test_names,
            "stand_teams": stand_teams,
            "tests_by_team": tests_by_team,
            "datasets_by_team": datasets_by_team,
        },
    )
