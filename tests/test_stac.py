import json
import tempfile
import unittest
from pathlib import Path

from nasa_explorer.catalog.stac import _asset, _base_item, export_metadata_seed


class StacContractTests(unittest.TestCase):
    def test_item_has_geojson_bbox_and_stac_identity(self):
        geom = {"type": "Polygon", "coordinates": [[[-2, 3], [4, 3], [4, 8], [-2, 8], [-2, 3]]]}
        item = _base_item("scene-1", geom, {"datetime": "2026-01-01T00:00:00Z"}, [], {})
        self.assertEqual(item["type"], "Feature")
        self.assertEqual(item["stac_version"], "1.0.0")
        self.assertEqual(item["bbox"], [-2, 3, 4, 8])

    def test_local_asset_uses_stac_file_checksum_multihash(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "asset.bin"
            path.write_bytes(b"pilot")
            asset = _asset("../asset.bin", path, "application/octet-stream", ["data"])
        self.assertEqual(asset["href"], "../asset.bin")
        self.assertTrue(asset["file:checksum"].startswith("1220"))
        self.assertEqual(len(asset["file:checksum"]), 68)

    def test_metadata_seed_removes_local_pixels_and_hides_visual_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / "items.json", Path(temp) / "seed.json"
            source.write_text('{"type":"FeatureCollection","features":[{"id":"x","assets":{"visual":{"href":"../../map.png"},"source-data":{"href":"https://cmr.example/data","roles":["data"]}},"properties":{"readiness:visual":"ready"}}]}')
            self.assertEqual(export_metadata_seed(source, target), 1)
            item = json.loads(target.read_text())["features"][0]
        self.assertEqual(list(item["assets"]), ["source-data"])
        self.assertEqual(item["properties"]["readiness:visual"], "not_prepared")
