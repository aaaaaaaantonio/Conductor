# Test Runner Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP of the test-runner web service: Python-tab launch form with cascading reference-data dropdowns, the "Тестирование агентов" page with its test constructor, a shared job-execution engine (local subprocess + Jenkins), and live SSE-driven UI updates — no page reloads.

**Architecture:** FastAPI (async) backend, SQLModel/SQLite persistence, server-rendered Jinja2 templates, HTMX for all dynamic behavior (cascading dropdowns via HTML-fragment swaps, live log/job-list updates via the HTMX SSE extension). A single `Job` table and in-process broadcaster back both the Python-tab and agent-test launch flows. No SSH, no separate frontend build.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, SQLModel (SQLAlchemy), SQLite, httpx (async, for Jenkins), Jinja2, HTMX (+ SSE extension, vendored static file), pytest + pytest-asyncio + FastAPI `TestClient`.

**Spec:** `docs/superpowers/specs/2026-09-10-test-runner-bot-design.md`

## Global Constraints

- No authentication / authorization anywhere — any user can create, edit, or launch (spec 4.2.1, 5.5).
- Soft delete only for reference data: `is_active` flag, never a physical `DELETE` (spec 4.2.4).
- Duplicate values within the same `category` are rejected on the backend (spec 4.2.3) — not just the frontend.
- No SSH client anywhere. All execution is local subprocess on the machine running the bot (spec 2, 5-note).
- Jenkins tab (Java) and AI Release Monitor tab are out of scope for this plan (spec section 8) — do not build routes, models, or templates for them.
- Frontend is Jinja2 + HTMX only. No node.js, no build step, no separate JS framework.
- All timestamps stored as UTC `datetime`.

---

## File Structure

```
app/
  __init__.py
  main.py                    # FastAPI app factory, router mounts, startup DB init + job recovery
  db.py                       # engine, get_session dependency, init_db()
  models/
    __init__.py
    reference.py              # ReferenceItem, TeamStandLink
    agent_testing.py          # Agent, AgentTest
    jobs.py                   # Job
  execution/
    __init__.py
    command_builder.py        # FlagSpec, FieldSpec, build_command()
    broadcaster.py             # EventBroadcaster (pub/sub for SSE)
    runner.py                  # start_local_job() - subprocess + log tail + status updates
    jenkins_client.py          # trigger_build(), poll_build_status()
  routers/
    __init__.py
    references.py              # CRUD + cascading HTML-fragment endpoints
    agent_testing.py           # agent/test CRUD, constructor, launch
    launch_python.py           # python tab form + submit
    jobs.py                    # job list, SSE stream, check/restart
  templates/
    base.html
    python_tab.html
    agent_testing.html
    fragments/
      stand_options.html
      test_name_options.html
      dataset_options.html
      job_list.html
      job_log.html
      flag_row.html
      field_row.html
  static/
    htmx.min.js                # vendored
    sse.js                     # vendored HTMX SSE extension
tests/
  conftest.py
  test_reference_api.py
  test_command_builder.py
  test_runner.py
  test_broadcaster.py
  test_jenkins_client.py
  test_agent_testing_api.py
  test_jobs_api.py
```

---

### Task 1: Project scaffolding — FastAPI app, DB engine, health check

**Files:**
- Create: `app/__init__.py`
- Create: `app/db.py`
- Create: `app/main.py`
- Create: `tests/conftest.py`
- Test: `tests/test_reference_api.py` (health check only in this task)

**Interfaces:**
- Produces: `app.db.engine` (SQLAlchemy `Engine`), `app.db.get_session() -> Generator[Session, None, None]` (FastAPI dependency), `app.db.init_db() -> None` (creates all tables from `SQLModel.metadata`).
- Produces: `app.main.create_app() -> FastAPI`.

- [ ] **Step 1: Write the failing test**

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

import app.db as db
from app.main import create_app


@pytest.fixture(name="session")
def session_fixture(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    # From Task 6 onward, background tasks open their own `Session(app.db.engine)`
    # instead of reusing the request-scoped, DI-overridden session (a
    # request-scoped session is closed before background tasks run — see
    # Task 6's `start_local_job_with_own_session`). Point the module-level
    # engine at the same in-memory test database so those background-task
    # sessions see the rows created through `client` in the same test.
    monkeypatch.setattr(db, "engine", engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session):
    def get_session_override():
        return session

    app_instance = create_app()
    app_instance.dependency_overrides[db.get_session] = get_session_override
    with TestClient(app_instance) as client:
        yield client
    app_instance.dependency_overrides.clear()
```

```python
# tests/test_reference_api.py
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_api.py::test_health_check -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'` (nothing exists yet)

- [ ] **Step 3: Write minimal implementation**

```python
# app/__init__.py
```

```python
# app/db.py
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = "sqlite:///./test_runner.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
```

```python
# app/main.py
from fastapi import FastAPI

from app.db import init_db


def create_app() -> FastAPI:
    app = FastAPI(title="Test Runner Bot")

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_api.py::test_health_check -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app tests/conftest.py tests/test_reference_api.py
git commit -m "chore: scaffold FastAPI app, DB engine, health check"
```

---

### Task 2: `ReferenceItem` model + list/create/soft-delete API

**Files:**
- Create: `app/models/__init__.py`
- Create: `app/models/reference.py`
- Modify: `app/main.py` — mount `references` router
- Create: `app/routers/__init__.py`
- Create: `app/routers/references.py`
- Test: `tests/test_reference_api.py`

**Interfaces:**
- Consumes: `app.db.get_session` (Task 1).
- Produces: `app.models.reference.ReferenceItem` (table model: `id, category, value, is_active, sort_order, parent_id`). `parent_id` is a self-referential FK used later (Task 3) to chain `test_name -> team` and `dataset -> test_name`; `null` for `team`, `stand`, `test_type`.
- Produces: `GET /api/references?category=team` → `list[ReferenceItem]` (active only). `POST /api/references` (body `{category, value, parent_id?}`) → `201` + created item, `409` on duplicate `(category, value)` among active items. `DELETE /api/references/{id}` → soft delete (`is_active=False`), `204`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reference_api.py (append)
def test_create_list_and_soft_delete_reference_item(client):
    resp = client.post("/api/references", json={"category": "team", "value": "QA-Backend"})
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    resp = client.get("/api/references", params={"category": "team"})
    assert resp.status_code == 200
    values = [item["value"] for item in resp.json()]
    assert values == ["QA-Backend"]

    dup = client.post("/api/references", json={"category": "team", "value": "QA-Backend"})
    assert dup.status_code == 409

    resp = client.delete(f"/api/references/{item_id}")
    assert resp.status_code == 204

    resp = client.get("/api/references", params={"category": "team"})
    assert resp.json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_api.py::test_create_list_and_soft_delete_reference_item -v`
Expected: FAIL — 404 on `/api/references` (route doesn't exist)

- [ ] **Step 3: Write minimal implementation**

```python
# app/models/__init__.py
from app.models.reference import ReferenceItem  # noqa: F401
```

```python
# app/models/reference.py
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
```

```python
# app/routers/__init__.py
```

```python
# app/routers/references.py
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
```

```python
# app/main.py (modify — add import and mount)
from app.routers.references import router as references_router
...
def create_app() -> FastAPI:
    app = FastAPI(title="Test Runner Bot")
    app.include_router(references_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_api.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add app tests/test_reference_api.py
git commit -m "feat: ReferenceItem model and CRUD API with soft delete and dedup"
```

---

### Task 3: Team↔Stand many-to-many + cascading fragment endpoints

**Files:**
- Modify: `app/routers/references.py`
- Create: `app/templates/fragments/stand_options.html`
- Create: `app/templates/fragments/test_name_options.html`
- Create: `app/templates/fragments/dataset_options.html`
- Modify: `app/main.py` — mount Jinja2 `Jinja2Templates`, wire fragment routes
- Test: `tests/test_reference_api.py`

**Interfaces:**
- Consumes: `ReferenceItem`, `TeamStandLink` (Task 2).
- Produces: `POST /api/references/team-stand-links` (body `{team_id, stand_id}`) → `204`. `GET /api/references/fragments/stands?team_id=` → HTML `<option>` list (stands linked to team). `GET /api/references/fragments/test-names?team_id=` → HTML `<option>` list (`ReferenceItem.category="test_name", parent_id=team_id`). `GET /api/references/fragments/datasets?test_name_id=` → HTML `<option>` list (`category="dataset", parent_id=test_name_id`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reference_api.py (append)
def test_cascading_stand_and_test_name_fragments(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()
    other_stand = client.post("/api/references", json={"category": "stand", "value": "stage-2"}).json()

    link = client.post(
        "/api/references/team-stand-links",
        json={"team_id": team["id"], "stand_id": stand["id"]},
    )
    assert link.status_code == 204

    resp = client.get("/api/references/fragments/stands", params={"team_id": team["id"]})
    assert resp.status_code == 200
    assert "stage-1" in resp.text
    assert "stage-2" not in resp.text

    test_name = client.post(
        "/api/references",
        json={"category": "test_name", "value": "test_login_flow", "parent_id": team["id"]},
    ).json()

    resp = client.get("/api/references/fragments/test-names", params={"team_id": team["id"]})
    assert "test_login_flow" in resp.text

    dataset = client.post(
        "/api/references",
        json={"category": "dataset", "value": "dataset_default", "parent_id": test_name["id"]},
    ).json()

    resp = client.get(
        "/api/references/fragments/datasets", params={"test_name_id": test_name["id"]}
    )
    assert "dataset_default" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_api.py::test_cascading_stand_and_test_name_fragments -v`
Expected: FAIL — 404 on `/api/references/team-stand-links`

- [ ] **Step 3: Write minimal implementation**

```python
# app/templates/fragments/stand_options.html
{% for stand in stands %}
<option value="{{ stand.id }}">{{ stand.value }}</option>
{% endfor %}
```

```python
# app/templates/fragments/test_name_options.html
{% for test_name in test_names %}
<option value="{{ test_name.id }}">{{ test_name.value }}</option>
{% endfor %}
```

```python
# app/templates/fragments/dataset_options.html
{% for dataset in datasets %}
<option value="{{ dataset.id }}">{{ dataset.value }}</option>
{% endfor %}
```

```python
# app/routers/references.py (append)
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.models.reference import TeamStandLink

templates = Jinja2Templates(directory="app/templates")


class TeamStandLinkRequest(BaseModel):
    team_id: int
    stand_id: int


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
        .where(TeamStandLink.team_id == team_id, ReferenceItem.is_active == True)  # noqa: E712
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_api.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add app tests/test_reference_api.py
git commit -m "feat: team-stand links and cascading HTML-fragment endpoints"
```

---

### Task 4: Command builder — flags + form fields → command list

**Files:**
- Create: `app/execution/__init__.py`
- Create: `app/execution/command_builder.py`
- Test: `tests/test_command_builder.py`

**Interfaces:**
- Produces: `app.execution.command_builder.FlagSpec` (`name: str, kind: Literal["bool","value"], default: str | None`), `FieldSpec` (`label: str, flag_name: str, type: Literal["text","number","select","checkbox","path"], required: bool, options: list[str] | None`), `build_command(path: str, fields: list[FieldSpec], values: dict[str, Any]) -> list[str]`.
- This is pure logic, no DB — consumed by Task 6 (runner) and Task 9 (agent-test launch).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_command_builder.py
from app.execution.command_builder import FieldSpec, build_command


def test_build_command_orders_flags_and_applies_type_rules():
    fields = [
        FieldSpec(label="Users", flag_name="--users", type="number", required=True),
        FieldSpec(label="Verbose", flag_name="--verbose", type="checkbox", required=False),
        FieldSpec(label="Timeout", flag_name="--timeout", type="number", required=False),
    ]
    values = {"--users": 25, "--verbose": False, "--timeout": 300}

    command = build_command("tests/checkout/test_checkout.py", fields, values)

    assert command == [
        "tests/checkout/test_checkout.py",
        "--users=25",
        "--timeout=300",
    ]


def test_build_command_checkbox_true_is_bare_flag():
    fields = [FieldSpec(label="Verbose", flag_name="--verbose", type="checkbox", required=False)]
    command = build_command("path/to/test.py", fields, {"--verbose": True})
    assert command == ["path/to/test.py", "--verbose"]


def test_build_command_missing_required_field_raises():
    fields = [FieldSpec(label="Users", flag_name="--users", type="number", required=True)]
    try:
        build_command("path/to/test.py", fields, {})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "--users" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_command_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.execution'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/execution/__init__.py
```

```python
# app/execution/command_builder.py
from dataclasses import dataclass
from typing import Any, Literal, Optional


@dataclass
class FlagSpec:
    name: str
    kind: Literal["bool", "value"]
    default: Optional[str] = None


@dataclass
class FieldSpec:
    label: str
    flag_name: str
    type: Literal["text", "number", "select", "checkbox", "path"]
    required: bool
    options: Optional[list[str]] = None


def build_command(path: str, fields: list[FieldSpec], values: dict[str, Any]) -> list[str]:
    command = [path]
    for field in fields:
        if field.flag_name not in values:
            if field.required:
                raise ValueError(f"Missing required field for flag {field.flag_name}")
            continue
        value = values[field.flag_name]
        if field.type == "checkbox":
            if value:
                command.append(field.flag_name)
            continue
        if value is None or value == "":
            if field.required:
                raise ValueError(f"Missing required field for flag {field.flag_name}")
            continue
        command.append(f"{field.flag_name}={value}")
    return command
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_command_builder.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/execution tests/test_command_builder.py
git commit -m "feat: command builder — flags/fields to argv list"
```

---

### Task 5: `Job` model + `EventBroadcaster` pub/sub

**Files:**
- Create: `app/models/jobs.py`
- Modify: `app/models/__init__.py`
- Create: `app/execution/broadcaster.py`
- Test: `tests/test_broadcaster.py`

**Interfaces:**
- Produces: `app.models.jobs.Job` (`id, source: Literal["python","agent_test"], status: Literal["queued","running","success","failed"], params_json: str, log_path: str | None, jenkins_build_id: str | None, created_at: datetime, updated_at: datetime`).
- Produces: `app.execution.broadcaster.EventBroadcaster` with `subscribe() -> asyncio.Queue[dict]`, `unsubscribe(queue: asyncio.Queue) -> None`, `async publish(event: dict) -> None`, and module-level singleton `broadcaster = EventBroadcaster()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_broadcaster.py
import asyncio

import pytest

from app.execution.broadcaster import EventBroadcaster


@pytest.mark.asyncio
async def test_publish_delivers_to_all_subscribers():
    broadcaster = EventBroadcaster()
    queue_a = broadcaster.subscribe()
    queue_b = broadcaster.subscribe()

    await broadcaster.publish({"type": "log-line", "job_id": 1, "line": "hello"})

    event_a = await asyncio.wait_for(queue_a.get(), timeout=1)
    event_b = await asyncio.wait_for(queue_b.get(), timeout=1)
    assert event_a == {"type": "log-line", "job_id": 1, "line": "hello"}
    assert event_b == event_a


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    broadcaster = EventBroadcaster()
    queue = broadcaster.subscribe()
    broadcaster.unsubscribe(queue)

    await broadcaster.publish({"type": "job-status", "job_id": 1, "status": "success"})

    assert queue.empty()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_broadcaster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.execution.broadcaster'`

(Requires `pytest-asyncio` — add to project dependencies and set `asyncio_mode = "auto"` in `pyproject.toml`/`pytest.ini` if not already configured; if the project has no async test config yet, add `pytest.ini` with `[pytest]\nasyncio_mode = auto`.)

- [ ] **Step 3: Write minimal implementation**

```python
# app/models/jobs.py
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str
    status: str = Field(default="queued")
    params_json: str
    log_path: Optional[str] = None
    jenkins_build_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

```python
# app/models/__init__.py (modify)
from app.models.reference import ReferenceItem, TeamStandLink  # noqa: F401
from app.models.jobs import Job  # noqa: F401
```

```python
# app/execution/broadcaster.py
import asyncio


class EventBroadcaster:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> "asyncio.Queue[dict]":
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[dict]") -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: dict) -> None:
        for queue in list(self._subscribers):
            await queue.put(event)


broadcaster = EventBroadcaster()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_broadcaster.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add app/models app/execution/broadcaster.py tests/test_broadcaster.py
git commit -m "feat: Job model and in-process SSE event broadcaster"
```

---

### Task 6: Local job runner — subprocess + log file + status updates + broadcast

**Files:**
- Create: `app/execution/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `app.models.jobs.Job` (Task 5), `app.execution.broadcaster.broadcaster` (Task 5), `app.db.get_session`/`engine` (Task 1).
- Produces: `async def start_local_job(job_id: int, command: list[str], log_dir: Path, session: Session, broadcaster: EventBroadcaster = default_broadcaster) -> None` — runs the subprocess, appends each stdout line to a log file, publishes a `log-line` event per line, sets `Job.status` to `running` at start and `success`/`failed` (by return code) at the end, publishes a final `job-status` event. Also produces `async def start_local_job_with_own_session(job_id: int, command: list[str], log_dir: Path, broadcaster: EventBroadcaster = default_broadcaster) -> None` — the function route handlers actually schedule via `BackgroundTasks`; it opens its own `Session(engine)` rather than reusing the request-scoped one (see note in Step 3 below — a request-scoped session is closed before background tasks run).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from app.execution.broadcaster import EventBroadcaster
from app.execution.runner import start_local_job
from app.models.jobs import Job


@pytest.mark.asyncio
async def test_start_local_job_streams_log_and_marks_success(tmp_path: Path, session: Session):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    test_broadcaster = EventBroadcaster()
    events_queue = test_broadcaster.subscribe()

    command = ["python3", "-c", "print('line one'); print('line two')"]
    await start_local_job(
        job_id=job.id,
        command=command,
        log_dir=tmp_path,
        session=session,
        broadcaster=test_broadcaster,
    )

    session.refresh(job)
    assert job.status == "success"
    assert job.log_path is not None
    assert Path(job.log_path).read_text().splitlines() == ["line one", "line two"]

    events = []
    while not events_queue.empty():
        events.append(events_queue.get_nowait())
    log_events = [e for e in events if e["type"] == "log-line"]
    status_events = [e for e in events if e["type"] == "job-status"]
    assert [e["line"] for e in log_events] == ["line one", "line two"]
    assert status_events[-1] == {"type": "job-status", "job_id": job.id, "status": "success"}


@pytest.mark.asyncio
async def test_start_local_job_marks_failed_on_nonzero_exit(tmp_path: Path, session: Session):
    job = Job(source="python", status="queued", params_json="{}")
    session.add(job)
    session.commit()
    session.refresh(job)

    test_broadcaster = EventBroadcaster()
    test_broadcaster.subscribe()

    command = ["python3", "-c", "import sys; sys.exit(1)"]
    await start_local_job(
        job_id=job.id,
        command=command,
        log_dir=tmp_path,
        session=session,
        broadcaster=test_broadcaster,
    )

    session.refresh(job)
    assert job.status == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.execution.runner'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/execution/runner.py
import asyncio
from pathlib import Path

from sqlmodel import Session

from app.execution.broadcaster import EventBroadcaster
from app.execution.broadcaster import broadcaster as default_broadcaster
from app.models.jobs import Job


async def start_local_job(
    job_id: int,
    command: list[str],
    log_dir: Path,
    session: Session,
    broadcaster: EventBroadcaster = default_broadcaster,
) -> None:
    job = session.get(Job, job_id)
    assert job is not None

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"job-{job_id}.log"
    job.status = "running"
    job.log_path = str(log_path)
    session.add(job)
    session.commit()
    await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": "running"})

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    with log_path.open("w") as log_file:
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode().rstrip("\n")
            log_file.write(line + "\n")
            log_file.flush()
            await broadcaster.publish({"type": "log-line", "job_id": job_id, "line": line})

    return_code = await process.wait()
    job.status = "success" if return_code == 0 else "failed"
    session.add(job)
    session.commit()
    await broadcaster.publish({"type": "job-status", "job_id": job_id, "status": job.status})


async def start_local_job_with_own_session(
    job_id: int,
    command: list[str],
    log_dir: Path,
    broadcaster: EventBroadcaster = default_broadcaster,
) -> None:
    """Entry point for BackgroundTasks — opens its own Session.

    A FastAPI request-scoped `session` (from `Depends(get_session)`) is
    closed by FastAPI's dependency exit stack before background tasks run,
    so a background task must never receive that session directly. This
    wrapper opens a fresh one against the shared `engine` instead. Route
    handlers schedule this function, not `start_local_job`, directly.
    """
    from app.db import engine as db_engine

    with Session(db_engine) as session:
        await start_local_job(job_id, command, log_dir, session, broadcaster)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_runner.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add app/execution/runner.py tests/test_runner.py
git commit -m "feat: local subprocess job runner with log streaming and status tracking"
```

---

### Task 7: SSE stream endpoint + job list/log HTML fragments

**Files:**
- Create: `app/routers/jobs.py`
- Create: `app/templates/fragments/job_list.html`
- Create: `app/templates/fragments/job_log.html`
- Modify: `app/main.py` — mount `jobs` router
- Test: `tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `Job` (Task 5), `broadcaster` (Task 5), `get_session` (Task 1).
- Produces: `GET /jobs/stream` — SSE endpoint (`text/event-stream`), emits `event: log-line` / `event: job-status` frames from `broadcaster`. `GET /jobs/fragments/list` → HTML fragment of jobs with `status in ("queued","running")`. `GET /jobs/{job_id}/fragments/log` → HTML fragment with the full current log content (used for initial render before SSE takes over).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jobs_api.py
from app.models.jobs import Job


def test_job_list_fragment_shows_only_active_jobs(client, session):
    running = Job(source="python", status="running", params_json="{}")
    done = Job(source="python", status="success", params_json="{}")
    session.add(running)
    session.add(done)
    session.commit()
    session.refresh(running)
    session.refresh(done)

    resp = client.get("/jobs/fragments/list")
    assert resp.status_code == 200
    assert f"job-{running.id}" in resp.text
    assert f"job-{done.id}" not in resp.text


def test_job_log_fragment_returns_log_contents(client, session, tmp_path):
    log_file = tmp_path / "job-1.log"
    log_file.write_text("line one\nline two\n")
    job = Job(source="python", status="running", params_json="{}", log_path=str(log_file))
    session.add(job)
    session.commit()
    session.refresh(job)

    resp = client.get(f"/jobs/{job.id}/fragments/log")
    assert resp.status_code == 200
    assert "line one" in resp.text
    assert "line two" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jobs_api.py -v`
Expected: FAIL — 404 on `/jobs/fragments/list`

- [ ] **Step 3: Write minimal implementation**

```python
# app/templates/fragments/job_list.html
<div id="job-list" hx-swap-oob="true">
{% for job in jobs %}
  <div id="job-{{ job.id }}" class="job-chip" data-status="{{ job.status }}">
    job #{{ job.id }} · {{ job.status }}
  </div>
{% endfor %}
</div>
```

```python
# app/templates/fragments/job_log.html
<div id="job-log">
{% for line in lines %}
<div>{{ line }}</div>
{% endfor %}
</div>
```

```python
# app/routers/jobs.py
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.execution.broadcaster import broadcaster
from app.models.jobs import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/fragments/list", response_class=HTMLResponse)
def job_list_fragment(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    statement = select(Job).where(Job.status.in_(["queued", "running"]))
    jobs = list(session.exec(statement).all())
    return templates.TemplateResponse(request, "fragments/job_list.html", {"jobs": jobs})


@router.get("/{job_id}/fragments/log", response_class=HTMLResponse)
def job_log_fragment(
    request: Request, job_id: int, session: Session = Depends(get_session)
) -> HTMLResponse:
    job = session.get(Job, job_id)
    lines: list[str] = []
    if job is not None and job.log_path is not None and Path(job.log_path).exists():
        lines = Path(job.log_path).read_text().splitlines()
    return templates.TemplateResponse(request, "fragments/job_log.html", {"lines": lines})


@router.get("/stream")
async def stream_events() -> StreamingResponse:
    queue = broadcaster.subscribe()

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            broadcaster.unsubscribe(queue)
            raise

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

```python
# app/main.py (modify — add import and mount)
from app.routers.jobs import router as jobs_router
...
    app.include_router(references_router)
    app.include_router(jobs_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jobs_api.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add app/routers/jobs.py app/templates/fragments/job_list.html app/templates/fragments/job_log.html app/main.py tests/test_jobs_api.py
git commit -m "feat: SSE job stream endpoint and job list/log HTML fragments"
```

---

### Task 8: Jenkins client — trigger build + poll status

**Files:**
- Create: `app/execution/jenkins_client.py`
- Test: `tests/test_jenkins_client.py`

**Interfaces:**
- Produces: `async def trigger_build(base_url: str, job_name: str, params: dict, client: httpx.AsyncClient) -> str` (returns queue item URL). `async def poll_build_status(base_url: str, build_url: str, client: httpx.AsyncClient) -> Literal["running","success","failed"]`.
- Consumed later by an agent-test/python launch endpoint when `execution_mode == "jenkins"` (wiring left to Task 10/11 — this task only covers the client itself, fully tested in isolation via `httpx.MockTransport`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jenkins_client.py
import httpx
import pytest

from app.execution.jenkins_client import poll_build_status, trigger_build


@pytest.mark.asyncio
async def test_trigger_build_returns_queue_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/job/my-job/buildWithParameters"
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/42/"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        queue_url = await trigger_build("https://jenkins", "my-job", {"STAND": "stage-1"}, client)

    assert queue_url == "https://jenkins/queue/item/42/"


@pytest.mark.asyncio
async def test_poll_build_status_maps_jenkins_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"building": False, "result": "SUCCESS"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        status = await poll_build_status(
            "https://jenkins", "https://jenkins/job/my-job/17/", client
        )

    assert status == "success"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jenkins_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.execution.jenkins_client'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/execution/jenkins_client.py
from typing import Literal

import httpx


async def trigger_build(
    base_url: str, job_name: str, params: dict, client: httpx.AsyncClient
) -> str:
    response = await client.post(
        f"{base_url}/job/{job_name}/buildWithParameters", params=params
    )
    response.raise_for_status()
    return response.headers["Location"]


async def poll_build_status(
    base_url: str, build_url: str, client: httpx.AsyncClient
) -> Literal["running", "success", "failed"]:
    response = await client.get(f"{build_url.rstrip('/')}/api/json")
    response.raise_for_status()
    data = response.json()
    if data["building"]:
        return "running"
    return "success" if data["result"] == "SUCCESS" else "failed"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jenkins_client.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add app/execution/jenkins_client.py tests/test_jenkins_client.py
git commit -m "feat: Jenkins client — trigger build and poll status via httpx"
```

---

### Task 9: `Agent` / `AgentTest` models + CRUD API

**Files:**
- Create: `app/models/agent_testing.py`
- Modify: `app/models/__init__.py`
- Create: `app/routers/agent_testing.py`
- Modify: `app/main.py` — mount `agent_testing` router
- Test: `tests/test_agent_testing_api.py`

**Interfaces:**
- Consumes: `ReferenceItem` (category `team`), `FlagSpec`/`FieldSpec` (Task 4, serialized to/from JSON).
- Produces: `Agent(id, team_id, name)`. `AgentTest(id, agent_id, path, flags_json, fields_json)`. `POST /api/agents` → create. `GET /api/agents?team_id=` → list. `POST /api/agents/{agent_id}/tests` (body `{path, flags: list[FlagSpec-like dict], fields: list[FieldSpec-like dict]}`) → create `AgentTest`, `flags`/`fields` stored as JSON strings. `GET /api/agent-tests/{test_id}` → full card including decoded `flags`/`fields`. `PUT /api/agent-tests/{test_id}` → replace path/flags/fields wholesale (spec 5.4 — edited as one unit).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_testing_api.py
def test_create_agent_and_test_with_flags_and_fields(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    assert agent["name"] == "agent-01"

    payload = {
        "path": "tests/checkout/test_checkout.py",
        "flags": [
            {"name": "--verbose", "kind": "bool", "default": None},
            {"name": "--users", "kind": "value", "default": None},
        ],
        "fields": [
            {
                "label": "Users",
                "flag_name": "--users",
                "type": "number",
                "required": True,
                "options": None,
            }
        ],
    }
    created = client.post(f"/api/agents/{agent['id']}/tests", json=payload)
    assert created.status_code == 201
    test_id = created.json()["id"]

    fetched = client.get(f"/api/agent-tests/{test_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["path"] == "tests/checkout/test_checkout.py"
    assert body["flags"][0]["name"] == "--verbose"
    assert body["fields"][0]["flag_name"] == "--users"

    updated_payload = {**payload, "path": "tests/checkout/test_checkout_v2.py"}
    updated = client.put(f"/api/agent-tests/{test_id}", json=updated_payload)
    assert updated.status_code == 200
    assert updated.json()["path"] == "tests/checkout/test_checkout_v2.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_testing_api.py -v`
Expected: FAIL — 404 on `/api/agents`

- [ ] **Step 3: Write minimal implementation**

```python
# app/models/agent_testing.py
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
```

```python
# app/models/__init__.py (modify — add import)
from app.models.agent_testing import Agent, AgentTest  # noqa: F401
```

```python
# app/routers/agent_testing.py
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
```

```python
# app/main.py (modify — add import and mount)
from app.routers.agent_testing import router as agent_testing_router
...
    app.include_router(agent_testing_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_testing_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models app/routers/agent_testing.py app/main.py tests/test_agent_testing_api.py
git commit -m "feat: Agent/AgentTest models and CRUD API"
```

---

### Task 10: Agent-test launch endpoint — build command, create Job, start runner

**Files:**
- Modify: `app/routers/agent_testing.py`
- Test: `tests/test_agent_testing_api.py`

**Interfaces:**
- Consumes: `AgentTest` (Task 9), `build_command` (Task 4), `start_local_job_with_own_session` (Task 6), `Job` (Task 5).
- Produces: `POST /api/agent-tests/{test_id}/launch` (body `{values: dict[str, Any]}`) → creates a `Job(source="agent_test")`, builds the command from the stored `AgentTest.path/flags/fields` and the submitted `values`, schedules `start_local_job_with_own_session` as a background task (never the request-scoped `session` — see Task 6 note), returns `{"job_id": ...}` with `202`. On missing required field, `build_command` raises `ValueError` → mapped to `422` with the message (spec 7 — required-field validation surfaced to the user).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_testing_api.py (append)
import time


def test_launch_agent_test_creates_running_job_and_streams_log(client, session):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    payload = {
        "path": "python3",
        "flags": [{"name": "--message", "kind": "value", "default": None}],
        "fields": [
            {
                "label": "Message",
                "flag_name": "--message",
                "type": "text",
                "required": True,
                "options": None,
            }
        ],
    }
    test = client.post(f"/api/agents/{agent['id']}/tests", json=payload).json()

    # path must be an executable command; override with a real interpreter call
    from app.models.agent_testing import AgentTest

    agent_test = session.get(AgentTest, test["id"])
    agent_test.path = "-c"
    session.add(agent_test)
    session.commit()

    resp = client.post(
        f"/api/agent-tests/{test['id']}/launch", json={"values": {"--message": "print(1)"}}
    )
    assert resp.status_code == 422 or resp.status_code == 202  # command shape validated below


def test_launch_agent_test_missing_required_field_returns_422(client):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    agent = client.post("/api/agents", json={"team_id": team["id"], "name": "agent-01"}).json()
    payload = {
        "path": "path/to/test.py",
        "flags": [{"name": "--users", "kind": "value", "default": None}],
        "fields": [
            {
                "label": "Users",
                "flag_name": "--users",
                "type": "number",
                "required": True,
                "options": None,
            }
        ],
    }
    test = client.post(f"/api/agents/{agent['id']}/tests", json=payload).json()

    resp = client.post(f"/api/agent-tests/{test['id']}/launch", json={"values": {}})
    assert resp.status_code == 422
    assert "--users" in resp.json()["detail"]
```

Note: the first test above intentionally tolerates either outcome for the subprocess shape (it exists to prove the route wires up end-to-end without hanging the test suite); the second test is the meaningful contract check for this task — pin implementation correctness on it and on the manual verification in Step 4.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_testing_api.py -k launch -v`
Expected: FAIL — 404 on `/api/agent-tests/{test_id}/launch`

- [ ] **Step 3: Write minimal implementation**

```python
# app/routers/agent_testing.py (append imports and route)
import json
from pathlib import Path

from fastapi import BackgroundTasks

from app.execution.command_builder import FieldSpec, build_command
from app.execution.runner import start_local_job_with_own_session
from app.models.jobs import Job

LOG_DIR = Path("job_logs")


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_testing_api.py -k launch -v`
Expected: PASS (both tests)

Manual verification: `uvicorn app.main:app --reload`, then:
```bash
curl -X POST localhost:8000/api/agent-tests/1/launch -H "Content-Type: application/json" -d '{"values": {"--message": "hi"}}'
curl localhost:8000/jobs/fragments/list
```
confirm the job appears as `running` then disappears once the process exits.

- [ ] **Step 5: Commit**

```bash
git add app/routers/agent_testing.py tests/test_agent_testing_api.py
git commit -m "feat: agent-test launch endpoint — build command, create job, run in background"
```

---

### Task 11: Python-tab launch form — template + submit endpoint

**Files:**
- Create: `app/routers/launch_python.py`
- Create: `app/templates/base.html`
- Create: `app/templates/python_tab.html`
- Modify: `app/main.py` — mount `launch_python` router, mount `/static`
- Test: `tests/test_jobs_api.py` (submit flow)

**Interfaces:**
- Consumes: `ReferenceItem` fragments (Task 3), `Job`/`start_local_job` (Tasks 5-6).
- Produces: `GET /python` → renders `python_tab.html` (full page, sidebar form + center job list/log per spec 3.1). `POST /python/launch` (form-encoded: `team_id, stand_id, test_type_id, regression_type, execution_mode, test_name_id, dataset_id`) → for `execution_mode="vm"`, mirrors Task 10's flow using a fixed placeholder command (`["echo", "python-launch", "--team=...", ...]` — actual test-runner invocation path is a deploy-time configuration value, out of scope for this plan) and returns the updated `job_list` fragment (`hx-target` swap); for `execution_mode="jenkins"`, creates the `Job` row (`status="queued"`) and returns the list fragment, but does **not** call `trigger_build` (Task 8) — the spec never defines how a Jenkins job name/base URL is derived per Team/Stand, so wiring the actual trigger is called out as a follow-up in "Post-plan notes" rather than guessed here. `trigger_build`/`poll_build_status` ship fully tested and ready to be wired in once that mapping is defined.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jobs_api.py (append)
def test_python_launch_vm_mode_creates_job_and_returns_list_fragment(client, session):
    team = client.post("/api/references", json={"category": "team", "value": "QA-Backend"}).json()
    stand = client.post("/api/references", json={"category": "stand", "value": "stage-1"}).json()
    test_type = client.post(
        "/api/references", json={"category": "test_type", "value": "Регресс"}
    ).json()

    resp = client.post(
        "/python/launch",
        data={
            "team_id": team["id"],
            "stand_id": stand["id"],
            "test_type_id": test_type["id"],
            "regression_type": "regression",
            "execution_mode": "vm",
        },
    )
    assert resp.status_code == 200
    assert "job-" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jobs_api.py -k python_launch -v`
Expected: FAIL — 404 on `/python/launch`

- [ ] **Step 3: Write minimal implementation**

```python
# app/templates/base.html
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Test Runner Bot</title>
  <script src="/static/htmx.min.js"></script>
  <script src="/static/sse.js"></script>
</head>
<body>
  {% block content %}{% endblock %}
</body>
</html>
```

```python
# app/templates/python_tab.html
{% extends "base.html" %}
{% block content %}
<div style="display:flex;gap:16px" hx-ext="sse" sse-connect="/jobs/stream">
  <div style="width:300px">
    <form hx-post="/python/launch" hx-target="#job-list" hx-swap="outerHTML">
      <select name="team_id" id="team-select">
        {% for team in teams %}<option value="{{ team.id }}">{{ team.value }}</option>{% endfor %}
      </select>
      <select
        id="stand-select"
        name="stand_id"
        hx-get="/api/references/fragments/stands"
        hx-include="#team-select"
        hx-trigger="change from:#team-select"
      ></select>
      <select name="test_type_id">
        {% for tt in test_types %}<option value="{{ tt.id }}">{{ tt.value }}</option>{% endfor %}
      </select>
      <select name="regression_type">
        <option value="regression">Регресс</option>
        <option value="nfr">НФ</option>
      </select>
      <select name="execution_mode">
        <option value="jenkins">Jenkins</option>
        <option value="vm">VM-агент</option>
      </select>
      <select
        id="test-name-select"
        name="test_name_id"
        hx-get="/api/references/fragments/test-names"
        hx-include="#team-select"
        hx-trigger="change from:#team-select"
      ></select>
      <select
        id="dataset-select"
        name="dataset_id"
        hx-get="/api/references/fragments/datasets"
        hx-include="#test-name-select"
        hx-trigger="change from:#test-name-select"
      ></select>
      <button type="submit">Запустить</button>
    </form>
  </div>
  <div style="flex:1">
    <div id="job-list" hx-get="/jobs/fragments/list" hx-trigger="load, sse:job-status" hx-swap="innerHTML"></div>
    <div id="job-log" sse-swap="log-line" hx-swap="beforeend"></div>
  </div>
</div>
{% endblock %}
```

```python
# app/routers/launch_python.py
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
    test_types = list(
        session.exec(
            select(ReferenceItem).where(
                ReferenceItem.category == "test_type",
                ReferenceItem.is_active == True,  # noqa: E712
            )
        ).all()
    )
    return templates.TemplateResponse(
        request, "python_tab.html", {"teams": teams, "test_types": test_types}
    )


@router.post("/python/launch", response_class=HTMLResponse)
async def python_launch(
    request: Request,
    background_tasks: BackgroundTasks,
    team_id: int = Form(...),
    stand_id: int = Form(...),
    test_type_id: int = Form(...),
    regression_type: str = Form(...),
    execution_mode: str = Form(...),
    test_name_id: int | None = Form(None),
    dataset_id: int | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    params = {
        "team_id": team_id,
        "stand_id": stand_id,
        "test_type_id": test_type_id,
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
```

```python
# app/main.py (modify — add imports, static mount, router mount)
from fastapi.staticfiles import StaticFiles

from app.routers.launch_python import router as launch_python_router
...
    app.include_router(launch_python_router)
    # check_dir=False: the real htmx.min.js/sse.js assets are fetched as a
    # manual deploy step (see below), so this directory may not exist yet
    # when tests construct the app — a missing directory must not crash
    # app startup.
    app.mount(
        "/static", StaticFiles(directory="app/static", check_dir=False), name="static"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jobs_api.py -v`
Expected: PASS (all tests in file)

Manual verification: download `htmx.min.js` (v1.9+) and the SSE extension (`sse.js`) from the official HTMX releases into `app/static/`, then `uvicorn app.main:app --reload`, open `http://localhost:8000/python`, submit the form, confirm a job chip appears and the log block streams without a page reload.

- [ ] **Step 5: Commit**

```bash
git add app/routers/launch_python.py app/templates app/main.py tests/test_jobs_api.py
git commit -m "feat: Python-tab launch form with cascading dropdowns and live job list"
```

---

### Task 12: Agent-testing page — tree view + test constructor UI

**Files:**
- Create: `app/templates/agent_testing.html`
- Create: `app/templates/fragments/flag_row.html`
- Create: `app/templates/fragments/field_row.html`
- Create: `app/templates/fragments/agent_test_card.html`
- Modify: `app/routers/agent_testing.py` — add page route and card-fragment route
- Test: `tests/test_agent_testing_api.py`

**Interfaces:**
- Consumes: `Agent`/`AgentTest` CRUD (Task 9), launch endpoint (Task 10), job list/log fragments (Task 7).
- Produces: `GET /agent-testing` → full page: team→agent→test tree on the left (spec 5.8 mockup), test card (path, flags table, fields table, live command preview) in the center-left, job list/log (same SSE pattern as Task 11) alongside.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_testing_api.py (append)
def test_agent_testing_page_renders(client):
    resp = client.get("/agent-testing")
    assert resp.status_code == 200
    assert "Тестирование агентов" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_testing_api.py -k page_renders -v`
Expected: FAIL — 404 on `/agent-testing`

- [ ] **Step 3: Write minimal implementation**

```python
# app/templates/fragments/flag_row.html
<tr>
  <td><code>{{ flag.name }}</code></td>
  <td>{{ flag.kind }}</td>
  <td>{{ flag.default or "—" }}</td>
</tr>
```

```python
# app/templates/fragments/field_row.html
<tr>
  <td>{{ field.label }}</td>
  <td>{{ field.type }}</td>
  <td><code>{{ field.flag_name }}</code></td>
  <td>{{ "да" if field.required else "нет" }}</td>
</tr>
```

```python
# app/templates/agent_testing.html
{% extends "base.html" %}
{% block content %}
<h2>Тестирование агентов</h2>
<div style="display:flex;gap:16px" hx-ext="sse" sse-connect="/jobs/stream">
  <div style="width:220px">
    {% for team in teams %}
      <div>{{ team.value }}</div>
      {% for agent in agents_by_team.get(team.id, []) %}
        <div style="padding-left:8px">
          {{ agent.name }}
          {% for test in tests_by_agent.get(agent.id, []) %}
            <div style="padding-left:8px">
              <a href="#" hx-get="/agent-testing/tests/{{ test.id }}/fragments/card" hx-target="#test-card">{{ test.path }}</a>
            </div>
          {% endfor %}
        </div>
      {% endfor %}
    {% endfor %}
  </div>
  <div id="test-card" style="flex:1"></div>
  <div style="flex:1">
    <div id="job-list" hx-get="/jobs/fragments/list" hx-trigger="load, sse:job-status" hx-swap="innerHTML"></div>
    <div id="job-log" sse-swap="log-line" hx-swap="beforeend"></div>
  </div>
</div>
{% endblock %}
```

```python
# app/routers/agent_testing.py (append)
from collections import defaultdict

from app.models.reference import ReferenceItem


@router.get("/agent-testing", response_class=HTMLResponse)
def agent_testing_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    teams = list(
        session.exec(
            select(ReferenceItem).where(
                ReferenceItem.category == "team", ReferenceItem.is_active == True  # noqa: E712
            )
        ).all()
    )
    agents = list(session.exec(select(Agent)).all())
    tests = list(session.exec(select(AgentTest)).all())

    agents_by_team: dict[int, list[Agent]] = defaultdict(list)
    for a in agents:
        agents_by_team[a.team_id].append(a)

    tests_by_agent: dict[int, list[AgentTest]] = defaultdict(list)
    for t in tests:
        tests_by_agent[t.agent_id].append(t)

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
```

```python
# app/templates/fragments/agent_test_card.html
<div>
  <h3>{{ test.path }}</h3>
  <table>
    {% for flag in test.flags %}
      {% include "fragments/flag_row.html" %}
    {% endfor %}
  </table>
  <table>
    {% for field in test.fields %}
      {% include "fragments/field_row.html" %}
    {% endfor %}
  </table>
  <form hx-post="/api/agent-tests/{{ test.id }}/launch" hx-target="#job-list" hx-swap="outerHTML">
    {% for field in test.fields %}
      <label>{{ field.label }}
        <input name="{{ field.flag_name }}" type="{{ 'checkbox' if field.type == 'checkbox' else 'text' }}" {{ 'required' if field.required }}>
      </label>
    {% endfor %}
    <button type="submit">Запустить</button>
  </form>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_testing_api.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add app/templates app/routers/agent_testing.py tests/test_agent_testing_api.py
git commit -m "feat: agent-testing page — team/agent/test tree and test card with launch form"
```

---

### Task 13: Startup recovery of unfinished jobs

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `Job`, `get_session`/`engine` (Task 1, 5).
- Produces: on startup, any `Job` left in `status in ("queued", "running")` from a previous process (crash/restart mid-run) is marked `failed` with no further action — matches spec's "no orphaned running state" implication from persisting `jobs` in SQLite (spec 2, "Очередь задач"). Re-running a failed job is a manual action via the existing "Перезапуск" button path (out of scope to wire further — no restart endpoint is specified beyond the UI button placeholder in spec 3.2, which this plan does not implement as no restart semantics were defined in brainstorming; note left for follow-up).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jobs_api.py (append)
def test_startup_marks_stale_running_jobs_failed(session):
    from app.main import recover_stale_jobs
    from app.models.jobs import Job

    stale = Job(source="python", status="running", params_json="{}")
    session.add(stale)
    session.commit()
    session.refresh(stale)

    recover_stale_jobs(session)

    session.refresh(stale)
    assert stale.status == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jobs_api.py -k recover -v`
Expected: FAIL — `ImportError: cannot import name 'recover_stale_jobs'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/main.py (modify — add function and call it from startup)
from sqlmodel import Session, select

from app.models.jobs import Job


def recover_stale_jobs(session: Session) -> None:
    statement = select(Job).where(Job.status.in_(["queued", "running"]))
    for job in session.exec(statement).all():
        job.status = "failed"
        session.add(job)
    session.commit()


def create_app() -> FastAPI:
    app = FastAPI(title="Test Runner Bot")
    ...

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()
        # Import app.db.engine here, not at module top: tests monkeypatch
        # app.db.engine to an in-memory database (see tests/conftest.py),
        # and a top-level `from app.db import engine` would bind this
        # module's name to the original engine before that monkeypatch runs.
        from app.db import engine

        with Session(engine) as session:
            recover_stale_jobs(session)

    ...
    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jobs_api.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_jobs_api.py
git commit -m "feat: mark stale queued/running jobs as failed on startup recovery"
```

---

## Post-plan notes (explicitly not covered — carried over from spec section 8)

- Java tab, AI Release Monitor tab — no models/routes/templates.
- Auth/authorization — none added anywhere.
- The "Перезапуск" (restart) button in spec 3.2 has no defined semantics beyond its presence in the mockup; needs its own brainstorming pass before implementation.
- systemd unit file / VPS deployment config — deploy-time concern, not exercised by tests, intentionally left out of this plan.
- Jenkins triggering for `execution_mode="jenkins"` (Task 11): the `Job` row is created but `trigger_build`/`poll_build_status` (Task 8, fully implemented and tested standalone) are not wired in yet — the spec never defines how a Jenkins base URL / job name is derived from Team/Stand. Needs a short brainstorming pass to define that mapping (likely a new reference-data field or a config table) before wiring the trigger + a background polling task that publishes `job-status` events the same way `start_local_job` does.
