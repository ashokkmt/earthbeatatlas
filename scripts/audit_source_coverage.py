"""Bounded CMR discovery for configured AOIs and NISAR product families.

This records metadata only. It never downloads or copies source raster data.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import earthaccess

from nasa_explorer.catalog.registry import CONFIG_ROOT, load_products, load_regions


def audit(start: str, end: str, *, limit: int = 25, search=earthaccess.search_data) -> dict:
    date.fromisoformat(start)
    date.fromisoformat(end)
    if start > end or not 1 <= limit <= 100:
        raise ValueError("Date range must be ordered and limit must be 1..100")
    report = {"period": {"start": start, "end": end}, "limit_per_region_product": limit, "records": []}
    for region_id, region in sorted(load_regions().items()):
        for product_id, product in sorted(load_products().items()):
            query = {
                "short_name": product["collection_short_name"],
                "bounding_box": tuple(region["bounds_wgs84"]),
                "temporal": (start, end),
                "count": limit,
            }
            granules = search(**query)
            for granule in granules:
                meta = granule.get("meta", {}) if hasattr(granule, "get") else {}
                umm = granule.get("umm", {}) if hasattr(granule, "get") else {}
                report["records"].append({
                    "region_id": region_id,
                    "dataset_id": product_id,
                    "collection_short_name": product["collection_short_name"],
                    "collection_concept_id": meta.get("collection-concept-id"),
                    "granule_concept_id": meta.get("concept-id"),
                    "granule_ur": umm.get("GranuleUR"),
                    "revision_date": meta.get("revision-date"),
                    "start": (umm.get("TemporalExtent", {}).get("RangeDateTime") or {}).get("BeginningDateTime"),
                    "end": (umm.get("TemporalExtent", {}).get("RangeDateTime") or {}).get("EndingDateTime"),
                    "product": product.get("product_short_name"),
                    "metadata_only": True,
                })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-10-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--limit", type=int, default=25, help="Maximum records per AOI/product (1..100)")
    parser.add_argument("--output", type=Path, default=Path("data/cache/source-audit/source-audit.json"))
    args = parser.parse_args()
    result = audit(args.start, args.end, limit=args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {len(result['records'])} metadata records to {args.output}; no raster data downloaded")


if __name__ == "__main__":
    main()
