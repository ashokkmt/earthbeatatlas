# EarthBeat Atlas

EarthBeat Atlas is an interactive NISAR SAR archive and prepared-raster explorer. The React app is static; public search and data access use the Python API, PgSTAC/PostGIS, a COG tile service, and S3-compatible object storage. Processing runs separately and is disabled by default in cloud deployments.

## Local setup

Requirements: Docker Compose, Python 3.14 with `uv`, Node.js 24 with npm.

```sh
uv sync --locked
docker compose -f infra/compose.yaml up -d db stac-api project-api bootstrap catalog-sync
cd web && npm ci && npm run dev
```

Open the Vite URL printed in the terminal. Local API, STAC and tile requests use same-origin development proxies. The optional `assets` profile runs SeaweedFS, TiTiler and the processing worker. Keep credentials in an ignored `.env` file; do not commit `.env` or Earthdata credentials.

## Cloud deployment

The production container stack and provider walkthrough are maintained in `infra/cloud/` and the ignored local `plans/deploy-anywhere.md` runbook. `infra/cloud/compose.yaml` is the portable self-hosted stack: it exposes only the Caddy gateway, uses a persistent PgSTAC volume, requires external S3-compatible object storage, and defaults public job submission off. Set the secrets in a private deployment environment and run schema bootstrap before starting the public services.

Vercel hosts the static frontend only; it still needs a separately hosted API, STAC service, PgSTAC database, tile service and object storage. Railway hosts those container services separately. A Linux VM can run the full Compose stack. Do not publish PostgreSQL, TiTiler, or the worker directly to the internet.

## Operations

- API readiness: `/healthz`
- Internal API docs: `http://project-api:8000/docs` from inside the private network.
- STAC API is mounted at `/stac`
- Prepared COG tiles and point reads pass through the API allowlist at `/api/v1/tiles`
- Public CMR catalog sync runs in `catalog-sync`; it stores source metadata, not NASA archive pixels.
- Processing jobs and the Earthdata worker need explicit operator configuration and an authenticated, rate-limited gateway before public use.

Run validation locally with `uv run --locked python -m unittest discover -s tests`, `cd web && npm test && npm run build`, and `docker compose -f infra/compose.yaml config -q`.
