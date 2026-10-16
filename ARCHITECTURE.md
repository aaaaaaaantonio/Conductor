# TestDepot — карта проекта

Документ для быстрого входа (в том числе для LLM): что где лежит, как устроены
процессы и какие решения приняты намеренно. Запуск и переменные окружения — в
README.md, здесь только устройство.

## Что это

Веб-панель для запуска автотестов командой QA. Три вида запусков:

| Вкладка | Куда уходит запуск | Отслеживается ли |
|---|---|---|
| **Java** | только Jenkins (`buildWithParameters`) | нет: показывается ссылка на сборку |
| **Python** | Jenkins **или** локально на этой машине («VM-агент») | VM — да: живой лог, статус, длительность, «Остановить» |
| **Тестирование агентов** | локально, произвольный скрипт с настраиваемыми полями | да, как Python VM |

Плюс: **История** запусков, **Справочники** (команды, стенды, тесты, датасеты),
**Доступы** (личные токены Jenkins / Allure / Zephyr в зашифрованной cookie),
**Уведомления** о завершении (звук, цифра на вкладке, системные).

## Стек

- Python ≥ 3.12, FastAPI, SQLModel (SQLAlchemy) поверх SQLite, Jinja2, httpx, cryptography (Fernet).
- Фронтенд без сборки: серверный HTML + **htmx** (`hx-*` атрибуты, `hx-boost` навигация) + расширение **htmx SSE** + немного ванильного JS.
- uv (зависимости, запуск), pytest + pytest-asyncio (`asyncio_mode = auto`), ruff (line-length 120). CI: `.github/workflows/ci.yml` — ruff + pytest на 3.12 и 3.14.

## Дерево

```
app/
  main.py                 create_app(): middleware, роутеры, /static, lifespan (init_db, восстановление, чистка)
  config.py               все переменные окружения (_int_env валидирует числа)
  db.py                   engine, init_db (create_all, без миграций), get_session, PRAGMA foreign_keys
  credentials.py          Credentials, шифрование cookie, credentials_middleware, get_credentials
  origin_check.py         CSRF: отклоняет POST/PUT/PATCH/DELETE с чужим Origin
  retention.py            удаление старых запусков и логов (при старте и раз в час)
  logging_setup.py        лог приложения: консоль или LOG_FILE (ротация по размеру, очистка при старте,
                          забирает и вывод uvicorn); причины 4xx/422 через exception handlers, log_refused()
  templating.py           Jinja2 + фильтры: localtime, duration, highlight, utc_iso; глобал job_duration
  grouping.py             group_by()
  test_params.py          параметры теста (CustomParam: text/bool/flag), их проверка, служебные имена
                          Java/Python, jenkins_values()/vm_args()
  models/
    jobs.py               Job, duration_seconds(), as_utc()
    reference.py          ReferenceItem, TeamStandLink, SelectedId, item_params, active_references, launch_reference_error
    agent_testing.py      Agent, AgentTest
  execution/
    runner.py             локальный запуск подпроцесса, стрим лога, отмена, статусы
    broadcaster.py        EventBroadcaster: fan-out событий в SSE-подписчиков
    log_lines.py          read_lines, mask (скрытие токенов), for_display, matches/highlight, ERROR_PATTERN
    command_builder.py    FieldSpec/FlagSpec -> argv
    jenkins_client.py     trigger_build(): POST buildWithParameters (query собирается вручную), вернуть Location
    jenkins_launch.py     ХУКИ для своей логики: launch_in_jenkins, restart_java, restart_python
    credential_checks.py  проверка токенов при сохранении: check_jenkins/allure/zephyr
  routers/
    launch_python.py      /python, /python/launch, /python/restart
    launch_java.py        /java, /java/launch, /java/restart
    jobs.py               /jobs/*: список, лог, поиск, скачивание, отмена, SSE /jobs/stream; общие Jenkins-ответы
    agent_testing.py      /agent-testing (страница+фрагменты), /api/agents*, /api/agent-tests*
    references.py         /api/references* (CRUD, порядок, связи команда-стенд, фрагменты <option>), /references
    history.py            /history, /history/fragments/list
    credentials.py        /credentials (GET, POST), /credentials/forget
  templates/              base.html (оболочка, сайдбар, SSE, панель уведомлений) + страницы + fragments/
  static/
    htmx.min.js, sse.js   вендорные htmx и SSE-расширение (не править)
    app.js                общий клиентский код (см. «Фронтенд»)
    notify.js             уведомления о завершении
    form-error.js         window.formError: показ ошибок API в формах
    style.css, favicon.svg
tests/                    pytest; conftest.py подменяет app.db.engine на in-memory SQLite
run-python-tests.example.sh  заглушка VM-скрипта (печатает аргументы, 5 с, exit 0)
docs/superpowers/         исходные спецификация и план (история, может устареть)
```

## Модель данных (SQLite, `test_runner.db`)

Схема создаётся `SQLModel.metadata.create_all` при старте. **Миграций нет**:
новое поле в существующей таблице само не появится.

- **ReferenceItem** — справочники одной таблицей. `category`: `team` | `stand` | `java_test` | `python_test` | `dataset`.
  Иерархия через `parent_id`: `java_test`/`python_test` → `team`, `dataset` → `python_test`; `team` и `stand`
  верхнего уровня. Java-тест не виден на вкладке Python и наоборот.
  `is_active=False` — мягкое удаление (строка остаётся, дети становятся «сиротами» и видны на /references
  под заглушками «Без команды»/«Без теста»). `sort_order` — ручной порядок (кнопки вверх/вниз).
  `command` — у теста: команда запуска (Python VM передаёт её вместо id, Jenkins получает `test_command`).
  `part` — только у `java_test`: `front` | `back`, входит в проверку дубля (у команды бывают `login`/фронт и
  `login`/бэк). `params_json` — у тестов: JSON-список `{key, type, value}`, `type` — `text` (непустое значение),
  `bool` (`true`/`false`) или `flag` (`null`); проверяется при сохранении (`test_params.validate_params`):
  ключ по `^[A-Za-z0-9_][A-Za-z0-9_.-]*$`, без повторов, не служебное имя языка (без учёта регистра),
  у Python — не префикс VM-флага (argparse развернул бы `--tea` в `--team`).
- **TeamStandLink** (team_id, stand_id) — какие стенды доступны команде (многие-ко-многим).
- **Agent** (team_id, name) и **AgentTest** (agent_id, path, flags_json, fields_json) — конфигурация
  «Тестирования агентов». Удаление настоящее (hard delete), запуски не ссылаются на тесты.
- **Job** — один запуск: `source` (`python` | `java` | `agent_test`), `status`, `params_json`
  (что выбрал пользователь), `log_path` (только у локальных), `jenkins_build_id` (URL из Location Jenkins),
  `created_at`, `updated_at` (onupdate). Время хранится в UTC; SQLite возвращает его naive → `as_utc()`.

### Статусы Job

```
Локальный (Python VM, агенты):  queued → running → success | failed | cancelled
                                queued → cancelled (остановлен до старта)
Jenkins (Java, Python Jenkins): triggering → triggered | failed
```

- «Активные» (список справа, тикающая длительность, «Остановить»): только `queued`, `running`.
  `triggering` намеренно не активен — Jenkins-запуски в список не попадают.
- При старте сервера `recover_stale_jobs` переводит `queued/running/triggering` в `failed`.
- `duration_seconds`: для активных — до «сейчас», для завершённых — `updated_at − created_at`;
  `None` для Jenkins (нет `log_path`). Отсчёт идёт от создания (включает очередь).

## Процессы

### 1. Запуск Python на VM (локально)

1. Форма `python_tab.html` → `POST /python/launch` (htmx, ответ в `#job-list`).
2. `launch_reference_error` проверяет выбор: команда/стенд заданы и активны, тест — `python_test` этой
   команды, датасет — этого теста. Ошибка → `launch_refused_response` (карточка в панели лога через `HX-Retarget`).
3. Нужны токены Allure **и** Zephyr из cookie (`creds.vm_env()`), иначе отказ со ссылкой на «Доступы».
4. Создаётся `Job(status="queued")`, `build_command(PYTHON_TEST_RUNNER_PATH, PYTHON_FIELDS, values)` даёт argv:
   `--team=<id> --stand=<id> --regression-type=<…> [--test-name=<command или id>] [--dataset=<id>]`,
   затем параметры теста: `--key=value` (text, bool) или голый `--key` (flag).
   В `Job.params_json` пишется и `test_params`.
5. `BackgroundTasks` → `start_local_job_with_own_session` (своя DB-сессия: сессия запроса к этому
   моменту закрыта) → `runner.start_local_job`.
6. Ответ: свежий список активных + заголовок `HX-Trigger: {"job-launched": {"id": …}}` (для notify.js).

### 2. Runner (`execution/runner.py`)

- Статус → `running`, событие `job-status`. Подпроцесс через `create_subprocess_exec` (без shell),
  stdout+stderr вместе, **`start_new_session=True`** (своя группа процессов — чтобы убивать и детей),
  `env` = окружение сервера + `ALLURE_TOKEN`, `ZEPHYR_TOKEN`.
- `read_lines` читает кусками по 64 КБ (строки любой длины), каждая строка: `mask` (значения токенов
  длиной ≥ 4 → `***`) → запись в `job_logs/job-<id>.log` → событие `log-line` с номером `n`
  и `for_display` (длинная строка обрезается до хвоста `LOG_LINE_MAX_CHARS`).
- Финал: код 0 → `success`, иначе `failed`; отменён → `cancelled` + строка «— Остановлено пользователем —».
  Исключение при старте (нет файла) → `failed` + причина в лог. В `finally` всегда коммит и `job-status`
  с `source` и `duration` (для уведомлений).
- Остановка сервера (задача отменена) → убить группу процессов, `failed`.
- Состояние в памяти процесса: `_processes` (живые), `_owned` (обрабатываются), `_cancel_requested`.
  Поэтому **uvicorn строго в один worker**.

### 3. Отмена («Остановить»)

`POST /jobs/{id}/cancel` → `cancel_job`: есть живой процесс → `killpg(SIGKILL)`, runner сам ставит
`cancelled` (эндпоинт ждёт до 2,5 с, чтобы вернуть финальное состояние). Процесса нет (в очереди или
остаток после рестарта) → эндпоинт сам пишет `cancelled` и шлёт событие; runner при старте проверяет
и не запускается. 409, если запуск уже не активен.

### 4. Jenkins (Java и Python в режиме Jenkins, перезапуски)

1. `Job(status="triggering")`. Служебные параметры без `None`, затем параметры теста (`jenkins_values`):
   `key=value` или голый `key` у `flag`. Java отправляет `team_id, stand_id, regression_type, part, thread_mode,
   test_name_id, test_command`, Python — `team_id, stand_id, regression_type, test_name_id, test_command,
   dataset_id`. Java проверяет, что тест — `java_test` этой команды **и части**. `trigger_build` собирает
   query сам (`quote` ключа и значения): httpx `params=` не умеет голый ключ.
2. `jobs.jenkins_reply_response`: нет cookie → `failed` + ссылка на «Доступы»; иначе вызывает хук.
3. Хуки в `execution/jenkins_launch.py` — **место для своей логики**: `launch_in_jenkins`,
   `restart_java`, `restart_python`. Возвращают `LaunchResult(message, url)`; исключение = ошибка,
   её текст показывается. Сейчас все зовут `trigger_build` (Basic Auth пользователя,
   `POST {JENKINS_BASE_URL}/job/<name>/buildWithParameters`, URL из `Location`).
4. Успех → `triggered`, `jenkins_build_id = url`; 401/403 → «обновите токен»; прочее → `failed`.
5. Ответ — карточка `fragments/jenkins_launched.html`, вставляется в начало `#job-log-body`
   (лента ответов на странице).

Намеренно: **логи и статус Jenkins-сборок не отслеживаются** — только ссылка на сборку.

### 5. Тестирование агентов

- Команда → агенты → тесты (дерево на `/agent-testing`, модалка с карточкой теста).
- `AgentTest`: `path` (исполняемый файл), `fields` (поля формы: `label`, `flag_name`, `type`
  text|number|select|checkbox|path, `required`, `options`) и `flags` (фиксированные: `bool` — голый флаг,
  `value` — `name=default`).
- `build_command`: сначала поля в порядке формы как `flag=value` (checkbox — голый флаг, если отмечен;
  пустое поле берёт default из одноимённого value-флага; обязательное пустое → 422; number проверяется),
  потом остальные флаги.
- Карточка (`fragments/agent_test_card.html`) шлёт JSON `POST /api/agent-tests/{id}/launch`
  `{"values": {...}}` → 202 `{"job_id"}` → дальше как Python VM. Событие `job-launched` JS шлёт сам.

### 6. Живые обновления (SSE)

- Один поток на страницу: `base.html` — `<div hx-ext="sse" sse-connect="/jobs/stream">`.
- `EventBroadcaster.publish` кладёт событие в очередь каждого подписчика (не ждёт; отставший
  на 1000 событий отключается и переподключается браузером). Heartbeat `: ping` раз в 15 с.
- События: `job-status` (JSON) и `log-line` (готовый `<div data-job data-n>` с экранированным текстом).
- Потребители: `hx-trigger="sse:job-status"` перезагружает `#job-list` / `#history-list`;
  `app.js` дописывает строки в открытый лог и обновляет его шапку; `notify.js` уведомляет.
- Невидимый `<div sse-swap="log-line,job-status" hx-swap="none">` нужен, чтобы sse.js вообще
  генерировал `htmx:sseMessage`.
- Открытые SSE-потоки не дают uvicorn завершиться → запуск с `--timeout-graceful-shutdown 5`.

### 7. Панель лога

- `GET /jobs/{id}/fragments/log?q=&errors=` читает файл целиком построчно (по `\n`, `\r` выкидывается —
  как в live), держит последние `LOG_TAIL_LINES` (совпавших) строк с реальными номерами.
- Поиск: подстрока без учёта регистра (`matches`) и/или «только ошибки» (`ERROR_PATTERN`),
  подсветка `<mark>` через фильтр `highlight`. Тот же шаблон продублирован в `app.js` —
  **менять синхронно**, без lookbehind (старый Safari не распарсит весь app.js).
- `GET /jobs/{id}/log.txt` — полный лог (ровно столько байт, сколько было на момент запроса).

### 8. Доступы (токены пользователей)

- `/credentials` POST: проверка (`credential_checks`) → cookie. Jenkins проверяется всегда
  (`GET /me/api/json`), Allure (обмен API-токена на JWT) и Zephyr (`GET /rest/api/2/myself`, Bearer) —
  только если поле заполнено и задан базовый URL.
- Cookie `testdepot_creds`: Fernet (ключ = SHA-256 от `TESTDEPOT_SECRET_KEY`; пусто → случайный на процесс),
  HttpOnly, SameSite=Strict. На сервере токены не хранятся и не логируются.
- `credentials_middleware` на каждом запросе расшифровывает cookie в `request.state.credentials`,
  продлевает её (скользящее окно: 12 ч или 30 дней с «Запомнить», не чаще `CREDS_REFRESH_AFTER`),
  чистит битую/просроченную. Жёсткий предел `CREDS_MAX_LIFETIME` от `issued_at`.
- Эндпоинт, который сам ставит/чистит cookie, вызывает `mark_changed(request)`.

### 9. Справочники и каскадные селекты

- `/references` — редактирование (inline JS в `references.html`, fetch к `/api/references`). Две плитки
  тестов (Java, Python); тест создаётся и правится в модалке `#test-modal` (строки параметров
  «ключ | тип | значение»), у остальных категорий — inline-редактирование.
- Формы запуска строят цепочки через `<option>`-фрагменты: Java — `team → stand`, `team + part → test`
  (`/fragments/java-tests?team_id=&part=`); Python — `team → stand`, `team → test → dataset`
  (`/fragments/python-tests?team_id=`, `/fragments/datasets?test_id=`).
  Пустой/пробельный родитель или часть (у верхнего селекта нет вариантов) → пустой список; отсутствующий
  параметр → 422; удалённый родитель → пусто. Тип `SelectedId` (пустая строка → None) общий с формами запуска.
- Дубликаты значения запрещены в пределах (категория, родитель, часть) среди активных → 409.

### 10. История и хранение

- `/history`: фильтры source/status/даты (даты в локальном времени сервера → UTC), максимум 500 строк,
  клик открывает тот же фрагмент лога.
- `retention.purge_old_jobs`: завершённые запуски старше `JOB_RETENTION_DAYS` удаляются вместе с логами,
  плюс осиротевшие `job-*.log` старше срока. При старте и раз в час.

### 11. Уведомления (`static/notify.js`)

- Браузер помнит id запусков, начатых **в нём** (`localStorage testdepot:my-jobs`, общий для вкладок;
  первая вкладка, увидевшая финал, «забирает» id — уведомление одно).
- На `job-status` с `success`/`failed` своего запуска, если вкладка не в фокусе: цифра на favicon
  (canvas) и в title, синтезированный звук (Web Audio), системное уведомление (только HTTPS/localhost).
  `cancelled` — без уведомления. Настройки в `localStorage testdepot:notify`.

## Фронтенд: соглашения

- `hx-boost` в сайдбаре: навигация заменяет содержимое `<body>` и **заново выполняет скрипты**.
  Поэтому `app.js`/`notify.js` защищены флагом `window.__…Init`, а страничные скрипты вешают
  делегированные обработчики через `window.bindPersistent` (base.html), а не `addEventListener`.
- `form[data-remember="<key>"]` — значения формы запоминаются в `localStorage testdepot:form:<key>`
  и восстанавливаются, в том числе в каскадных селектах после подгрузки их вариантов.
- Отказы запуска и ответы Jenkins приходят с `HX-Retarget: #job-log-body` + `HX-Reswap: afterbegin`.
- Ошибки JSON-API в формах — `formError.fromResponse/show/clear` (переводит ошибки валидации FastAPI).

## Безопасность (намеренные решения)

- **Аутентификации нет и не планируется** — инструмент внутренней сети; не предлагать.
- CSRF: `origin_check_middleware` (Origin ≠ Host или ≠ `TESTDEPOT_ALLOWED_ORIGINS` → 403;
  без Origin — пропуск, для curl/скриптов) + SameSite=Strict cookie.
- Команды запускаются без shell (argv), значения как `--flag=value`.
- Токены: только в зашифрованной cookie и в env подпроцесса; в логах маскируются.
  В лог сервера не пишутся: у 422 — только поле и сообщение, без введённых значений.

## Тесты

- `tests/conftest.py`: in-memory SQLite (подмена `app.db.engine` — поэтому модули импортируют
  engine внутри функций, а не на верхнем уровне), `client` (TestClient), `session`.
- По файлу на область: `test_runner.py` (подпроцессы, отмена, маскирование), `test_jobs_api.py`
  (список, лог, поиск, SSE, Python-запуск), `test_launch_java_api.py`, `test_reference_api.py`,
  `test_agent_testing_api.py`, `test_command_builder.py`, `test_credentials*.py`, `test_history_api.py`,
  `test_retention.py`, `test_origin_check.py`, `test_lifespan.py`, `test_config.py`, `test_broadcaster.py`,
  `test_jenkins_client.py`, `test_restart_api.py`, `test_job_duration.py`.
- Фронтенд не тестируется в браузере; часть поведения проверяется по тексту отдаваемых шаблонов/JS.
- Проверка перед коммитом: `uv run ruff check && uv run pytest`.

## Куда смотреть, если нужно…

| Задача | Файлы |
|---|---|
| Поменять, что уходит в Jenkins | `execution/jenkins_launch.py` |
| Поменять правила параметров теста или служебные имена | `test_params.py` |
| Поменять аргументы Python VM-скрипта | `routers/launch_python.py` (`PYTHON_FIELDS`, `values`) |
| Новое поле в форме запуска | шаблон вкладки + параметр `Form` в роутере + `launch_reference_error` при ссылке на справочник |
| Новая категория справочника | `references.py` (`Category`, `PARENT_CATEGORY`), `references.html` |
| Новое SSE-событие | `broadcaster.publish(...)` + обработчик `htmx:sseMessage` в `app.js` + `sse-swap` в base.html |
| Новый статус запуска | `runner.py`, `history.STATUSES`, `retention.ACTIVE_STATUSES`, классы в шаблонах и `app.js` |
| Новая переменная окружения | `config.py`, README, `.env.example` |
| Новая колонка в таблице | модель + **ручная миграция** существующей БД (create_all не меняет таблицы) |
