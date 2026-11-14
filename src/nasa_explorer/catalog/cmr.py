"""Map authoritative NASA CMR UMM-G records into searchable STAC Items."""
import re


def _attribute(umm, name):
    return next((a.get("Values", [None])[0] for a in umm.get("AdditionalAttributes", [])
                 if a.get("Name") == name), None)


def _geometry(umm):
    geometry = umm.get("SpatialExtent", {}).get("HorizontalSpatialDomain", {}).get("Geometry", {})
    polygons = geometry.get("GPolygons", [])
    if polygons:
        return {"type": "MultiPolygon", "coordinates": [
            [[[p["Longitude"], p["Latitude"]] for p in polygon["Boundary"]["Points"]]]
            for polygon in polygons]}
    rectangles = geometry.get("BoundingRectangles", [])
    if rectangles:
        return {"type": "MultiPolygon", "coordinates": [[[
            [r["WestBoundingCoordinate"], r["SouthBoundingCoordinate"]],
            [r["EastBoundingCoordinate"], r["SouthBoundingCoordinate"]],
            [r["EastBoundingCoordinate"], r["NorthBoundingCoordinate"]],
            [r["WestBoundingCoordinate"], r["NorthBoundingCoordinate"]],
            [r["WestBoundingCoordinate"], r["SouthBoundingCoordinate"]],
        ]] for r in rectangles]}
    return None


def _bbox(geometry):
    points = []

    def visit(value):
        if isinstance(value, list) and len(value) >= 2 and all(isinstance(x, (int, float)) for x in value[:2]):
            points.append(value)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(geometry["coordinates"])
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)] if points else None


def umm_to_stac(record):
    meta, umm = record["meta"], record["umm"]
    concept_id = meta["concept-id"]
    collection = umm["CollectionReference"]
    collection_id = f"{collection['ShortName']}_{collection['Version']}"
    temporal = umm.get("TemporalExtent", {})
    interval = temporal.get("RangeDateTime", {})
    instant = temporal.get("SingleDateTime")
    start = interval.get("BeginningDateTime") or instant
    end = interval.get("EndingDateTime") or instant or start
    geometry = _geometry(umm)
    granule_ur = umm.get("GranuleUR", "")
    maturity = re.search(r"(BETA|PROVISIONAL|VALIDATED)", collection["ShortName"], re.IGNORECASE)
    crid = re.search(r"_(P\d{5})_", granule_ur)
    product_type = _attribute(umm, "PRODUCT_TYPE") or collection["ShortName"].split("_")[2]
    polarization = _attribute(umm, "FREQUENCY_A_POLARIZATION")
    related = next((u.get("URL") for u in umm.get("RelatedUrls", [])
                    if u.get("Type") == "GET DATA" and u.get("URL", "").startswith("https://")), None)
    attrs = {name: _attribute(umm, name) for name in (
        "PRODUCT_VERSION", "STACK_ID", "TRACK_NUMBER", "FRAME_NUMBER",
        "ASCENDING_DESCENDING", "FREQUENCY_A_RANGE_BANDWIDTH")}
    props = {
        "datetime": start, "start_datetime": start, "end_datetime": end,
        "title": granule_ur, "product": f"nisar-{product_type.lower()}",
        "parameter": polarization or "unknown",
        "nisar:collection_maturity": maturity.group(1).upper() if maturity else "unknown",
        "nisar:crid": crid.group(1) if crid else None,
        "nisar:product_version": attrs["PRODUCT_VERSION"],
        "nisar:collection_version": collection["Version"],
        "nisar:cmr_collection_concept_id": meta.get("collection-concept-id"),
        "nisar:cmr_collection_id": collection_id,
        "nisar:cmr_item_id": concept_id,
        "nisar:cmr_revision_id": int(meta["revision-id"]),
        "nisar:cmr_revision_date": meta["revision-date"],
        "nisar:granule_ur": granule_ur,
        "nisar:stack_id": attrs["STACK_ID"], "nisar:track": attrs["TRACK_NUMBER"],
        "nisar:frame": attrs["FRAME_NUMBER"], "nisar:orbit_direction": attrs["ASCENDING_DESCENDING"],
        "nisar:frequency_a_bandwidth": attrs["FREQUENCY_A_RANGE_BANDWIDTH"],
        "readiness:archive": "available" if related else "metadata_only",
        "quality:state": "unknown", "readiness:visual": "not_prepared",
        "readiness:reviewed_change": "not_reviewed",
    }
    item = {"type": "Feature", "stac_version": "1.0.0", "id": concept_id,
            "collection": collection_id, "geometry": geometry, "properties": props,
            "links": [{"rel": "via", "href": f"https://cmr.earthdata.nasa.gov/search/concepts/{concept_id}.umm_json",
                       "type": "application/vnd.nasa.cmr.umm+json"}], "assets": {}}
    bbox = _bbox(geometry) if geometry else None
    if bbox:
        item["bbox"] = bbox
    if related:
        item["assets"]["source-data"] = {"href": related, "roles": ["data", "source"],
                                           "type": "application/x-hdf5"}
    return item
