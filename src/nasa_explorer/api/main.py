from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from nasa_explorer.catalog.registry import load_regions
from nasa_explorer.db import connect

app = FastAPI(title="NISAR Explorer Project API", version="0.1.0")


@app.get("/healthz")
def health():
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unavailable"})
    return {"status": "ok"}


@app.get("/api/v1/cases")
def cases():
    return [{"id": name, "name": value["name"], "bounds_wgs84": value["bounds_wgs84"]}
            for name, value in sorted(load_regions().items())]


@app.get("/api/v1/readiness/{collection_id}/{item_id}")
def readiness(collection_id: str, item_id: str):
    with connect() as conn:
        row = conn.execute("SELECT content FROM pgstac.items WHERE collection=%s AND id=%s", (collection_id, item_id)).fetchone()
    if not row:
        raise HTTPException(404, "Catalog item not found")
    props = row[0].get("properties", {})
    return {key: props.get(key) for key in ("readiness:archive", "quality:state", "readiness:visual", "readiness:reviewed_change", "readiness:catalog")}


@app.get("/api/v1/jobs/{job_id}")
def job(job_id: str):
    with connect() as conn:
        row = conn.execute("SELECT id,kind,status,details,updated_at FROM nasa_explorer.jobs WHERE id=%s", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return dict(zip(("id", "kind", "status", "details", "updated_at"), row))


@app.get("/api/v1/sync/status")
def sync_status():
    with connect() as conn:
        row = conn.execute("SELECT source,last_success,last_error,pages,records,expected_records,next_url FROM nasa_explorer.sync_state ORDER BY source").fetchall()
    return [{"source": r[0], "last_success": r[1], "last_error": r[2], "pages": r[3],
             "records": r[4], "expected_records": r[5], "in_progress": bool(r[6])} for r in row]
