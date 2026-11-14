"""Export the verified pilot release as a local STAC ItemCollection."""

from pathlib import Path

from nasa_explorer.catalog.registry import load_products, load_regions
from nasa_explorer.catalog.stac import export_metadata_seed, export_stac

ROOT = Path(__file__).resolve().parents[1]


def main():
    release = ROOT / "data/releases/nisar-pilot-20261114-v1"
    cache_seed = ROOT / "data/cache/phase-3a/stac/items.json"
    result = export_stac(release, cache_seed,
                         ROOT / "data/cache/phase-3a/cmr-audit.json",
                         load_regions(), load_products())
    metadata_count = export_metadata_seed(cache_seed, ROOT / "data/seeds/nisar-gcov-pilot.json")
    print(f"Exported {result['acquisitions']} acquisitions and {result['pairs']} pairs")
    print(f"Wrote {metadata_count} metadata-only seed items")


if __name__ == "__main__":
    main()
