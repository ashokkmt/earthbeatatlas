FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY config ./config
COPY migrations ./migrations
COPY scripts ./scripts
COPY data/seeds ./data/seeds
COPY data/releases/nisar-pilot-20261114-v1/santa-rosa/santa-rosa-perimeter-clipped.geojson ./data/releases/nisar-pilot-20261114-v1/santa-rosa/
COPY data/releases/nisar-pilot-20261114-v1/barataria/barataria-nwi-emergent.geojson ./data/releases/nisar-pilot-20261114-v1/barataria/
COPY data/releases/nisar-pilot-20261114-v1/barataria/barataria-nwi-forested-shrub.geojson ./data/releases/nisar-pilot-20261114-v1/barataria/
COPY data/releases/nisar-pilot-20261114-v1/colusa/cdl-2025-rice.png ./data/releases/nisar-pilot-20261114-v1/colusa/
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["uvicorn", "nasa_explorer.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
