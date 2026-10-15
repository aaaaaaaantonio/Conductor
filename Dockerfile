FROM ghcr.io/astral-sh/uv:0.8.22-python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
RUN uv sync --locked --no-dev

# Database and local job logs live on a volume so they survive container rebuilds.
ENV DATABASE_URL=sqlite:////data/test_runner.db \
    JOB_LOG_DIR=/data/job_logs
VOLUME /data

EXPOSE 8000
# Exactly one worker: running VM jobs, «Остановить» and live logs are held in process memory.
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
