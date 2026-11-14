"""Load the small, reviewed JSON registries used by the pilot pipeline."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG_ROOT = ROOT / "config"


def _load_files(directory: Path, key: str) -> dict[str, dict]:
    records = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text())
        identifier = record[key]
        if identifier in records:
            raise ValueError(f"Duplicate {key} in {directory}: {identifier}")
        records[identifier] = record
    if not records:
        raise ValueError(f"No JSON configuration found in {directory}")
    return records


def load_regions(config_root: Path = CONFIG_ROOT) -> dict[str, dict]:
    records = _load_files(config_root / "regions", "name")
    for name, record in records.items():
        if len(record["bounds_wgs84"]) != 4 or record["analysis_epsg"] <= 0:
            raise ValueError(f"Invalid AOI or CRS configured for {name}")
    return records


def load_products(config_root: Path = CONFIG_ROOT) -> dict[str, dict]:
    records = _load_files(config_root / "products", "dataset_id")
    for dataset_id, record in records.items():
        if not record.get("collection_concept_id") or not record.get("crid"):
            raise ValueError(f"Missing collection provenance for {dataset_id}")
    return records
