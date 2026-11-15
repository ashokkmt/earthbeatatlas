import argparse
from pathlib import Path

from nasa_explorer.catalog.ingest import import_seed
from nasa_explorer.db import migrate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import the curated STAC metadata seed into PgSTAC")
    parser.add_argument("seed", type=Path, nargs="?", default=Path("data/seeds/nisar-gcov-pilot.json"))
    args = parser.parse_args()
    if not args.seed.is_file():
        parser.error(f"Seed file not found: {args.seed}; create it with scripts.audit_cmr_granules and scripts.export_stac_seed")
    migrate()
    print(f"Upserted {import_seed(args.seed)} metadata items")
