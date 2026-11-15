import unittest

from nasa_explorer.catalog.cmr import umm_to_stac
from nasa_explorer.catalog.ingest import _normalize_polarization_flags


def record(concept_id="G1-ASF", revision="1", polarization="HH+HV"):
    return {"meta": {"concept-id": concept_id, "revision-id": revision,
                     "revision-date": "2026-08-10T10:40:58Z", "collection-concept-id": "C1-ASF"},
            "umm": {"GranuleUR": "NISAR_L2_PR_GCOV_019_114_D_071_4005_DHDH_A_20260505T024859_20260505T024934_P05023_N_F_J_001",
                    "CollectionReference": {"ShortName": "NISAR_L2_GCOV_PROVISIONAL_V1", "Version": "1"},
                    "TemporalExtent": {"RangeDateTime": {"BeginningDateTime": "2026-05-05T02:48:59Z", "EndingDateTime": "2026-05-05T02:49:35Z"}},
                    "AdditionalAttributes": [{"Name": k, "Values": [v]} for k,v in {
                        "PRODUCT_TYPE":"GCOV", "PRODUCT_VERSION":"1.0.11", "STACK_ID":"114_D_071",
                        "TRACK_NUMBER":"114", "FRAME_NUMBER":"71", "ASCENDING_DESCENDING":"DESCENDING",
                        "FREQUENCY_A_POLARIZATION":polarization, "FREQUENCY_A_RANGE_BANDWIDTH":"40"}.items()],
                    "SpatialExtent": {"HorizontalSpatialDomain": {"Geometry": {"GPolygons": [{"Boundary": {"Points": [
                        {"Latitude": 0, "Longitude": 0}, {"Latitude": 0, "Longitude": 1},
                        {"Latitude": 1, "Longitude": 1}, {"Latitude": 0, "Longitude": 0}]}}]}}},
                    "RelatedUrls": [{"Type":"GET DATA", "URL":"https://example.test/granule.h5"}]}}


class CatalogIngestTests(unittest.TestCase):
    def test_umm_record_preserves_revision_product_parameter_and_geometry(self):
        item = umm_to_stac(record())
        self.assertEqual(item["id"], "G1-ASF")
        self.assertEqual(item["collection"], "NISAR_L2_GCOV_PROVISIONAL_V1_1")
        self.assertEqual(item["bbox"], [0, 0, 1, 1])
        props = item["properties"]
        self.assertEqual(props["nisar:cmr_revision_id"], 1)
        self.assertEqual(props["nisar:crid"], "P05023")
        self.assertEqual(props["nisar:collection_maturity"], "PROVISIONAL")
        self.assertEqual(props["parameter"], "HH+HV")
        self.assertEqual(props["sar:polarizations"], ["HH", "HV"])
        self.assertTrue(props["nisar:has_hh"])
        self.assertTrue(props["nisar:has_hv"])
        self.assertFalse(props["nisar:has_vh"])
        self.assertFalse(props["nisar:has_vv"])
        self.assertEqual(props["readiness:archive"], "available")
        self.assertEqual(props["readiness:visual"], "not_prepared")

    def test_umm_revision_updates_have_distinct_stable_source_ids(self):
        one, two = umm_to_stac(record(revision="1")), umm_to_stac(record(revision="2"))
        self.assertEqual(one["id"], two["id"])
        self.assertEqual(one["properties"]["nisar:cmr_revision_id"], 1)
        self.assertEqual(two["properties"]["nisar:cmr_revision_id"], 2)

    def test_umm_vh_channel_is_not_misclassified_as_hv(self):
        props = umm_to_stac(record(polarization="VH"))["properties"]
        self.assertEqual(props["sar:polarizations"], ["VH"])
        self.assertFalse(props["nisar:has_hv"])
        self.assertTrue(props["nisar:has_vh"])

    def test_seed_ingestion_normalizes_combined_polarization_metadata(self):
        item = {"properties": {"parameter": "hh-backscatter + HV"}}
        self.assertIs(_normalize_polarization_flags(item), item)
        self.assertEqual(item["properties"]["sar:polarizations"], ["HH", "HV"])
        self.assertTrue(item["properties"]["nisar:has_hh"])
        self.assertTrue(item["properties"]["nisar:has_hv"])
        self.assertFalse(item["properties"]["nisar:has_vh"])


if __name__ == "__main__":
    unittest.main()
