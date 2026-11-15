import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.shutil import copy as rio_copy

from nasa_explorer.catalog.registry import load_products
from nasa_explorer.api.main import app
from nasa_explorer.api.jobs import JobRequest
from nasa_explorer.processing.harmony import harmony_request
from nasa_explorer.processing.harmony import harmony_bearer_token
from nasa_explorer.processing.harmony_products import display_state, inspect_harmony_cogs
from nasa_explorer.processing.jobs import find_source_granule
from scripts.audit_source_coverage import audit
from scripts.prepare_product_sample import earthdata_auth_strategy


class ProductProcessingTests(unittest.TestCase):
    def test_all_four_product_families_have_explicit_provenance_and_parameters(self):
        products = load_products()
        self.assertEqual(set(products), {"nisar-gcov", "nisar-gunw", "nisar-goff", "nisar-sme2"})
        for product in products.values():
            self.assertTrue(product.get("collection_concept_id") or product.get("collection_short_name"))
            self.assertTrue(product.get("channels") or product.get("parameters"))
        self.assertEqual(products["nisar-sme2"]["workflow_state"], "experimental_provisional")
        self.assertEqual(products["nisar-gunw"]["collection_concept_id"], "C2854335566-ASF")
        self.assertEqual(products["nisar-goff"]["collection_concept_id"], "C2854341702-ASF")
        self.assertEqual(products["nisar-sme2"]["collection_concept_id"], "C2854344945-ASF")

    def test_source_audit_is_bounded_and_keeps_regions_and_products_separate(self):
        calls = []

        def fake_search(**kwargs):
            calls.append(kwargs)
            return []

        result = audit("2026-01-01", "2026-02-01", limit=2, search=fake_search)
        self.assertEqual(len(calls), 16)
        self.assertTrue(all(call["count"] == 2 for call in calls))
        self.assertEqual(result["records"], [])
        with self.assertRaises(ValueError):
            audit("2026-02-01", "2026-01-01", search=fake_search)

    def test_ingestion_uses_token_when_set_otherwise_local_netrc(self):
        self.assertEqual(earthdata_auth_strategy("fake-token"), "environment")
        self.assertEqual(earthdata_auth_strategy(""), "netrc")
        self.assertEqual(harmony_bearer_token(SimpleNamespace(token={"access_token": "fake-token"})), "fake-token")

    def test_product_endpoint_exposes_source_and_withheld_states(self):
        response = TestClient(app).get("/api/v1/products")
        self.assertEqual(response.status_code, 200)
        products = {product["id"]: product for product in response.json()}
        self.assertEqual(set(products), {"nisar-gcov", "nisar-gunw", "nisar-goff", "nisar-sme2"})
        self.assertEqual(products["nisar-gcov"]["workflow_state"], "ready_pilot")
        self.assertEqual(products["nisar-gunw"]["workflow_state"], "source_raster_qa_required")
        self.assertEqual(products["nisar-sme2"]["workflow_state"], "experimental_provisional")

    def test_public_api_has_no_earthdata_oauth_dependency(self):
        paths = app.openapi()["paths"]
        self.assertNotIn("/auth/earthdata/login", paths)
        self.assertIn("/api/v1/products", paths)

    def test_case_endpoint_exposes_only_packaged_configured_context_assets(self):
        client = TestClient(app)
        cases = {item["id"]: item for item in client.get("/api/v1/cases").json()}
        santa_rosa = cases["Santa Rosa"]
        self.assertEqual(santa_rosa["full_name"], "Santa Rosa Island, California")
        self.assertTrue(santa_rosa["context_layers"][0]["asset_url"].endswith("santa-rosa-perimeter-clipped.geojson"))
        response = client.get(santa_rosa["context_layers"][0]["asset_url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "FeatureCollection")
        self.assertEqual(client.get("/api/v1/cases/Santa%20Rosa/context/../../.env").status_code, 404)

    def test_bounded_job_contract_is_exposed_and_rejects_extra_scope(self):
        paths = app.openapi()["paths"]
        self.assertIn("/api/v1/jobs", paths)
        self.assertIn("/api/v1/jobs/{job_id}/cancel", paths)
        payload = {"product_id": "nisar-gunw", "region_id": "Colusa", "granule_id": "G123-ASF",
                   "parameters": ["coherence"], "unexpected_bbox": [-180, -90, 180, 90]}
        with self.assertRaises(Exception):
            JobRequest.model_validate(payload)

    def test_job_source_lookup_uses_exact_granule_and_configured_aoi(self):
        product = load_products()["nisar-gunw"]
        region = __import__("nasa_explorer.catalog.registry", fromlist=["load_regions"]).load_regions()["Colusa"]
        calls = []
        def search(**kwargs):
            calls.append(kwargs)
            return [{"meta": {"concept-id": "G123-ASF"}}]
        result = find_source_granule(product, region, "G123-ASF", search)
        self.assertEqual(result["meta"]["concept-id"], "G123-ASF")
        self.assertEqual(calls[0]["bounding_box"], tuple(region["bounds_wgs84"]))
        self.assertEqual(calls[0]["count"], 1)

    def test_harmony_request_selects_only_configured_product_variables_and_aoi(self):
        products = load_products()
        regions = __import__("nasa_explorer.catalog.registry", fromlist=["load_regions"]).load_regions()
        request = harmony_request(products["nisar-gunw"], regions["Colusa"], "G123-ASF",
                                  ["unwrapped_phase", "coherence"])
        self.assertEqual(request.collection.id, "C2854335566-ASF")
        self.assertEqual(request.granule_id, ["G123-ASF"])
        self.assertEqual(request.variables, [
            "/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/unwrappedPhase",
            "/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/coherenceMagnitude",
        ])
        with self.assertRaises(ValueError):
            harmony_request(products["nisar-gunw"], regions["Colusa"], "G123-ASF", ["not_a_layer"])

    def test_product_cog_inspection_preserves_raw_layers_and_withholds_uncertain_fields(self):
        product = load_products()["nisar-goff"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = []
            for variable, values in (("alongTrackOffset", np.arange(16, dtype="float32").reshape(4, 4)),
                                     ("slantRangeOffset", np.arange(16, dtype="float32").reshape(4, 4))):
                source, output = root / f"{variable}.src.tif", root / f"x_science_LSAR_GOFF_grids_frequencyA_pixelOffsets_HH_layer1_{variable}_subsetted.tif"
                with rasterio.open(source, "w", driver="GTiff", width=4, height=4, count=1,
                                   dtype="float32", crs="EPSG:3031", transform=from_origin(0, 320, 80, 80),
                                   nodata=float("nan")) as dataset:
                    dataset.write(values, 1)
                rio_copy(source, output, driver="COG", blocksize=128, overview_resampling="nearest")
                outputs.append(str(output))
            report = inspect_harmony_cogs(product, {"parameters": ["along_track_offset", "slant_range_offset"],
                                                     "local_files": outputs, "polarization": "HH", "goff_layer": "layer1"})
        self.assertEqual([row["valid_pixels"] for row in report], [16, 16])
        self.assertIsNone(report[0]["nodata"])
        self.assertEqual(report[1]["unit"].startswith("unverified"), True)
        self.assertEqual(display_state(product, "slant_range_offset")[0], "withheld")
        self.assertEqual(display_state(product, "valid_data_mask")[0], "withheld")
        self.assertEqual(display_state(product, "along_track_offset")[0], "raw_observation")


if __name__ == "__main__":
    unittest.main()
