"""Bounded, public-processing job API for configured NISAR AOIs."""

import hashlib
import json
import re
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from nasa_explorer.catalog.registry import load_products, load_regions
from nasa_explorer.db import connect
from nasa_explorer.processing.harmony import harmony_request

router = APIRouter(prefix="/api/v1/jobs", tags=["processing-jobs"])


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=40)
    region_id: str = Field(min_length=1, max_length=40)
    granule_id: str = Field(pattern=r"^G[0-9]+-ASF$", max_length=40)
    parameters: list[str] = Field(min_length=1, max_length=6)
    polarization: str = Field(default="HH", pattern=r"^(HH|VV)$")
    goff_layer: str = Field(default="layer1", pattern=r"^layer[1-3]$")


def _key_digest(key: str | None) -> str:
    if key is None or not re.fullmatch(r"[A-Za-z0-9._~-]{32,128}", key):
        raise HTTPException(400, "A 32–128 character Idempotency-Key header is required")
    return hashlib.sha256(key.encode()).hexdigest()


def enqueue(body: JobRequest, idempotency_key: str) -> tuple[dict, bool]:
    products, regions = load_products(), load_regions()
    product = products.get(body.product_id)
    region = regions.get(body.region_id)
    if not product or not region:
        raise HTTPException(404, "Unknown product or configured region")
    if len(set(body.parameters)) != len(body.parameters):
        raise HTTPException(422, "Parameters must be unique")
    try:
        harmony_request(product, region, body.granule_id, body.parameters,
                        polarization=body.polarization, layer=body.goff_layer)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    owner = _key_digest(idempotency_key)
    request = body.model_dump(mode="json")
    request_sha256 = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(5270361)")
        existing = conn.execute(
            "SELECT id,request_sha256,status,progress,attempts,details,updated_at FROM nasa_explorer.jobs WHERE idempotency_sha256=%s",
            (owner,),
        ).fetchone()
        if existing:
            if existing[1] != request_sha256:
                raise HTTPException(409, "Idempotency-Key was already used for a different request")
            return dict(zip(("id", "request_sha256", "status", "progress", "attempts", "details", "updated_at"), existing)), False
        active = conn.execute("SELECT count(*) FROM nasa_explorer.jobs WHERE status IN ('queued','running')").fetchone()[0]
        recent = conn.execute("SELECT count(*) FROM nasa_explorer.jobs WHERE created_at>now()-interval '24 hours'").fetchone()[0]
        if active >= 5 or recent >= 20:
            raise HTTPException(429, "Processing queue is at its bounded demo limit; retry later")
        row = conn.execute(
            "INSERT INTO nasa_explorer.jobs(id,kind,status,request,request_sha256,idempotency_sha256,progress,max_attempts) "
            "VALUES (%s,'harmony_subset','queued',%s::jsonb,%s,%s,0,3) "
            "RETURNING id,request_sha256,status,progress,attempts,details,updated_at",
            (str(uuid.uuid4()), json.dumps(request), request_sha256, owner),
        ).fetchone()
    return dict(zip(("id", "request_sha256", "status", "progress", "attempts", "details", "updated_at"), row)), True


def _owned(job_id: str, key: str | None):
    digest = _key_digest(key)
    with connect() as conn:
        row = conn.execute(
            "SELECT id,kind,status,progress,attempts,details,error,updated_at,cancel_requested "
            "FROM nasa_explorer.jobs WHERE id=%s AND idempotency_sha256=%s", (job_id, digest),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return dict(zip(("id", "kind", "status", "progress", "attempts", "details", "error", "updated_at", "cancel_requested"), row))


@router.post("", status_code=202)
def submit(body: JobRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    record, created = enqueue(body, idempotency_key)
    record.pop("request_sha256", None)
    record["created"] = created
    return record


@router.get("/{job_id}")
def status(job_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return _owned(job_id, idempotency_key)


@router.post("/{job_id}/cancel")
def cancel(job_id: str, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    owner = _key_digest(idempotency_key)
    with connect() as conn:
        row = conn.execute(
            "UPDATE nasa_explorer.jobs SET status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END, "
            "cancel_requested=CASE WHEN status='running' THEN true ELSE cancel_requested END, updated_at=now() "
            "WHERE id=%s AND idempotency_sha256=%s AND status IN ('queued','running') "
            "RETURNING id,status,progress,attempts,details,cancel_requested,updated_at", (job_id, owner),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Active job not found")
    return dict(zip(("id", "status", "progress", "attempts", "details", "cancel_requested", "updated_at"), row))
