import unittest
from unittest.mock import patch

import httpx

from nasa_explorer.catalog import sync


class Result:
    def __init__(self, value=None): self.value = value
    def fetchone(self): return self.value


class FakeConnection:
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def execute(self, sql, params=()):
        if sql.startswith("SELECT next_url"):
            return Result((None, None))
        if "RETURNING id" in sql:
            return Result((1,))
        return Result()


class FakeResponse:
    status_code = 200
    request = None
    def __init__(self, payload, headers=None): self.payload, self.headers = payload, headers or {}
    def raise_for_status(self): pass
    def json(self): return self.payload


def umm_record(concept_id):
    return {"meta": {"concept-id": concept_id, "revision-id": "1", "revision-date": "2026-01-01T00:00:00Z"},
            "umm": {"CollectionReference": {"ShortName": "NISAR_L2_GCOV_PROVISIONAL_V1", "Version": "1"},
                    "GranuleUR": "scene_P05023_name", "TemporalExtent": {"SingleDateTime": "2026-01-01T00:00:00Z"},
                    "SpatialExtent": {"HorizontalSpatialDomain": {"Geometry": {}}}, "RelatedUrls": []}}


class FakeClient:
    def __init__(self): self.pages, self.headers_seen = 0, []
    def get(self, url, headers=None):
        self.headers_seen.append(headers)
        if url == sync.COLLECTION_URL:
            return FakeResponse({"id": sync.COLLECTION_ID, "extent": {}})
        self.pages += 1
        if self.pages == 1:
            return FakeResponse({"items": [umm_record("G1-ASF")]}, {"CMR-Search-After": "cursor-1", "CMR-Hits": "2"})
        return FakeResponse({"items": [umm_record("G2-ASF")]}, {"CMR-Hits": "2"})


class CatalogSyncTests(unittest.TestCase):
    def test_retries_rate_limit_after_server_delay(self):
        class SequenceClient:
            def __init__(self):
                self.responses = [httpx.Response(429, headers={"Retry-After": "7"}, request=httpx.Request("GET", sync.START)),
                                  httpx.Response(200, json={"items": []}, request=httpx.Request("GET", sync.START))]
            def get(self, _url, headers=None): return self.responses.pop(0)
        delays = []
        payload, _ = sync._get_json(SequenceClient(), sync.START, delays.append)
        self.assertEqual(payload, {"items": []})
        self.assertEqual(delays, [7.0])

    def test_uses_search_after_checkpoint_to_harvest_next_page(self):
        imported, collections, client = [], [], FakeClient()
        with patch.object(sync, "connect", FakeConnection), \
             patch.object(sync, "import_items", side_effect=lambda items: imported.extend(items)), \
             patch.object(sync, "import_collection", side_effect=collections.append):
            result = sync.sync_once(client, sleep=lambda _: None)
        self.assertEqual(result, {"pages": 2, "records": 2, "status": "succeeded"})
        self.assertEqual([item["id"] for item in imported], ["G1-ASF", "G2-ASF"])
        self.assertEqual(client.headers_seen[2], {"CMR-Search-After": "cursor-1"})
        self.assertEqual(len(collections), 1)


if __name__ == "__main__":
    unittest.main()
