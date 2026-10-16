
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator
from sqlmodel import Field, Session, SQLModel, select

from app.test_params import CustomParam, load_params


def blank_to_none(value: Any) -> Any:
    """An empty <select> submits "": treat it (and whitespace) as no choice."""
    return None if isinstance(value, str) and not value.strip() else value


# An id picked in a <select> that may have no options to pick from.
SelectedId = Annotated[int | None, BeforeValidator(blank_to_none)]

TestCategory = Literal["java_test", "python_test"]
Part = Literal["front", "back"]


class ReferenceItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    category: str = Field(index=True)
    value: str
    is_active: bool = Field(default=True)
    sort_order: int = Field(default=0)
    parent_id: int | None = Field(default=None, foreign_key="referenceitem.id")
    command: str | None = Field(default=None)
    # java_test only: "front" | "back".
    part: str | None = Field(default=None)
    # java_test / python_test: JSON list of CustomParam, see app/test_params.py.
    params_json: str | None = Field(default=None)


def item_params(item: ReferenceItem) -> list[CustomParam]:
    return load_params(item.params_json)


class TeamStandLink(SQLModel, table=True):
    team_id: int | None = Field(
        default=None, foreign_key="referenceitem.id", primary_key=True
    )
    stand_id: int | None = Field(
        default=None, foreign_key="referenceitem.id", primary_key=True
    )


def active_references(
    session: Session, category: str, parent_id: int | None = None
) -> list[ReferenceItem]:
    statement = select(ReferenceItem).where(
        ReferenceItem.category == category, ReferenceItem.is_active == True  # noqa: E712
    )
    if parent_id is not None:
        statement = statement.where(ReferenceItem.parent_id == parent_id)
    statement = statement.order_by(ReferenceItem.sort_order, ReferenceItem.value)
    return list(session.exec(statement).all())


def sibling_references(
    session: Session, category: str, parent_id: int | None
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


def next_sort_order(session: Session, category: str, parent_id: int | None) -> int:
    siblings = sibling_references(session, category, parent_id)
    return max((s.sort_order for s in siblings), default=-1) + 1


def launch_reference_error(
    session: Session,
    team_id: int | None,
    stand_id: int | None,
    test_id: int | None,
    test_category: TestCategory,
    part: str | None = None,
    dataset_id: int | None = None,
) -> str | None:
    """Why a launch form's selection can't be run, or None if it can: each
    id must be an active item of its category, the test must be of this
    tab's language and belong to the team (and, for Java, to the part), the
    dataset to the test. Catches stale or hand-made forms."""

    def active(item_id: int, category: str, parent_id: int | None = None) -> bool:
        item = session.get(ReferenceItem, item_id)
        return (
            item is not None
            and item.is_active
            and item.category == category
            and (parent_id is None or item.parent_id == parent_id)
        )

    if team_id is None:
        return "Выберите команду"
    if stand_id is None:
        return "Выберите стенд"
    if not active(team_id, "team"):
        return "Команда не найдена или удалена — обновите страницу"
    if not active(stand_id, "stand"):
        return "Стенд не найден или удалён — обновите страницу"
    if test_id is not None:
        if test_category == "java_test":
            test = session.get(ReferenceItem, test_id)
            if not active(test_id, "java_test", team_id) or test.part != part:
                return "Тест не найден у этой команды и части — обновите страницу"
        elif not active(test_id, "python_test", team_id):
            return "Тест не найден у этой команды — обновите страницу"
    if dataset_id is not None and (test_id is None or not active(dataset_id, "dataset", test_id)):
        return "Датасет не найден у этого теста — обновите страницу"
    return None
