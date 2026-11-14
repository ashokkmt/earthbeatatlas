"""Create a compact STAC ItemCollection from the immutable pilot release."""

import hashlib
import json
from pathlib import Path


def _checksum(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"1220{digest}"


def _asset(href, local_path, media_type, roles):
    return {"href": href, "type": media_type, "roles": roles,
            "file:checksum": _checksum(local_path)}


def _base_item(identifier, geometry, properties, links, assets):
    coordinates = geometry["coordinates"][0]
    return {"type": "Feature", "stac_version": "1.0.0", "stac_extensions": [
        "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
        "https://stac-extensions.github.io/sar/v1.0.0/schema.json",
        "https://stac-extensions.github.io/file/v2.1.0/schema.json"],
        "id": identifier, "geometry": geometry,
        "bbox": [min(point[0] for point in coordinates), min(point[1] for point in coordinates),
                 max(point[0] for point in coordinates), max(point[1] for point in coordinates)],
        "properties": properties,
        "links": links, "assets": assets}


def export_stac(release_dir: Path, catalog_path: Path, audit_path: Path, regions: dict, products: dict):
    audit = json.loads(audit_path.read_text())
    if len(audit["records"]) != 12:
        raise ValueError("CMR audit must contain all 12 pinned granules")
    sources = {record["concept_id"]: record for record in audit["records"]}
    product = products["nisar-gcov"]
    items = []
    observations = {}
    for slug, region in ((entry["slug"], entry) for entry in regions.values()):
        manifest = json.loads((release_dir / slug / "manifest.json").read_text())
        west, south, east, north = region["bounds_wgs84"]
        geometry = {"type": "Polygon", "coordinates": [[[west, south], [east, south],
                                                            [east, north], [west, north], [west, south]]]}
        for observation in manifest["observations"]:
            source = sources[observation["granule_id"]]
            is_eligible = source["catalog_eligibility"] == "eligible_for_pilot_review"
            path_prefix = f"../../../releases/{release_dir.name}/"
            source_link = {"rel": "via", "href": source["source_record"], "type": "application/vnd.nasa.cmr.umm+json"}
            properties = {
                "datetime": source["acquisition_start_utc"],
                "start_datetime": source["acquisition_start_utc"],
                "end_datetime": source["acquisition_end_utc"],
                "proj:epsg": region["analysis_epsg"], "proj:shape": manifest_shape(manifest),
                "proj:transform": manifest["transform"],
                "sar:instrument_mode": source["attributes"]["ACQUISITION_MODE"],
                "sar:frequency_band": product["frequency_band"],
                "sar:polarizations": [observation["polarization"]],
                "nisar:frequency": product["frequency"],
                "nisar:collection_concept_id": source["collection_concept_id"],
                "nisar:collection_version": source["collection_version"],
                "nisar:cmr_collection_revision_id": audit["collection_revision_id"],
                "nisar:cmr_collection_revision_date": audit["collection_revision_date"],
                "nisar:collection_maturity": source["maturity"], "nisar:crid": source["crid"],
                "nisar:product_version": source["attributes"]["PRODUCT_VERSION"],
                "nisar:track": source["attributes"]["TRACK_NUMBER"],
                "nisar:frame": source["attributes"]["FRAME_NUMBER"],
                "nisar:stack_id": source["attributes"]["STACK_ID"],
                "nisar:orbit_direction": source["attributes"]["ASCENDING_DESCENDING"],
                "nisar:cmr_revision_id": source["cmr_revision_id"],
                "nisar:cmr_revision_date": source["cmr_revision_date"],
                "product": observation["dataset_id"], "parameter": observation["parameter"],
                "unit": observation["units"], "gsd": manifest["cell_size_m"],
                "quality:state": "project_qa_screened",
                "readiness:archive": "available", "readiness:visual": "ready",
                "readiness:reviewed_change": "not_reviewed",
                "readiness:catalog": "eligible_for_pilot_review" if is_eligible else "segregated",
                "nisar:supplemental_series_status": source["supplemental_series_status"],
                "nisar:catalog_eligibility": source["catalog_eligibility"],
                "nisar:project_processor_version": "phase3-release-v1",
                "nisar:source_granule_id": observation["granule_id"],
                "nisar:source_footprint": source["geometry"],
                "nisar:analysis_geometry_scope": "configured_aoi_bbox",
                "nisar:valid_cells": observation["valid_cells"],
                "nisar:coverage": observation["coverage"],
                "nisar:raw_grid_encoding": manifest["analysis_grid_encoding"],
            }
            raw = (release_dir / observation["assets"]["values_f32"]).resolve()
            png = (release_dir / observation["assets"]["map_png"]).resolve()
            assets = {"data": _asset(path_prefix + observation["assets"]["values_f32"], raw,
                                      "application/octet-stream", ["data"]),
                      "visual": _asset(path_prefix + observation["assets"]["map_png"], png,
                                       "image/png", ["overview"])}
            if source["source_data_url"]:
                assets["source-data"] = {"href": source["source_data_url"], "type": "application/x-hdf5",
                                          "roles": ["data", "source"], "title": "Original NISAR source granule"}
            item = _base_item(observation["id"], geometry, properties, [source_link], assets)
            item["collection"] = f"{source['collection_short_name']}_{source['collection_version']}"
            items.append(item)
            observations[(slug, observation["polarization"], observation["utc_date"])] = item
        for pair in manifest["pairs"]:
            before = observations[(slug, pair["polarization"], pair["earlier_date"])]
            after = observations[(slug, pair["polarization"], pair["later_date"])]
            start = before["properties"]["datetime"]
            end = after["properties"]["datetime"]
            pair_id = f"{slug}:nisar-gcov:{pair['polarization'].lower()}-difference:{pair['earlier_date']}:{pair['later_date']}"
            source_rows = [sources[before["properties"]["nisar:source_granule_id"]],
                           sources[after["properties"]["nisar:source_granule_id"]]]
            eligible = all(s["catalog_eligibility"] == "eligible_for_pilot_review" for s in source_rows)
            pair_props = dict(before["properties"])
            pair_props.update({"datetime": None, "start_datetime": start, "end_datetime": end,
                               "parameter": f"{pair['polarization'].lower()}-backscatter-difference",
                               "nisar:source_footprints": [s["geometry"] for s in source_rows],
                               "nisar:source_granule_ids": [s["concept_id"] for s in source_rows],
                               "nisar:source_observation_ids": [before["id"], after["id"]],
                               "quality:state": "project_qa_screened",
                               "readiness:visual": "ready", "readiness:reviewed_change": "not_reviewed",
                               "readiness:catalog": "eligible_for_pilot_review" if eligible else "segregated",
                               "nisar:source_lineage": "later_date_minus_earlier_date",
                               "nisar:valid_pair_cells": pair["valid_pair_cells"],
                               "nisar:pair_summary": pair["summary"]})
            pair_props.pop("nisar:source_granule_id")
            pair_props.pop("nisar:source_footprint")
            png = (release_dir / pair["map_png"]).resolve()
            pair_item = _base_item(pair_id, geometry, pair_props,
                                   [{"rel": "via", "href": s["source_record"],
                                     "type": "application/vnd.nasa.cmr.umm+json"} for s in source_rows],
                                   {"visual": _asset(path_prefix + pair["map_png"], png,
                                                     "image/png", ["overview"])})
            pair_item["collection"] = before["collection"]
            items.append(pair_item)
    if len(items) != 52:
        raise ValueError(f"Expected 22 acquisition and 30 pair items; got {len(items)}")
    output = {"type": "FeatureCollection", "stac_version": "1.0.0",
              "links": [], "features": items}
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(output, indent=2) + "\n")
    return {"acquisitions": 22, "pairs": 30, "items": len(items)}


def export_metadata_seed(catalog_path: Path, seed_path: Path):
    """Write catalog metadata without local raster/preview links for clean installs."""
    catalog = json.loads(catalog_path.read_text())
    for item in catalog["features"]:
        item["assets"] = {key: value for key, value in item.get("assets", {}).items()
                          if key == "source-data" and value.get("href", "").startswith("https://")}
        item["properties"]["readiness:visual"] = "not_prepared"
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(json.dumps(catalog, indent=2) + "\n")
    return len(catalog["features"])


def manifest_shape(manifest):
    return [manifest["height"], manifest["width"]]
