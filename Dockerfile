FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY config ./config
COPY migrations ./migrations
COPY scripts ./scripts
COPY data/seeds ./data/seeds
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["uvicorn", "nasa_explorer.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
