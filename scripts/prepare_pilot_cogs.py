"""Build a separate, validated COG release from the immutable Phase 3 pilot."""

import argparse
import json
from pathlib import Path

from nasa_explorer.processing.gcov import prepare_release

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=ROOT / "data/releases/nisar-pilot-20261114-v1")
    parser.add_argument("--output", type=Path, default=ROOT / "data/cache/phase-5/cogs")
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    manifest = prepare_release(args.release, args.output)
    manifest_path = args.manifest or args.output / "assets.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Prepared {len(manifest['assets'])} GCOV COGs: {manifest_path}")


if __name__ == "__main__":
    main()
