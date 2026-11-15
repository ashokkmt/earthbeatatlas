"""Prepare and validate immutable COGs for the qualified GCOV pilot."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.shutil import copy as rio_copy
from rasterio.transform import Affine


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_cog(source: Path, destination: Path, *, width: int, height: int,
                crs: str, transform: list[float], tags: dict[str, str]) -> dict:
    """Convert the Phase 3 little-endian Float32 grid without changing valid values."""
    source = Path(source)
    destination = Path(destination)
    expected_bytes = width * height * np.dtype("<f4").itemsize
    if source.stat().st_size != expected_bytes:
        raise ValueError(f"{source} has {source.stat().st_size} bytes; expected {expected_bytes}")
    values = np.fromfile(source, dtype="<f4").reshape((height, width))
    valid = np.isfinite(values)
    if not valid.any():
        raise ValueError(f"No valid pixels in {source}")
    nodata = -9999.0
    encoded = np.where(valid, values, nodata).astype("float32", copy=False)
    expected_tags = {**tags, "units": "dB", "source_sha256": sha256(source)}
    if destination.exists():
        validate_cog(destination, values, crs=crs, transform=transform, tags=expected_tags)
        return {
            "href": str(destination), "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"], "sha256": sha256(destination), "file:size": destination.stat().st_size,
            "proj:epsg": rasterio.crs.CRS.from_string(crs).to_epsg(),
            "proj:shape": [height, width], "proj:transform": transform, "unit": "dB",
            "valid_pixels": int(valid.sum()), "nodata": nodata,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary_dir:
        temporary = Path(temporary_dir)
        source_tif = temporary / "source.tif"
        cog_tif = temporary / "output.tif"
        profile = {
            "driver": "GTiff", "width": width, "height": height, "count": 1,
            "dtype": "float32", "crs": crs, "transform": Affine(*transform),
            "nodata": nodata, "tiled": True, "blockxsize": 256, "blockysize": 256,
            "compress": "DEFLATE", "predictor": 3,
        }
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
            with rasterio.open(source_tif, "w", **profile) as dataset:
                dataset.write(encoded, 1)
                dataset.write_mask(valid.astype("uint8") * 255)
                dataset.update_tags(**expected_tags)
            rio_copy(source_tif, cog_tif, driver="COG", compress="DEFLATE", predictor=3,
                     blocksize=256, overview_resampling="AVERAGE", BIGTIFF="IF_SAFER")
            validate_cog(cog_tif, values, crs=crs, transform=transform, tags=expected_tags)
        os.replace(cog_tif, destination)

    return {
        "href": str(destination), "type": "image/tiff; application=geotiff; profile=cloud-optimized",
        "roles": ["data"], "sha256": sha256(destination), "file:size": destination.stat().st_size,
        "proj:epsg": rasterio.crs.CRS.from_string(crs).to_epsg(),
        "proj:shape": [height, width], "proj:transform": transform, "unit": "dB",
        "valid_pixels": int(valid.sum()), "nodata": nodata,
    }


def validate_cog(path: Path, expected: np.ndarray | None = None, *, crs: str | None = None,
                 transform: list[float] | None = None, tags: dict[str, str] | None = None) -> dict:
    """Check COG layout, georeferencing, units, mask, and optional source equality."""
    with rasterio.open(path) as dataset:
        layout = dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT")
        if dataset.driver != "GTiff" or not dataset.profile.get("tiled") or not dataset.overviews(1) or layout != "COG":
            raise ValueError(f"{path} is not a tiled GeoTIFF COG with overviews")
        if dataset.count != 1 or dataset.dtypes != ("float32",) or dataset.nodata != -9999.0:
            raise ValueError(f"{path} has an unsupported band, dtype, or nodata value")
        if dataset.tags().get("units") != "dB":
            raise ValueError(f"{path} is missing dB units")
        if crs is not None and dataset.crs != rasterio.crs.CRS.from_string(crs):
            raise ValueError(f"{path} CRS differs from source grid")
        if transform is not None and tuple(dataset.transform)[:6] != tuple(transform):
            raise ValueError(f"{path} transform differs from source grid")
        asset_tags = dataset.tags()
        for key, value in (tags or {}).items():
            if asset_tags.get(key) != str(value):
                raise ValueError(f"{path} lineage tag {key} is missing or changed")
        if expected is not None:
            actual = dataset.read(1, masked=True)
            valid = np.isfinite(expected)
            if not np.array_equal(~np.ma.getmaskarray(actual), valid):
                raise ValueError(f"{path} valid-data mask differs from source")
            if not np.array_equal(actual.data[valid], expected[valid]):
                raise ValueError(f"{path} changed valid source values")
        return {
            "driver": dataset.driver, "layout": layout, "crs": dataset.crs.to_string(),
            "shape": [dataset.height, dataset.width], "overviews": dataset.overviews(1),
            "nodata": dataset.nodata, "units": asset_tags["units"],
        }


def prepare_release(release: Path, output: Path) -> dict:
    """Prepare one per-acquisition COG for each observation in the immutable release."""
    release = Path(release)
    catalog = json.loads((release.parent.parent / "catalog.json").read_text())
    if catalog.get("release_id") != release.name:
        raise ValueError("Catalog and release IDs do not match")
    assets = []
    manifests = {}
    observations = {}
    for manifest_path in release.glob("*/manifest.json"):
        manifest = json.loads(manifest_path.read_text())
        manifests[manifest["region_id"]] = manifest
        observations.update({row["id"]: row for row in manifest["observations"]})
    for observation in catalog["observations"]:
        region = observation["region_id"]
        manifest = manifests[region]
        released_observation = observations[observation["id"]]
        source = release / released_observation["assets"]["values_f32"]
        if sha256(source) != released_observation["checksums"]["values_f32"]:
            raise ValueError(f"Source checksum mismatch: {source}")
        tags = {
            "stac_item_id": observation["id"], "source_granule_id": released_observation["granule_id"],
            "release_id": catalog["release_id"], "processor": "phase5-gcov-cog-v1",
            "parameter": released_observation["parameter"], "polarization": released_observation["polarization"],
            "acquisition_date": released_observation["utc_date"], "crid": "P05023",
        }
        destination = Path(output) / region / f"{observation['id'].replace(':', '__')}.tif"
        asset = prepare_cog(source, destination, width=manifest["width"], height=manifest["height"],
                            crs=manifest["crs"], transform=manifest["transform"], tags=tags)
        assets.append({"item_id": observation["id"], **asset})
    return {"release_id": catalog["release_id"], "processor": "phase5-gcov-cog-v1", "assets": assets}
