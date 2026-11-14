"""Resumable NASA CMR UMM-G harvest using stateless Search-After cursors."""
import json
import time

import httpx

from nasa_explorer.catalog.cmr import umm_to_stac
from nasa_explorer.catalog.ingest import import_collection, import_items
from nasa_explorer.db import connect

SOURCE = "cmr-umm:ASF/C2854338529-ASF"
COLLECTION_ID = "NISAR_L2_GCOV_PROVISIONAL_V1_1"
COLLECTION_URL = f"https://cmr.earthdata.nasa.gov/stac/ASF/collections/{COLLECTION_ID}"
START = "https://cmr.earthdata.nasa.gov/search/granules.umm_json?collection_concept_id=C2854338529-ASF&page_size=2000&sort_key%5B%5D=start_date"


def _get_json(client, url, sleep, headers=None):
    for attempt in range(6):
        try:
            response = client.get(url, headers=headers)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(f"CMR returned HTTP {response.status_code}", request=response.request, response=response)
            response.raise_for_status()
            return response.json(), response.headers
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == 5:
                raise
            delay = min(2 ** attempt, 60)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                try:
                    delay = min(max(float(exc.response.headers.get("Retry-After", delay)), 0), 300)
                except ValueError:
                    pass
            sleep(delay)


def sync_once(client=None, sleep=time.sleep):
    own_client = client is None
    client = client or httpx.Client(timeout=90, headers={"Accept": "application/vnd.nasa.cmr.umm_results+json",
                                                         "Client-Id": "nasa-dancing-with-sars"})
    with connect() as conn:
        row = conn.execute("SELECT next_url,cursor FROM nasa_explorer.sync_state WHERE source=%s", (SOURCE,)).fetchone()
        url, cursor = row if row and row[0] else (START, None)
        run_id = conn.execute("INSERT INTO nasa_explorer.sync_runs(source,status) VALUES (%s,'running') RETURNING id", (SOURCE,)).fetchone()[0]
    pages = records = expected = 0
    try:
        collection, _ = _get_json(client, COLLECTION_URL, sleep)
        import_collection(collection)
        while url:
            headers = {"CMR-Search-After": cursor} if cursor else None
            payload, response_headers = _get_json(client, url, sleep, headers)
            records_umm = payload.get("items", [])
            items = [umm_to_stac(record) for record in records_umm]
            import_items(items)
            next_cursor = response_headers.get("CMR-Search-After")
            try:
                expected = int(response_headers.get("CMR-Hits", expected))
            except ValueError:
                pass
            next_url = START if next_cursor else None
            with connect() as conn:
                conn.execute("""INSERT INTO nasa_explorer.sync_state(source,next_url,cursor,expected_records,pages,records)
                    VALUES (%s,%s,%s,%s,1,%s) ON CONFLICT(source) DO UPDATE SET next_url=EXCLUDED.next_url,
                    cursor=EXCLUDED.cursor,expected_records=COALESCE(EXCLUDED.expected_records,nasa_explorer.sync_state.expected_records),
                    pages=nasa_explorer.sync_state.pages+1,records=nasa_explorer.sync_state.records+EXCLUDED.records""",
                             (SOURCE, next_url, next_cursor, expected or None, len(items)))
            pages += 1
            records += len(items)
            cursor, url = next_cursor, next_url
        with connect() as conn:
            conn.execute("UPDATE nasa_explorer.sync_state SET last_success=now(),last_error=NULL,next_url=NULL,cursor=NULL WHERE source=%s", (SOURCE,))
            conn.execute("UPDATE nasa_explorer.sync_runs SET status='succeeded',finished_at=now(),pages=%s,records=%s WHERE id=%s", (pages, records, run_id))
        return {"pages": pages, "records": records, "status": "succeeded"}
    except Exception as exc:
        with connect() as conn:
            conn.execute("""INSERT INTO nasa_explorer.sync_state(source,last_error) VALUES (%s,%s)
                ON CONFLICT(source) DO UPDATE SET last_error=EXCLUDED.last_error""", (SOURCE, str(exc)))
            conn.execute("UPDATE nasa_explorer.sync_runs SET status='failed',finished_at=now(),pages=%s,records=%s,error=%s WHERE id=%s", (pages, records, str(exc), run_id))
        raise
    finally:
        if own_client:
            client.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-hours", type=float, default=24)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            print(json.dumps(sync_once()), flush=True)
        except Exception as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}), flush=True)
        if args.once:
            break
        time.sleep(max(args.interval_hours, 1) * 3600)
