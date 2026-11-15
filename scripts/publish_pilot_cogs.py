"""Publish validated pilot COGs to content-addressed S3 storage."""

import argparse
import json
import os
from pathlib import Path

from nasa_explorer.storage.s3 import publish
from nasa_explorer.db import connect
from nasa_explorer.catalog.ingest import import_items

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("data/cache/cogs/assets.json"))
    parser.add_argument("--release", type=Path, default=ROOT / "data/releases/nisar-pilot-20261114-v1")
    parser.add_argument("--bucket", default=os.environ.get("S3_BUCKET", "nisar-assets"))
    parser.add_argument("--register", action="store_true", help="Update pilot STAC items in PostgreSQL")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    for asset in manifest["assets"]:
        result = publish(Path(asset["href"]), bucket=args.bucket)
        if result["sha256"] != asset["sha256"]:
            raise ValueError(f"Post-upload digest mismatch for {asset['item_id']}")
        asset["s3_href"] = result["href"]

    previews, contexts, region_manifests = [], [], []
    for path in sorted(args.release.glob("*/manifest.json")):
        region_manifest = json.loads(path.read_text())
        region = path.parent.name
        region_manifests.append({"region_id": region, **publish(path, bucket=args.bucket)})
        item_ids = {
            observation["assets"]["map_png"]: observation["id"]
            for observation in region_manifest["observations"]
        }
        item_ids.update({
            pair["map_png"]: f"{region}:nisar-gcov:{pair['polarization'].lower()}-difference:{pair['earlier_date']}:{pair['later_date']}"
            for pair in region_manifest["pairs"]
        })
        for relative, item_id in item_ids.items():
            local = args.release / relative
            previews.append({"item_id": item_id, "path": relative, **publish(local, bucket=args.bucket)})
        for label, layer in region_manifest["contexts"].items():
            local = args.release / layer["asset"]
            if local.is_file():
                contexts.append({"region_id": region, "label": label,
                                 "path": layer["asset"], **publish(local, bucket=args.bucket)})
    manifest["previews"] = previews
    manifest["contexts"] = contexts
    manifest["region_manifests"] = region_manifests
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")

    if args.register:
        items_by_id = {}
        all_ids = sorted({row["item_id"] for row in manifest["assets"] + previews})
        collection = "NISAR_L2_GCOV_PROVISIONAL_V1_1"
        with connect() as conn:
            rows = conn.execute(
                "SELECT id,collection,content FROM pgstac.items WHERE collection=%s AND id=ANY(%s)",
                (collection, all_ids),
            ).fetchall()
        items_by_id = {}
        for item_id, item_collection, content in rows:
            content["id"] = item_id
            content["collection"] = item_collection
            items_by_id[item_id] = content
        if set(items_by_id) != set(all_ids):
            missing = sorted(set(all_ids) - set(items_by_id))
            raise ValueError(f"Cannot register assets; STAC items are missing: {missing[:5]}")
        for asset in manifest["assets"]:
            item = items_by_id[asset["item_id"]]
            item.setdefault("assets", {})["data"] = {
                "href": asset["s3_href"], "type": asset["type"], "roles": ["data"],
                "file:checksum": "1220" + asset["sha256"], "file:size": asset["file:size"],
            }
            item["properties"]["readiness:visual"] = "ready"
        for preview in previews:
            item = items_by_id[preview["item_id"]]
            item.setdefault("assets", {})["visual"] = {
                "href": preview["href"], "type": "image/png", "roles": ["overview"],
                "file:checksum": "1220" + preview["sha256"], "file:size": preview["size"],
            }
            item["properties"]["readiness:visual"] = "ready"
        import_items(list(items_by_id.values()))
    print(f"Published {len(manifest['assets'])} COGs, {len(previews)} pilot previews, "
          f"{len(contexts)} context layers, and {len(region_manifests)} region manifests to s3://{args.bucket}")


if __name__ == "__main__":
    main()
