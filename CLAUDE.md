# Conductor

Веб-панель запуска автотестов (FastAPI + SQLite + htmx). Полная карта модулей и процессов —
**ARCHITECTURE.md**, читать перед изменениями. Запуск и переменные окружения — README.md.

- Проверка: `uv run ruff check && uv run pytest`.
- uvicorn только в один worker: процессы запусков и их отмена живут в памяти процесса.
- Нет аутентификации и нет отслеживания логов/статуса Jenkins-сборок — намеренно, не предлагать.
- `ERROR_PATTERN` в `app/execution/log_lines.py` и `app/static/app.js` менять синхронно, без lookbehind.
- Миграций нет: новая колонка в существующей БД сама не появится.
- Новая переменная окружения → `app/config.py`, README, `.env.example`.
