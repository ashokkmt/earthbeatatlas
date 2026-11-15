"""Claim and process one bounded NISAR Harmony subset job."""

import json
import os
import time
from pathlib import Path

import earthaccess
from harmony import Client

from nasa_explorer.catalog.ingest import import_collection, import_items
from nasa_explorer.catalog.registry import load_products, load_regions
from nasa_explorer.db import connect
from nasa_explorer.processing.harmony import (earthdata_auth_strategy, fetch_harmony_cogs,
    harmony_request)
from nasa_explorer.processing.harmony_products import inspect_harmony_cogs, stac_records
from nasa_explorer.storage.s3 import publish


def claim_job() -> dict | None:
    """Atomically claim one available job; reclaim abandoned leases safely."""
    with connect() as conn:
        conn.execute("""UPDATE nasa_explorer.jobs SET status='expired',lease_expires_at=NULL,updated_at=now()
            WHERE status IN ('queued','running','ready','failed','cancelled') AND expires_at < now()""")
        conn.execute("""UPDATE nasa_explorer.jobs SET
            status=CASE WHEN attempts>=max_attempts THEN 'failed' ELSE 'queued' END,
            available_at=now(),lease_expires_at=NULL,
            error=CASE WHEN attempts>=max_attempts THEN '{"code":"worker_lease_expired"}'::jsonb ELSE error END,
            updated_at=now()
            WHERE status='running' AND lease_expires_at < now()""")
        row = conn.execute("""WITH selected AS (
                SELECT id FROM nasa_explorer.jobs
                WHERE status='queued' AND available_at<=now() AND expires_at>now()
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
            ) UPDATE nasa_explorer.jobs j SET status='running',attempts=j.attempts+1,
                progress=0,error=NULL,lease_expires_at=now()+interval '4 hours',updated_at=now()
              FROM selected WHERE j.id=selected.id
              RETURNING j.id,j.request,j.attempts,j.max_attempts""").fetchone()
    if not row:
        return None
    return dict(zip(("id", "request", "attempts", "max_attempts"), row))


def _cancelled(job_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT status,cancel_requested FROM nasa_explorer.jobs WHERE id=%s", (job_id,)).fetchone()
    return not row or row[0] == "cancelled" or row[1]


def _progress(job_id: str, progress: int, details: dict | None = None) -> None:
    with connect() as conn:
        conn.execute("""UPDATE nasa_explorer.jobs SET progress=%s,
            details=COALESCE(%s::jsonb,details),updated_at=now(),lease_expires_at=now()+interval '4 hours'
            WHERE id=%s AND status='running'""",
            (progress, json.dumps(details) if details is not None else None, job_id))


def find_source_granule(product: dict, region: dict, granule_id: str, search=earthaccess.search_data) -> dict:
    granules = search(short_name=product["collection_short_name"], concept_id=granule_id,
                      bounding_box=tuple(region["bounds_wgs84"]), count=1)
    if len(granules) != 1 or granules[0].get("meta", {}).get("concept-id") != granule_id:
        raise ValueError("Selected source granule is not available for this configured region/product")
    return granules[0]


def process_job(job: dict) -> None:
    job_id, request = job["id"], job["request"]
    products, regions = load_products(), load_regions()
    product, region = products[request["product_id"]], regions[request["region_id"]]
    # Rebuild the allow-listed request at the worker trust boundary.
    harmony_request(product, region, request["granule_id"], request["parameters"],
                    polarization=request["polarization"], layer=request["goff_layer"])
    if _cancelled(job_id):
        return _finish(job_id, "cancelled")
    auth = earthaccess.login(strategy=earthdata_auth_strategy())
    if not auth.authenticated:
        raise RuntimeError("Earthdata authentication unavailable")
    granule = find_source_granule(product, region, request["granule_id"])
    _progress(job_id, 20)
    if _cancelled(job_id):
        return _finish(job_id, "cancelled")
    output = Path("data/cache/jobs") / job_id
    manifest = fetch_harmony_cogs(product, region, request["granule_id"], request["parameters"], output,
                                  polarization=request["polarization"], layer=request["goff_layer"])
    _progress(job_id, 60)
    if _cancelled(job_id):
        return _finish(job_id, "cancelled")
    inspected = inspect_harmony_cogs(product, manifest)
    bucket = os.environ.get("S3_BUCKET", "nisar-assets")
    published = {row["parameter"]: publish(Path(row["path"]), bucket=bucket) for row in inspected}
    _progress(job_id, 80)
    if _cancelled(job_id):
        return _finish(job_id, "cancelled")
    collection, items = stac_records(product, region, manifest, inspected, granule, published)
    import_collection(collection)
    import_items(items)
    _finish(job_id, "ready", {"collection": collection["id"], "items": [item["id"] for item in items],
                               "assets": published})


def _finish(job_id: str, status: str, details: dict | None = None) -> None:
    with connect() as conn:
        conn.execute("""UPDATE nasa_explorer.jobs SET status=%s,progress=%s,
            details=COALESCE(%s::jsonb,details),error=NULL,lease_expires_at=NULL,updated_at=now()
            WHERE id=%s AND status='running'""",
            (status, 100 if status == "ready" else 0,
             json.dumps(details) if details is not None else None, job_id))


def run_once() -> bool:
    job = claim_job()
    if not job:
        return False
    try:
        process_job(job)
    except Exception as error:
        # Persist a stable code/type only; upstream exceptions may contain signed URLs.
        retry = job["attempts"] < job["max_attempts"]
        with connect() as conn:
            conn.execute("""UPDATE nasa_explorer.jobs SET status=%s,
                available_at=now()+(%s * interval '1 second'), lease_expires_at=NULL,
                error=%s::jsonb,updated_at=now() WHERE id=%s AND status='running'""",
                ("queued" if retry else "failed", min(300, 15 * 2 ** (job["attempts"] - 1)),
                 json.dumps({"code": "processing_failed", "type": type(error).__name__,
                             "http_status": getattr(error, "code", None)}), job["id"]))
    return True


def run_worker(poll_seconds: float = 5) -> None:
    while True:
        if not run_once():
            time.sleep(poll_seconds)
