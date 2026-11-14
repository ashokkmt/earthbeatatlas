import unittest

from scripts.audit_cmr_granules import audit_record, cmr_record_url


class CmrAuditTests(unittest.TestCase):
    def test_exact_record_query_uses_granule_concept_id(self):
        url = cmr_record_url("G4275207669-ASF")
        self.assertIn("concept_id=G4275207669-ASF", url)
        self.assertIn("collection_concept_id=C2854338529-ASF", url)
        self.assertNotIn("granule_ur=", url)

    def test_early_scene_is_segregated_and_exact_cmr_url_uses_concept_id(self):
        umm = {
            "TemporalExtent": {"RangeDateTime": {"BeginningDateTime": "2026-05-05T02:48:59Z",
                                                   "EndingDateTime": "2026-05-05T02:49:35Z"}},
            "GranuleUR": "NISAR_L2_PR_GCOV_019_114_D_071_4005_DHDH_A_20260505T024859_20260505T024934_P05023_N_F_J_001",
            "CollectionReference": {"ShortName": "NISAR_L2_GCOV_PROVISIONAL_V1", "Version": "1"},
            "AdditionalAttributes": [{"Name": key, "Values": [value]} for key, value in {
                "PRODUCT_TYPE": "GCOV", "PRODUCT_VERSION": "1.0.11", "STACK_ID": "114_D_071",
                "TRACK_NUMBER": "114", "FRAME_NUMBER": "71", "ASCENDING_DESCENDING": "DESCENDING",
                "FREQUENCY_A_POLARIZATION": "HH+HV", "FREQUENCY_A_RANGE_BANDWIDTH": "40"}.items()],
            "SpatialExtent": {"HorizontalSpatialDomain": {"Geometry": {"GPolygons": [{
                "Boundary": {"Points": [{"Latitude": 0, "Longitude": 0},
                                         {"Latitude": 0, "Longitude": 1},
                                         {"Latitude": 1, "Longitude": 1},
                                         {"Latitude": 0, "Longitude": 0}]}}]}}},
        }
        response = {"items": [{"meta": {"collection-concept-id": "C2854338529-ASF",
                                             "revision-id": "1", "revision-date": "2026-08-10T10:40:58Z"},
                                "umm": umm}]}
        row = audit_record("Santa Rosa", "114_D_071", "2026-05-05", "G4275207669-ASF",
                           "NISAR_L2_PR_GCOV_019_114_D_071_4005_DHDH_A_20260505T024859_20260505T024934_P05023_N_F_J_001", lambda _: response)
        self.assertEqual(row["catalog_eligibility"], "segregated_pending_supplemental_evidence")
        self.assertIn("concept_id=G4275207669-ASF", row["source_record"])
        self.assertNotIn("granule_ur=", row["source_record"])
        self.assertEqual(row["attributes"]["STACK_ID"], "114_D_071")


    def test_first_general_provisional_date_is_not_segregated(self):
        umm = {
            "TemporalExtent": {"RangeDateTime": {"BeginningDateTime": "2026-06-17T00:00:00Z",
                                                   "EndingDateTime": "2026-06-17T00:00:35Z"}},
            "GranuleUR": "NISAR_L2_PR_GCOV_019_114_D_071_4005_DHDH_A_20260505T024859_20260505T024934_P05023_N_F_J_001",
            "CollectionReference": {"ShortName": "NISAR_L2_GCOV_PROVISIONAL_V1", "Version": "1"},
            "AdditionalAttributes": [{"Name": key, "Values": [value]} for key, value in {
                "PRODUCT_TYPE": "GCOV", "PRODUCT_VERSION": "1.0.11", "STACK_ID": "114_D_071",
                "TRACK_NUMBER": "114", "FRAME_NUMBER": "71", "ASCENDING_DESCENDING": "DESCENDING",
                "FREQUENCY_A_POLARIZATION": "HH+HV", "FREQUENCY_A_RANGE_BANDWIDTH": "40"}.items()],
            "SpatialExtent": {"HorizontalSpatialDomain": {"Geometry": {"GPolygons": [{
                "Boundary": {"Points": [{"Latitude": 0, "Longitude": 0},
                                         {"Latitude": 0, "Longitude": 1},
                                         {"Latitude": 1, "Longitude": 1},
                                         {"Latitude": 0, "Longitude": 0}]}}]}}},
        }
        response = {"items": [{"meta": {"collection-concept-id": "C2854338529-ASF",
                                             "revision-id": "1", "revision-date": "2026-08-10T10:40:58Z"},
                                "umm": umm}]}
        row = audit_record("Santa Rosa", "114_D_071", "2026-06-17", "G4275207669-ASF",
                           "NISAR_L2_PR_GCOV_019_114_D_071_4005_DHDH_A_20260505T024859_20260505T024934_P05023_N_F_J_001", lambda _: response)
        self.assertEqual(row["catalog_eligibility"], "eligible_for_pilot_review")


if __name__ == "__main__":
    unittest.main()
