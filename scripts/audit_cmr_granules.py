"""Audit pinned pilot granules against the live NASA CMR UMM-G endpoint."""

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = "C2854338529-ASF"
CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
PROVISIONAL_START = "2026-06-17"


def cmr_record_url(concept_id):
    query = urllib.parse.urlencode({"concept_id": concept_id,
                                    "collection_concept_id": COLLECTION})
    return f"{CMR}?{query}"


def _attribute(umm, name):
    for item in umm.get("AdditionalAttributes", []):
        if item.get("Name") == name:
            return item.get("Values", [None])[0]
    return None


def _footprint(umm):
    polygons = umm["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"].get("GPolygons", [])
    if not polygons:
        return None
    rings = [[[point["Longitude"], point["Latitude"]]
              for point in polygon["Boundary"]["Points"]] for polygon in polygons]
    return {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}


def _pins():
    rows = json.loads((ROOT / "config/source_records/nisar-gcov-pilot.json").read_text())
    if len(rows) != 12:
        raise ValueError(f"Expected 12 pinned source rows, found {len(rows)}")
    return [(r["region"], r["stack_id"], r["date"], r["concept_id"], r["granule_ur"]) for r in rows]


def audit_record(region, stack, expected_date, concept_id, expected_ur, fetch):
    record = fetch(cmr_record_url(concept_id))
    if len(record.get("items", [])) != 1:
        raise ValueError(f"CMR expected exactly one record for {concept_id}")
    item = record["items"][0]
    meta, umm = item["meta"], item["umm"]
    time = umm["TemporalExtent"]["RangeDateTime"]
    start = time["BeginningDateTime"]
    if start[:10] != expected_date or umm["GranuleUR"] != expected_ur:
        raise ValueError(f"Pinned date/name mismatch for {concept_id}")
    maturity = umm["CollectionReference"]["ShortName"].split("_")[-2]
    attributes = {key: _attribute(umm, key) for key in
                  ("PRODUCT_TYPE", "PRODUCT_VERSION", "STACK_ID", "TRACK_NUMBER",
                   "FRAME_NUMBER", "ASCENDING_DESCENDING", "FREQUENCY_A_POLARIZATION",
                   "FREQUENCY_A_RANGE_BANDWIDTH")}
    mode_match = re.search(r"_(\d{4})_[A-Z]{4}_[AB]_", umm["GranuleUR"])
    if not mode_match:
        raise ValueError(f"Missing acquisition mode in CMR native name for {concept_id}")
    attributes["ACQUISITION_MODE"] = mode_match.group(1)
    if meta.get("collection-concept-id") != COLLECTION or maturity != "PROVISIONAL":
        raise ValueError(f"Unexpected collection/maturity for {concept_id}")
    if "P05023" not in umm["GranuleUR"] or attributes["PRODUCT_VERSION"] != "1.0.11":
        raise ValueError(f"Unexpected CRID or product version for {concept_id}")
    if attributes["STACK_ID"] != stack or attributes["PRODUCT_TYPE"] != "GCOV":
        raise ValueError(f"Unexpected stack/product for {concept_id}")
    geometry = _footprint(umm)
    if not geometry:
        raise ValueError(f"CMR source footprint is missing for {concept_id}")
    source_url = cmr_record_url(concept_id)
    source_data_url = next((link["URL"] for link in umm.get("RelatedUrls", [])
                            if link.get("Type") == "GET DATA" and link.get("URL", "").startswith("https://")), None)
    return {
        "region": region, "stack_id": stack, "expected_date": expected_date,
        "concept_id": concept_id, "granule_ur": umm["GranuleUR"],
        "collection_concept_id": meta["collection-concept-id"],
        "collection_short_name": umm["CollectionReference"]["ShortName"],
        "collection_version": umm["CollectionReference"]["Version"],
        "cmr_revision_id": int(meta["revision-id"]), "cmr_revision_date": meta["revision-date"],
        "acquisition_start_utc": start, "acquisition_end_utc": time["EndingDateTime"],
        "geometry": geometry, "attributes": attributes,
        "maturity": maturity, "crid": "P05023",
        "source_data_url": source_data_url,
        "supplemental_series_status": "unverified_early_series" if expected_date < PROVISIONAL_START else "not_applicable",
        "catalog_eligibility": "segregated_pending_supplemental_evidence" if expected_date < PROVISIONAL_START else "eligible_for_pilot_review",
        "source_record": source_url,
    }


def run(fetch=None):
    def live_fetch(url):
        with urllib.request.urlopen(url, timeout=45) as response:
            return json.load(response)
    fetch = fetch or live_fetch
    collection_query = urllib.parse.urlencode({"concept_id": COLLECTION})
    collection_result = fetch(f"https://cmr.earthdata.nasa.gov/search/collections.umm_json?{collection_query}")
    if len(collection_result.get("items", [])) != 1:
        raise ValueError(f"CMR expected exactly one collection record for {COLLECTION}")
    collection_item = collection_result["items"][0]
    audited = [audit_record(region, stack, date, concept, name, fetch)
               for region, stack, date, concept, name in _pins()]
    return {"collection_concept_id": COLLECTION,
            "collection_revision_id": int(collection_item["meta"]["revision-id"]),
            "collection_revision_date": collection_item["meta"]["revision-date"],
            "collection_short_name": collection_item["umm"]["ShortName"],
            "collection_version": collection_item["umm"]["Version"],
            "inventory_scope": "12 pinned source IDs only; this is not a complete frame search",
            "known_mission_data_gaps_utc": [{
                "start": "2026-07-27T22:03:25Z", "end": "2026-08-10T00:55:27Z",
                "source": "https://nisar-docs.asf.alaska.edu/availability-overview/"}],
            "audited_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "records": audited}


def main():
    result = run()
    target = ROOT / "data/cache/catalog-seed/cmr-audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Audited {len(result['records'])} CMR records -> {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
