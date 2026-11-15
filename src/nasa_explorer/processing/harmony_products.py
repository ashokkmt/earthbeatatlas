"""Validate selected Harmony COGs without changing native values or flags."""

from pathlib import Path

import numpy as np
import rasterio

from nasa_explorer.processing.gcov import sha256


def _variable_suffix(variable: str, polarization: str, layer: str) -> str:
    return "science_" + variable.format(polarization=polarization, layer=layer).split("/science/", 1)[1].replace("/", "_")


def inspect_harmony_cogs(product: dict, manifest: dict) -> list[dict]:
    """Match every selected parameter to one COG and report native raster metadata."""
    parameters = manifest.get("parameters", [])
    if not parameters or len(parameters) > 6 or len(parameters) != len(set(parameters)):
        raise ValueError("Manifest must select 1–6 unique parameters")
    configured = product.get("parameters", {})
    if set(parameters) - set(configured):
        raise ValueError("Manifest contains a parameter absent from the product configuration")
    polarization = manifest.get("polarization", "HH")
    layer = manifest.get("goff_layer", "layer1") or "layer1"
    files = [Path(path) for path in manifest.get("local_files", [])]
    if len(files) != len(parameters) or len(files) != len(set(files)):
        raise ValueError("Harmony output count does not match selected parameters")

    results = []
    reference_grid = None
    for parameter in parameters:
        suffix = _variable_suffix(configured[parameter]["harmony_variable"], polarization, layer)
        matches = [path for path in files if path.name.endswith(suffix + "_subsetted.tif")]
        if len(matches) != 1:
            raise ValueError(f"Expected one Harmony COG for {parameter}; found {len(matches)}")
        path = matches[0]
        with rasterio.open(path) as dataset:
            if dataset.driver != "GTiff" or dataset.count != 1 or dataset.crs is None:
                raise ValueError(f"Unsupported Harmony raster structure: {path.name}")
            if dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") != "COG":
                raise ValueError(f"Harmony output is not a Cloud Optimized GeoTIFF: {path.name}")
            grid = (dataset.crs.to_string(), dataset.width, dataset.height, tuple(dataset.transform)[:6])
            if reference_grid is None:
                reference_grid = grid
            elif grid != reference_grid:
                raise ValueError("Selected layers do not share one native grid")
            data = dataset.read(1, masked=True)
            valid = data.compressed()
            if valid.size == 0:
                raise ValueError(f"Harmony raster has no valid pixels: {path.name}")
            if np.issubdtype(valid.dtype, np.floating) and not np.isfinite(valid).all():
                raise ValueError(f"Harmony raster contains unmasked non-finite values: {path.name}")
            digest = sha256(path)
            metadata = {
                "parameter": parameter, "path": str(path), "sha256": digest,
                "crs": dataset.crs.to_string(), "shape": [dataset.height, dataset.width],
                "transform": list(dataset.transform)[:6], "dtype": dataset.dtypes[0],
                "nodata": (float(dataset.nodata) if dataset.nodata is not None and np.isfinite(dataset.nodata)
                           else None), "valid_pixels": int(valid.size),
                "minimum": float(np.min(valid)), "maximum": float(np.max(valid)),
                "unit": configured[parameter].get("unit", "unspecified"),
            }
            results.append(metadata)
    return results


def display_state(product: dict, parameter: str) -> tuple[str, str]:
    """Return a conservative display state and warning; raw input remains unchanged."""
    if product["dataset_id"] == "nisar-goff" and parameter == "slant_range_offset":
        return "withheld", "Source unit metadata conflicts; do not render as a physical offset."
    if product["dataset_id"] == "nisar-goff" and parameter == "valid_data_mask":
        return "withheld", "Mask category meanings are not qualified; do not filter or classify from raw codes."
    if product["dataset_id"] == "nisar-goff" and parameter == "along_track_offset":
        return "raw_observation", "Native offset in source units; no SNR/mask screening or velocity interpretation applied."
    if product["dataset_id"] == "nisar-gunw" and parameter == "valid_data_mask":
        return "withheld", "Mask encoding has not been interpreted; raw category values only."
    if product["dataset_id"] == "nisar-sme2":
        return "experimental", "PROVISIONAL SME2; preserve and expose quality flags."
    return "raw_observation", "Native source layer; not a reviewed change analysis."


def stac_records(product: dict, region: dict, manifest: dict, inspected: list[dict],
                 granule: dict, published: dict[str, dict]) -> tuple[dict, list[dict]]:
    """Build one immutable STAC observation per native source layer."""
    import re

    umm = granule["umm"]
    meta = granule["meta"]
    temporal = umm["TemporalExtent"]["RangeDateTime"]
    start = temporal["BeginningDateTime"]
    end = temporal["EndingDateTime"]
    collection_ref = umm["CollectionReference"]
    collection_id = f"{collection_ref['ShortName']}_{collection_ref['Version']}"
    granule_id = meta["concept-id"]
    crid = re.search(r"P\d{5}", umm.get("GranuleUR", ""))
    common = {
        "start_datetime": start, "end_datetime": end,
        "datetime": None if any(product["parameters"][p].get("pair_required") for p in manifest["parameters"]) else start,
        "product": product["dataset_id"], "nisar:collection_concept_id": meta["collection-concept-id"],
        "nisar:collection_maturity": product["maturity"],
        "nisar:crid": crid.group(0) if crid else "unknown",
        "nisar:source_granule_id": granule_id,
        "nisar:product_version": next((a["Values"][0] for a in umm.get("AdditionalAttributes", [])
                                         if a.get("Name") == "PRODUCT_VERSION" and a.get("Values")), None),
        "readiness:archive": "available", "readiness:reviewed_change": "not_reviewed",
        "readiness:catalog": "source_subset_qa", "quality:state": "source_quality_review_required",
    }
    items = []
    for layer in inspected:
        parameter = layer["parameter"]
        visual_state, warning = display_state(product, parameter)
        properties = {**common, "parameter": parameter, "unit": layer["unit"],
                      "nisar:visualization": product["parameters"][parameter]["visualization"],
                      "quality:state": "experimental_provisional" if product["dataset_id"] == "nisar-sme2" else common["quality:state"],
                      "readiness:visual": "withheld" if visual_state == "withheld" else "ready",
                      "nisar:display_warning": warning}
        extension = ["https://stac-extensions.github.io/projection/v1.1.0/schema.json",
                     "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
                     "https://stac-extensions.github.io/file/v2.1.0/schema.json"]
        band = {"data_type": layer["dtype"], "unit": layer["unit"], "statistics": {
            "minimum": layer["minimum"], "maximum": layer["maximum"]}}
        if layer["nodata"] is not None:
            band["nodata"] = layer["nodata"]
        item = {
            "type": "Feature", "stac_version": "1.0.0", "stac_extensions": extension,
            "id": f"{granule_id}:{parameter}", "collection": collection_id,
            "geometry": {"type": "Polygon", "coordinates": [[
                [region["bounds_wgs84"][0], region["bounds_wgs84"][1]],
                [region["bounds_wgs84"][2], region["bounds_wgs84"][1]],
                [region["bounds_wgs84"][2], region["bounds_wgs84"][3]],
                [region["bounds_wgs84"][0], region["bounds_wgs84"][3]],
                [region["bounds_wgs84"][0], region["bounds_wgs84"][1]],
            ]]},
            "bbox": list(region["bounds_wgs84"]), "properties": properties, "links": [],
            "assets": {"data": {
                "href": published[parameter]["href"],
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data"], "file:checksum": "1220" + layer["sha256"],
                "file:size": Path(layer["path"]).stat().st_size,
                "proj:epsg": rasterio.crs.CRS.from_string(layer["crs"]).to_epsg(),
                "proj:shape": layer["shape"], "proj:transform": layer["transform"],
                "raster:bands": [band],
            }},
        }
        items.append(item)
    collection = {
        "type": "Collection", "id": collection_id, "stac_version": "1.0.0",
        "description": f"{product['product_short_name']} native source-layer subsets; provisional project QA assets.",
        "license": "other", "extent": {
            "spatial": {"bbox": [[-180.0, -90.0, 180.0, 90.0]]},
            "temporal": {"interval": [["2025-10-01T00:00:00Z", None]]},
        }, "links": [],
        "providers": [{"name": "NASA CMR / ASF DAAC", "roles": ["host", "processor"],
                       "url": "https://cmr.earthdata.nasa.gov/stac/"}],
        "summaries": {"product": [product["dataset_id"]],
                      "nisar:collection_maturity": [product["maturity"]],
                      "nisar:crid": [crid.group(0) if crid else "unknown"]},
    }
    return collection, items
