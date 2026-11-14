"""Idempotent metadata-only PgSTAC ingestion and source revision history."""
import hashlib
import json

from nasa_explorer.db import connect


def _digest(item):
    return hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def import_items(items):
    """Upsert STAC items and preserve each observed CMR revision/payload."""
    if not items:
        return 0
    revisions, payloads = [], []
    for item in items:
        if not item.get("collection") or not item.get("id"):
            raise ValueError("STAC item must include collection and id")
        props = item.get("properties", {})
        revision = str(props.get("nisar:cmr_revision_id", "project-seed"))
        revisions.append((item["collection"], item["id"], revision,
                          props.get("nisar:cmr_revision_date"), _digest(item), json.dumps(item)))
        payloads.append((json.dumps(item),))
    with connect() as conn:
        conn.cursor().executemany(
            """INSERT INTO nasa_explorer.source_revisions
               (collection_id,item_id,revision_id,revision_date,payload_sha256,payload)
               VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING""", revisions)
        conn.cursor().executemany("INSERT INTO pgstac.items_staging_upsert(content) VALUES (%s::jsonb)", payloads)
    return len(items)


def import_collection(collection):
    if not collection.get("id") or not collection.get("extent"):
        raise ValueError("CMR STAC collection is missing id or extent")
    with connect() as conn:
        conn.execute("INSERT INTO pgstac.collections(content) VALUES (%s::jsonb) ON CONFLICT (id) DO UPDATE SET content=EXCLUDED.content",
                     (json.dumps(collection),))


def import_seed(path):
    items = json.loads(path.read_text())["features"]
    if not items or len({item.get("collection") for item in items}) != 1:
        raise ValueError("Seed must contain items from exactly one STAC collection")
    collection_id = items[0]["collection"]
    collection = {
        "type": "Collection", "id": collection_id,
        "stac_version": "1.0.0", "description": "NISAR L2 GCOV PROVISIONAL V1 source acquisitions and pilot comparisons.",
        "license": "other", "extent": {"spatial": {"bbox": [[-180, -90, 180, 90]]},
        "temporal": {"interval": [["2026-01-01T00:00:00Z", None]]}},
        "links": [], "providers": [{"name": "NASA CMR / ASF DAAC", "roles": ["host", "processor"],
        "url": "https://cmr.earthdata.nasa.gov/stac/"}],
        "summaries": {"nisar:collection_maturity": ["PROVISIONAL"], "product": ["nisar-gcov"]}}
    with connect() as conn:
        conn.execute("INSERT INTO pgstac.collections(content) VALUES (%s::jsonb) ON CONFLICT (id) DO UPDATE SET content=EXCLUDED.content",
                     (json.dumps(collection),))
    return import_items(items)
