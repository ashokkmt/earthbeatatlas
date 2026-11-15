from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from nasa_explorer.catalog.registry import load_regions
from nasa_explorer.db import connect
from nasa_explorer.catalog.registry import load_products
from nasa_explorer.api.jobs import router as jobs_router

app = FastAPI(title="NISAR Explorer Project API", version="0.1.0")
app.include_router(jobs_router)


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
    root = Path(__file__).resolve().parents[3]
    return [{"id": name, "name": value["name"], "title": value.get("title"),
             "full_name": value.get("full_name"), "bounds_wgs84": value["bounds_wgs84"],
             "data_note": value.get("data_note"),
             "context_layers": [{**layer, "asset_url": f"/api/v1/cases/{name}/context/{layer.get('display_filename', layer['filename'])}"}
                                for layer in value.get("context_layers", [])
                                if (root / "data/releases/nisar-pilot-20261114-v1" / value["slug"] /
                                    layer.get("display_filename", layer["filename"])).is_file()]}
            for name, value in sorted(load_regions().items())]


@app.get("/api/v1/cases/{region_id}/context/{filename}")
def case_context(region_id: str, filename: str):
    region = load_regions().get(region_id)
    if not region:
        raise HTTPException(404, "Unknown configured region")
    layer = next((layer for layer in region.get("context_layers", [])
                  if filename in {layer["filename"], layer.get("display_filename", layer["filename"])}), None)
    if not layer:
        raise HTTPException(404, "Context layer not found")
    path = (Path(__file__).resolve().parents[3] / "data/releases/nisar-pilot-20261114-v1" /
            region["slug"] / layer.get("display_filename", layer["filename"]))
    if not path.is_file():
        raise HTTPException(404, "Context asset is not packaged")
    media_type = "application/geo+json" if path.suffix == ".geojson" else "image/png"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/api/v1/products")
def products():
    return [{
        "id": key,
        "short_name": value["product_short_name"],
        "maturity": value.get("maturity"),
        "workflow_state": value.get("workflow_state", "source_audit_required"),
        "parameters": value.get("parameters", value.get("channels", {})),
        "source_guide": value.get("source_guide", "https://nisar-docs.asf.alaska.edu/gcov/"),
        "harmony_guide": value.get("harmony_guide", "https://nisar-docs.asf.alaska.edu/harmony/"),
    } for key, value in sorted(load_products().items())]


@app.get("/api/v1/readiness/{collection_id}/{item_id}")
def readiness(collection_id: str, item_id: str):
    with connect() as conn:
        row = conn.execute("SELECT content FROM pgstac.items WHERE collection=%s AND id=%s", (collection_id, item_id)).fetchone()
    if not row:
        raise HTTPException(404, "Catalog item not found")
    props = row[0].get("properties", {})
    return {key: props.get(key) for key in ("readiness:archive", "quality:state", "readiness:visual", "readiness:reviewed_change", "readiness:catalog")}


@app.get("/api/v1/sync/status")
def sync_status():
    with connect() as conn:
        row = conn.execute("SELECT source,last_success,last_error,pages,records,expected_records,next_url FROM nasa_explorer.sync_state ORDER BY source").fetchall()
    return [{"source": r[0], "last_success": r[1], "last_error": r[2], "pages": r[3],
             "records": r[4], "expected_records": r[5], "in_progress": bool(r[6])} for r in row]
