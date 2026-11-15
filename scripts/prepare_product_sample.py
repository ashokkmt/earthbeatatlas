"""Retrieve only configured variables for one region/granule through Harmony."""

import argparse
from pathlib import Path

from nasa_explorer.catalog.registry import load_products, load_regions
from nasa_explorer.processing.harmony import (earthdata_auth_strategy, fetch_harmony_cogs,
    harmony_request)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", required=True, choices=("nisar-gcov", "nisar-gunw", "nisar-goff", "nisar-sme2"))
    parser.add_argument("--region", help="Configured region name (e.g. Colusa)")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                        help="Temporary, tightly bounded QA AOI; not added to dashboard region registry")
    parser.add_argument("--granule-id", required=True, help="One pinned CMR granule concept ID")
    parser.add_argument("--parameters", nargs="+", required=True)
    parser.add_argument("--polarization", choices=("HH", "VV"), default="HH")
    parser.add_argument("--layer", choices=("layer1", "layer2", "layer3"), default="layer1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    products = load_products()
    regions = load_regions()
    if bool(args.region) == bool(args.bbox):
        parser.error("Provide either --region or --bbox")
    if args.region and args.region not in regions:
        parser.error(f"Unknown configured region: {args.region}")
    if args.bbox:
        west, south, east, north = args.bbox
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90
                and east - west <= 10 and north - south <= 10):
            parser.error("Temporary QA bbox must be valid and no wider than 10 degrees")
        region = {"name": "Temporary QA AOI", "slug": "temporary-qa-aoi", "bounds_wgs84": args.bbox}
    else:
        region = regions[args.region]
    product = products[args.product]
    output_dir = args.output or Path("data/cache/product-samples") / args.product / region["slug"] / args.granule_id
    manifest = fetch_harmony_cogs(product, region, args.granule_id, args.parameters,
                                  output_dir, polarization=args.polarization, layer=args.layer)
    print(f"Downloaded {len(manifest['local_files'])} selected Harmony COGs to {output_dir}; credentials were not written")


if __name__ == "__main__":
    main()
