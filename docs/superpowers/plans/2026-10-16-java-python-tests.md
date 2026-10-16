# Раздельные Java/Python-тесты с параметрами — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Разделить тесты справочника на `java_test` и `python_test`, дать им типизированные параметры
(текст / да-нет / без значения), модальное окно создания и передачу параметров в Jenkins и на VM.

**Architecture:** Вся логика параметров (модель, валидация, служебные имена, сборка Jenkins-значений и argv)
живёт в новом модуле `app/test_params.py`, которым пользуются API справочников и оба роутера запуска.
`ReferenceItem` получает колонки `part` и `params_json`. `trigger_build` собирает query-строку сам,
чтобы `None` уходил голым ключом.

**Tech Stack:** FastAPI, SQLModel/SQLite, Jinja2 + htmx, ванильный JS, pytest, httpx MockTransport.

**Spec:** `docs/superpowers/specs/2026-10-16-java-python-tests-design.md`

## Global Constraints

- Проверка после каждой задачи: `uv run ruff check && uv run pytest` — зелёные.
- Миграций нет; старую `test_runner.db` пользователь удаляет сам. Тесты используют in-memory БД.
- Имена Jenkins-параметров не меняются: `team_id, stand_id, regression_type, part, thread_mode, test_name_id, test_command` (Java), `team_id, stand_id, regression_type, test_name_id, test_command, dataset_id` (Python). Служебные `None` отбрасываются.
- Регекс ключа: `^[A-Za-z0-9_][A-Za-z0-9_.-]*$`. Сравнение со служебными именами — без учёта регистра.
- Типы параметра: `text` (непустое значение после `strip()`), `bool` (ровно `true`/`false`), `flag` (значение `null`).
- В Jenkins: `text`/`bool` → `key=value`, `flag` → голый `key`. На VM: `--key=value` / голый `--key`, после штатных аргументов.
- Все сообщения пользователю — на русском. Нет аутентификации и отслеживания Jenkins — не добавлять.
- Функции в `app/` не называть с префиксом `test_`, а классы — с `Test` (pytest соберёт их при импорте в тестах).
  Поэтому хелпер спеки `test_params(item)` называется `item_params(item)`.

## Review Focus

1. Ключ в другом регистре (`Team_ID`, `TEAM`) у Java-теста → 422, а не тихая подмена служебного параметра. Тест в Task 1.
2. Значение со спецсимволами (`a b&c=d`, кириллица) в Jenkins → процентное кодирование, query не ломается. Тест в Task 2.
3. Редактирование Java-теста со сменой части на ту, где у команды уже есть тест с таким именем → 409. Тест в Task 3.
4. После смены части в форме Java уходит тест прежней части (устаревший select) → отказ «Тест не найден у этой команды и части — обновите страницу». Тест в Task 4.
5. Python-ключ — префикс VM-флага (`tea`, `test`, `regression`) → 422; ключ длиннее флага (`teams`) → принят. Тест в Task 1.

---

### Task 1: Модуль параметров `app/test_params.py`

**Files:**
- Create: `app/test_params.py`
- Test: `tests/test_custom_params.py`

**Interfaces:**
- Produces:
  - `ParamType = Literal["text", "bool", "flag"]`
  - `class CustomParam(BaseModel)`: `key: str`, `type: ParamType = "text"`, `value: str | None = None`
  - `class ParamError(ValueError)` — сообщение на русском, роутер превращает в 422.
  - `Language = Literal["java", "python"]`
  - `JAVA_RESERVED: frozenset[str]` = `{"team_id","stand_id","regression_type","part","thread_mode","test_name_id","test_command"}`
  - `PYTHON_RESERVED: frozenset[str]` = `{"team_id","stand_id","regression_type","test_name_id","test_command","dataset_id","team","stand","regression-type","test-name","dataset"}`
  - `PYTHON_VM_FLAGS: tuple[str, ...]` = `("team","stand","regression-type","test-name","dataset")`
  - `validate_params(params: list[CustomParam], language: Language) -> list[CustomParam]` — возвращает нормализованный список (ключ и `text`-значение без крайних пробелов, у `flag` value `None`), иначе `ParamError`.
  - `load_params(params_json: str | None) -> list[CustomParam]` (`None` → `[]`)
  - `dump_params(params: list[CustomParam]) -> str | None` (пустой список → `None`)
  - `jenkins_values(params: list[CustomParam]) -> dict[str, str | None]` (`flag` → `None`)
  - `vm_args(params: list[CustomParam]) -> list[str]`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from app.test_params import CustomParam as P, ParamError, validate_params, load_params, dump_params, jenkins_values, vm_args

def test_normalizes_text_and_flag():
    out = validate_params([P(key=" env ", type="text", value="  stage "), P(key="headless", type="flag", value="")], "java")
    assert out == [P(key="env", type="text", value="stage"), P(key="headless", type="flag", value=None)]

@pytest.mark.parametrize("param, fragment", [
    (P(key="", type="flag"), "Пустой ключ"),
    (P(key="-x", type="flag"), "Недопустимый ключ"),
    (P(key="ключ", type="flag"), "Недопустимый ключ"),
    (P(key="env", type="text", value="  "), "выберите тип «без значения»"),
    (P(key="retry", type="bool", value="yes"), "true или false"),
    (P(key="retry", type="bool", value="True"), "true или false"),
    (P(key="headless", type="flag", value="1"), "не может быть значения"),
])
def test_rejects_bad_param(param, fragment):
    with pytest.raises(ParamError, match=fragment):
        validate_params([param], "java")

def test_rejects_duplicate_keys():
    with pytest.raises(ParamError, match="указан дважды"):
        validate_params([P(key="a", type="flag"), P(key="a", type="flag")], "java")

@pytest.mark.parametrize("key", ["team_id", "Team_ID", "THREAD_MODE", "part"])
def test_java_rejects_reserved_key_any_case(key):
    with pytest.raises(ParamError, match="служебным"):
        validate_params([P(key=key, type="flag")], "java")

@pytest.mark.parametrize("key", ["dataset_id", "test-name", "tea", "test", "regression", "Stan"])
def test_python_rejects_reserved_and_vm_flag_prefix(key):
    with pytest.raises(ParamError):
        validate_params([P(key=key, type="flag")], "python")

def test_python_accepts_key_longer_than_flag_and_java_accepts_python_only_names():
    validate_params([P(key="teams", type="flag")], "python")
    validate_params([P(key="dataset", type="flag")], "java")

def test_dump_load_roundtrip_and_empty():
    ps = [P(key="retry", type="bool", value="false"), P(key="headless", type="flag")]
    assert load_params(dump_params(ps)) == ps
    assert dump_params([]) is None and load_params(None) == []

def test_jenkins_values_and_vm_args():
    ps = [P(key="env", type="text", value="a b"), P(key="retry", type="bool", value="true"), P(key="headless", type="flag")]
    assert jenkins_values(ps) == {"env": "a b", "retry": "true", "headless": None}
    assert vm_args(ps) == ["--env=a b", "--retry=true", "--headless"]
```

- [ ] **Step 2: Run** `uv run pytest tests/test_custom_params.py -v` — FAIL (`ModuleNotFoundError: app.test_params`).

- [ ] **Step 3: Implement `app/test_params.py`** по Interfaces. Тексты ошибок (подставляется ключ):
  `"Пустой ключ параметра"`, `"Недопустимый ключ параметра «{key}»: только латиница, цифры, _ . -"`,
  `"Параметр «{key}» указан дважды"`, `"Ключ «{key}» занят служебным параметром запуска"`,
  `"Ключ «{key}» совпадает с началом служебного флага --{flag}"`,
  `"Укажите значение параметра «{key}» или выберите тип «без значения»"`,
  `"Значение параметра «{key}» — только true или false"`,
  `"У параметра «{key}» с типом «без значения» не может быть значения"`.
  Пустое/пробельное значение у `flag` → `None` (не ошибка). Дубли сравниваются без учёта регистра.
  Префикс VM-флага: `flag.startswith(key.lower())` для любого флага из `PYTHON_VM_FLAGS`.

- [ ] **Step 4: Run** `uv run pytest tests/test_custom_params.py -v` — PASS.

- [ ] **Step 5: Commit** `git add app/test_params.py tests/test_custom_params.py && git commit -m "feat: typed custom test params module"`

---

### Task 2: Jenkins query с голыми ключами

**Files:**
- Modify: `app/execution/jenkins_client.py`
- Test: `tests/test_jenkins_client.py`

**Interfaces:**
- Produces: `trigger_build(base_url, job_name, params: dict[str, object | None], client, auth=None) -> str` — сигнатура прежняя; значение `None` → голый ключ, остальное через `str()`. Пустой `params` → URL без `?`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_trigger_build_sends_bare_keys_and_encodes_values():
    seen = []
    def handler(request):
        seen.append(request.url)
        return httpx.Response(201, headers={"Location": "https://jenkins/queue/item/1/"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await trigger_build("https://jenkins", "job", {"team_id": 1, "env": "a b&c=d", "имя": "тест", "headless": None}, client)
    assert seen[0].query == b"team_id=1&env=a%20b%26c%3Dd&%D0%B8%D0%BC%D1%8F=%D1%82%D0%B5%D1%81%D1%82&headless"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_jenkins_client.py -v` — FAIL (httpx шлёт `headless=`).
- [ ] **Step 3: Implement** — собрать query через `urllib.parse.quote(..., safe="")` для ключа и значения и дописать к URL; `params=` в `client.post` убрать.
- [ ] **Step 4: Run** `uv run pytest tests/test_jenkins_client.py tests/test_launch_java_api.py tests/test_restart_api.py -v` — PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: Jenkins query with bare keys for valueless params"`

---

### Task 3: Модель, API справочников, фрагменты, проверка запуска

**Files:**
- Modify: `app/models/reference.py`, `app/routers/references.py`, `app/routers/launch_java.py`, `app/routers/launch_python.py` (только вызов `launch_reference_error` и `test_name_id` → новый вызов; поля форм — в Task 4/5)
- Create: `app/templates/fragments/test_options.html` (переменная `tests`), Delete: `app/templates/fragments/test_name_options.html`
- Modify: `app/templates/java_tab.html`, `app/templates/python_tab.html` — только `hx-get` на новые фрагменты, чтобы страницы не ссылались на удалённый URL (Java: `/fragments/java-tests`, `hx-include="#j-team-select, #j-part-select"`, триггер `load, change from:#j-team-select, change from:#j-part-select`; Python: `/fragments/python-tests`; датасеты: параметр `test_id`).
- Test: `tests/test_reference_api.py`, а также `tests/test_launch_java_api.py`, `tests/test_jobs_api.py` — заменить `"test_name"` на `java_test`/`python_test` (Java-тестам добавить `"part": "front"`), `test_name_id` в query фрагмента датасетов → `test_id`.

**Interfaces:**
- Consumes: Task 1 (`CustomParam`, `validate_params`, `dump_params`, `load_params`, `ParamError`).
- Produces:
  - `ReferenceItem.part: str | None`, `ReferenceItem.params_json: str | None`
  - `item_params(item: ReferenceItem) -> list[CustomParam]` в `app/models/reference.py`
  - `TestCategory = Literal["java_test", "python_test"]` в `app/models/reference.py` (имя типа, не класса — pytest не трогает)
  - `launch_reference_error(session, team_id, stand_id, test_id, test_category: TestCategory, part: str | None = None, dataset_id: int | None = None) -> str | None`
  - Фрагменты: `GET /api/references/fragments/java-tests?team_id=&part=`, `GET /api/references/fragments/python-tests?team_id=`, `GET /api/references/fragments/datasets?test_id=`. Параметр `part` — `Annotated[Literal["front","back"] | None, BeforeValidator(blank_to_none)]`, обязателен (отсутствует → 422, пустой → пустой список).
  - Тело create: `{category, value, parent_id, command, part, params: [{key,type,value}]}`; update — то же без `category`. Ответ содержит `part` и `params_json` (сырой JSON).

- [ ] **Step 1: Write the failing tests** (в `tests/test_reference_api.py`; хелпер `_create` расширить kwargs `part`, `params`)

```python
def test_java_test_requires_part_and_others_forbid_it(client):
    team = _create(client, "team", "QA")
    assert client.post("/api/references", json={"category": "java_test", "value": "t", "parent_id": team["id"]}).status_code == 422
    assert client.post("/api/references", json={"category": "python_test", "value": "t", "parent_id": team["id"], "part": "front"}).status_code == 422
    assert client.post("/api/references", json={"category": "team", "value": "X", "params": [{"key": "a", "type": "flag"}]}).status_code == 422

def test_params_saved_normalized_and_bad_params_rejected_in_russian(client):
    team = _create(client, "team", "QA")
    body = {"category": "java_test", "value": "t", "parent_id": team["id"], "part": "back",
            "params": [{"key": " retry ", "type": "bool", "value": "true"}, {"key": "headless", "type": "flag", "value": ""}]}
    item = client.post("/api/references", json=body).json()
    assert json.loads(item["params_json"]) == [{"key": "retry", "type": "bool", "value": "true"}, {"key": "headless", "type": "flag", "value": None}]
    bad = client.post("/api/references", json={**body, "value": "t2", "params": [{"key": "Team_ID", "type": "flag"}]})
    assert bad.status_code == 422 and "служебным" in bad.json()["detail"]

def test_same_name_allowed_for_front_and_back_but_not_twice_in_one_part(client):
    team = _create(client, "team", "QA")
    _create(client, "java_test", "login", team["id"], part="front")
    _create(client, "java_test", "login", team["id"], part="back")
    dup = client.post("/api/references", json={"category": "java_test", "value": "login", "parent_id": team["id"], "part": "front"})
    assert dup.status_code == 409

def test_update_moving_java_test_into_part_with_same_name_is_409(client):  # Review Focus 3
    team = _create(client, "team", "QA")
    _create(client, "java_test", "login", team["id"], part="front")
    back = _create(client, "java_test", "login", team["id"], part="back")
    resp = client.put(f"/api/references/{back['id']}", json={"value": "login", "parent_id": team["id"], "part": "front"})
    assert resp.status_code == 409

def test_update_replaces_params(client): ...  # PUT с новыми params → params_json заменён; params=[] → params_json is None

def test_java_tests_fragment_filters_by_part_and_python_fragment_by_category(client):
    team = _create(client, "team", "QA")
    _create(client, "java_test", "j-front", team["id"], part="front")
    _create(client, "java_test", "j-back", team["id"], part="back")
    _create(client, "python_test", "p", team["id"])
    html = client.get("/api/references/fragments/java-tests", params={"team_id": team["id"], "part": "front"}).text
    assert "j-front" in html and "j-back" not in html and ">p<" not in html
    py = client.get("/api/references/fragments/python-tests", params={"team_id": team["id"]}).text
    assert ">p<" in py and "j-front" not in py

def test_dataset_parent_must_be_python_test(client):
    team = _create(client, "team", "QA")
    jt = _create(client, "java_test", "j", team["id"], part="front")
    assert client.post("/api/references", json={"category": "dataset", "value": "d", "parent_id": jt["id"]}).status_code == 422
```

  Параметризованные тесты фрагментов (`test_option_fragments_*`) обновить на новые пути и параметры;
  для `java-tests` пустой `part` → пустой список, отсутствующий `part` → 422. `/fragments/test-names` → 404.

- [ ] **Step 2: Run** `uv run pytest tests/test_reference_api.py -v` — новые тесты FAIL.
- [ ] **Step 3: Implement**
  - Модель: колонки, `item_params`, `TestCategory`, новая `launch_reference_error`. Для Java при несовпадении части/команды/категории — `"Тест не найден у этой команды и части — обновите страницу"`, для Python — прежний текст. Датасет проверяется против `python_test`.
  - Роутер: `Category`, `PARENT_CATEGORY` (`java_test`/`python_test` → `team`, `dataset` → `python_test`); в create/update `part: Literal["front","back"] | None = None`, `params: list[CustomParam] = []`; общий `_check_test_fields(category, part, params) -> tuple[str | None, str | None]` (возвращает `part`, `params_json`; 422 с текстами: `"У Java-теста укажите часть: фронт или бэк"`, `"Часть бывает только у Java-теста"`, `"Параметры бывают только у тестов"`, `ParamError` → `str(exc)`); проверка дубля с условием `ReferenceItem.part == part`.
  - Фрагменты по Interfaces, старый удалить. `references_page` пока только переименовать категории так, чтобы страница рендерилась (полная переделка — Task 6).
  - Роутеры запуска: вызывать новую `launch_reference_error` (Java: `"java_test"`, `part=part`; Python: `"python_test"`), формы пока принимают `test_name_id` как раньше.
- [ ] **Step 4: Run** `uv run ruff check && uv run pytest` — PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: separate java_test/python_test references with part and typed params"`

---

### Task 4: Запуск Java — режим, часть, параметры

**Files:**
- Modify: `app/routers/launch_java.py`, `app/templates/java_tab.html`
- Test: `tests/test_launch_java_api.py`

**Interfaces:**
- Consumes: `launch_reference_error`, `item_params` (Task 3), `jenkins_values` (Task 1), `trigger_build` (Task 2).
- Produces: форма `POST /java/launch`: `team_id, stand_id, regression_type, part: Literal["front","back"], thread_mode: Literal["multi","single"], test_id: SelectedId`.

- [ ] **Step 1: Write the failing tests** (хелпер мок-Jenkins как в `test_launch_java_api_jenkins_mode_triggers_build`)

```python
def test_java_launch_sends_thread_mode_and_test_params_to_jenkins(client, session, monkeypatch):
    # тест: part=back, params retry=bool true, env=text "a b", headless=flag
    ...
    assert requests[0].url.query.decode() == (
        f"team_id={team}&stand_id={stand}&regression_type=regression&part=back&thread_mode=single"
        f"&test_name_id={test}&test_command=mvn%20test&retry=true&env=a%20b&headless")
    params = json.loads(job.params_json)
    assert params["thread_mode"] == "single"
    assert params["test_params"] == [{"key": "retry", "type": "bool", "value": "true"}, ...]

def test_java_launch_refuses_test_of_other_part(client, session):  # Review Focus 4
    # java_test part=front, запуск с part=back и test_id этого теста
    assert "Тест не найден у этой команды и части" in resp.text

def test_java_launch_refuses_python_test(client, session): ...  # test_id python_test → тот же отказ
def test_java_launch_requires_valid_thread_mode(client): ...    # thread_mode="fast" → 422
def test_java_tab_has_thread_mode_and_part_aware_test_select(client):
    html = client.get("/java").text
    assert 'name="thread_mode"' in html and "Многопоточный" in html and "Однопоточный" in html
    assert 'hx-get="/api/references/fragments/java-tests"' in html and 'name="test_id"' in html
    assert 'change from:#j-part-select' in html
```

  Существующие тесты Java-запуска дополнить `thread_mode`, `test_name_id` → `test_id`.

- [ ] **Step 2: Run** `uv run pytest tests/test_launch_java_api.py -v` — FAIL.
- [ ] **Step 3: Implement** — порядок Jenkins-параметров: служебные из Global Constraints (без `None`), затем `jenkins_values(item_params(test))`. В `Job.params_json` добавить `thread_mode` и `test_params` (`[p.model_dump() for p in …]`). В шаблоне — select «Режим» (`id="j-thread-select"`, `multi` «Многопоточный» первым) после «Части», select теста `name="test_id"`, подпись «Тест».
- [ ] **Step 4: Run** `uv run ruff check && uv run pytest` — PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: Java launch sends thread mode and test params"`

---

### Task 5: Запуск Python — параметры на VM и в Jenkins

**Files:**
- Modify: `app/routers/launch_python.py`, `app/templates/python_tab.html`
- Test: `tests/test_jobs_api.py`, `tests/test_launch_java_api.py` (тест `test_python_datasets_reload_when_test_name_changes` — новые id)

**Interfaces:**
- Consumes: `launch_reference_error`, `item_params`, `vm_args`, `jenkins_values`.
- Produces: форма `POST /python/launch`: `test_id: SelectedId` вместо `test_name_id`; select теста `id="p-test-select"`, датасетов — `hx-include="#p-test-select"`, триггер `htmx:afterSwap from:#p-test-select, change from:#p-test-select`.

- [ ] **Step 1: Write the failing tests**

```python
def test_python_vm_launch_appends_test_params_after_standard_args(client, session, monkeypatch):
    # перехватить start_local_job_with_own_session, тест с command="smoke" и params retry=bool false, headless=flag
    assert command[-2:] == ["--retry=false", "--headless"]
    assert "--test-name=smoke" in command   # бывший 500 из-за type="number"

def test_python_jenkins_launch_sends_test_params(client, session, monkeypatch):
    assert requests[0].url.query.decode().endswith("&retry=false&headless")
    assert json.loads(job.params_json)["test_params"][1] == {"key": "headless", "type": "flag", "value": None}

def test_python_launch_refuses_java_test(client, session): ...  # test_id java_test → «Тест не найден у этой команды»
```

  Существующие Python-тесты: `test_name_id` → `test_id`, `"test_name"` → `"python_test"`, id селектов в проверках шаблона.

- [ ] **Step 2: Run** `uv run pytest tests/test_jobs_api.py -v` — FAIL.
- [ ] **Step 3: Implement** — `FieldSpec("--test-name")` `type="text"`; argv = `build_command(...) + vm_args(params)`; Jenkins: служебные + `jenkins_values(params)`; `test_params` в `Job.params_json`.
- [ ] **Step 4: Run** `uv run ruff check && uv run pytest` — PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: Python launch passes test params to VM and Jenkins"`

---

### Task 6: Страница «Справочники» — две плитки и модальное окно

**Files:**
- Modify: `app/routers/references.py` (`references_page`), `app/templates/references.html`, при необходимости `app/static/style.css` (только существующие классы + стили строки параметра)
- Test: `tests/test_reference_api.py`

**Interfaces:**
- Consumes: API create/update из Task 3.
- Produces: контекст шаблона `teams, stands, stand_teams, java_tests_by_team, python_tests_by_team, python_tests, datasets_by_team, param_counts: dict[int, int]`. Группировка тестов под командами (с «Без команды») — один хелпер `_group_tests_by_team(tests, teams)` для обеих плиток; `datasets_by_team` строится по Python-тестам.

- [ ] **Step 1: Write the failing tests**

```python
def test_references_page_has_two_test_tiles_and_test_modal(client):
    team = _create(client, "team", "QA")
    _create(client, "java_test", "j-login", team["id"], part="back", params=[{"key": "retry", "type": "bool", "value": "true"}])
    _create(client, "python_test", "p-login", team["id"])
    html = client.get("/references").text
    assert "Java-тесты" in html and "Python-тесты" in html and "Имена тестов" not in html
    assert 'id="test-modal"' in html
    assert "+ Добавить Java-тест" in html and "+ Добавить Python-тест" in html
    assert "Бэк" in html and "1 парам." in html
    for label in ("Текст", "Да-нет", "Без значения"):
        assert label in html

def test_dataset_form_lists_only_python_tests(client):
    # java_test "j" и python_test "p" → в <select id="new-dataset-test"> есть "p", нет "j"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_reference_api.py -v` — FAIL.
- [ ] **Step 3: Implement**
  - Строка теста: имя, `· <code>команда</code>`, у Java бейдж «Фронт»/«Бэк», `· N парам.` при N > 0; data-атрибуты `data-id, data-category, data-parent, data-value, data-command, data-part, data-params` (JSON); кнопка ✎ с классом `test-edit` (не `ref-edit` — inline-редактирование у тестов не включается).
  - `#test-modal` по образцу `#stand-modal`: eyebrow «Новый Java-тест» / «Изменение Python-теста» и т. п.; поля `#test-modal-team` (select), `#test-modal-value`, `#test-modal-command`, fieldset «Часть» (радио `front` «Фронт» по умолчанию / `back` «Бэк», скрыт для Python), контейнер `#test-modal-params`, кнопка «+ параметр», ✕ на строке.
  - Строка параметра: `input.tp-key`, `select.tp-type` (`text` «Текст» по умолчанию / `bool` «Да-нет» / `flag` «Без значения»), `input.tp-text` или `select.tp-bool` (`true` по умолчанию / `false`), для `flag` поле значения скрыто; смена типа сбрасывает значение. Строки с пустым ключом не отправляются.
  - Открытие: `.modal-trigger[data-modal="test-modal"][data-category=…]` (создание, POST) и `.test-edit` (PUT `/api/references/{id}`). Ошибки — `formError.show` в `.modal-body`. Esc и клик по фону закрывают оба окна. Успех → `reload()`.
  - Плитка датасетов: форма с `#new-dataset-test` из `python_tests`, «Сначала добавьте Python-тест», группировка по Python-тестам.
- [ ] **Step 4: Run** `uv run ruff check && uv run pytest` — PASS. Затем вручную (скилл `run`): создать Java-тест с параметрами всех трёх типов, отредактировать, убедиться, что ошибка 422 видна в окне.
- [ ] **Step 5: Commit** `git commit -am "feat: Java/Python test tiles with modal editor"`

---

### Task 7: Документация

**Files:**
- Modify: `ARCHITECTURE.md` (модель данных, процессы 1, 4, 9, таблица «Куда смотреть» — `app/test_params.py`), `README.md`

- [ ] **Step 1:** ARCHITECTURE: категории `java_test`/`python_test`, `part`, `params_json` с типами; `trigger_build` собирает query сам; argv Python с параметрами; поле `thread_mode`.
- [ ] **Step 2:** README: заметка «после обновления удалите `test_runner.db`: схема справочника изменилась»; в таблице VM-аргументов строка про параметры теста (`--key=value` / `--key`); у `--test-name` — «команда запуска теста».
- [ ] **Step 3: Run** `uv run ruff check && uv run pytest` — PASS.
- [ ] **Step 4: Commit** `git commit -am "docs: java/python tests and typed params"`
