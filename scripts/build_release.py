import hashlib
import json
import re
import shutil
import warnings
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform
from shapely.geometry import box, mapping
from nasa_explorer.catalog.registry import load_products, load_regions
from scripts.audit_cmr_granules import cmr_record_url

from scripts.phase2a_qa import CACHE, POLARIZATIONS, REGIONS, aggregate, inside, target_grid, WITHHELD

ROOT = Path(__file__).resolve().parents[1]
REGION_CONFIG = load_regions()
PRODUCT_CONFIG = load_products()["nisar-gcov"]
RELEASE_ID = "nisar-pilot-20261114-v1"
RELEASES = ROOT / "data/releases"
RELEASE = RELEASES / RELEASE_ID
CATALOG_PATH = ROOT / "data/catalog.json"
SOURCE = CACHE / "phase-2"
CHANNELS = PRODUCT_CONFIG["channels"]
DIFFERENCE_SCALE_DB = 6.0
SLUG = {name: row["slug"] for name, row in REGION_CONFIG.items()}
TITLES = {name: row["title"] for name, row in REGION_CONFIG.items()}
REGION_NAMES = {name: row["full_name"] for name, row in REGION_CONFIG.items()}
ALIASES = {name: row["aliases"] for name, row in REGION_CONFIG.items()}
CONTEXT = {name: [(layer["filename"], layer["label"]) for layer in row["context_layers"]]
           for name, row in REGION_CONFIG.items()}
SOURCES = {name: row["context_layers"][0]["source"] for name, row in REGION_CONFIG.items()}


def read_scene(region, date, pol):
    suffix = date.replace("-", "")
    values = list(CACHE.glob(f"phase-[12]/*{suffix}*_{CHANNELS[pol]}_subsetted.tif"))
    masks = list(CACHE.glob(f"phase-[12]/*{suffix}*_mask_subsetted.tif"))
    if len(values) != 1 or len(masks) != 1:
        raise ValueError(f"Expected one data/mask pair for {region} {date} {pol}")
    with rasterio.open(values[0]) as ds:
        power = ds.read(1, masked=True)
        grid = (ds.transform, ds.shape, ds.crs)
        assert ds.crs.to_epsg() == REGIONS[region][1] and ds.dtypes[0] == "float32"
    with rasterio.open(masks[0]) as ds:
        assert (ds.transform, ds.shape, ds.crs) == grid
        mask = ds.read(1, masked=True)
    codes = set(np.unique(mask.compressed()).tolist())
    assert codes <= {0, 1, 255} and 1 in codes
    valid = (mask.data == 1) & ~np.ma.getmaskarray(mask)
    valid &= ~np.ma.getmaskarray(power) & np.isfinite(power.data) & (power.data > 0)
    transform, size, padding = target_grid(grid[0], grid[1])
    return aggregate(power.data, valid, size, padding), grid, transform, size


def rgba(values, lower, upper, difference=False):
    valid = np.isfinite(values)
    out = np.zeros((*values.shape, 4), dtype=np.uint8)
    clean = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    if difference:
        scale = np.clip(clean / upper, -1, 1)
        out[..., 0] = ((1 - np.maximum(-scale, 0)) * 255).astype("u1")
        out[..., 1] = ((1 - abs(scale)) * 255).astype("u1")
        out[..., 2] = ((1 - np.maximum(scale, 0)) * 255).astype("u1")
    else:
        grey = (np.clip((clean - lower) / (upper - lower), 0, 1) * 255).astype("u1")
        out[..., :3] = grey[..., None]
    out[..., 3] = valid.astype("u1") * 255
    return out


def write_png(path, image):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(path, "w", driver="PNG", width=image.shape[1], height=image.shape[0], count=4,
                       dtype="uint8", photometric="RGB") as dst:
            dst.write(np.moveaxis(image, -1, 0))
    Path(str(path) + ".aux.xml").unlink(missing_ok=True)


def display_grid(image, source_transform, source_crs):
    height, width = image.shape[:2]
    left, bottom, right, top = array_bounds(height, width, source_transform)
    dst_transform, dst_width, dst_height = calculate_default_transform(
        source_crs, "EPSG:3857", width, height, left, bottom, right, top
    )
    output = np.zeros((dst_height, dst_width, 4), dtype="uint8")
    for channel in range(3):
        reproject(image[..., channel], output[..., channel], src_transform=source_transform,
                  src_crs=source_crs, dst_transform=dst_transform, dst_crs="EPSG:3857",
                  resampling=Resampling.bilinear)
    reproject(image[..., 3], output[..., 3], src_transform=source_transform,
              src_crs=source_crs, dst_transform=dst_transform, dst_crs="EPSG:3857",
              resampling=Resampling.nearest)
    xmin, ymin, xmax, ymax = array_bounds(dst_height, dst_width, dst_transform)
    xs, ys = transform("EPSG:3857", "EPSG:4326", [xmin, xmax, xmax, xmin], [ymax, ymax, ymin, ymin])
    return output, [[float(x), float(y)] for x, y in zip(xs, ys, strict=True)]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stats(values, paired, eligible, threshold):
    data = values[paired & np.isfinite(values)]
    n = data.size
    return {"valid_cells": int(n), "valid_area_km2": float(n * .0009),
            "coverage": float(n / eligible.sum()) if eligible.any() else None,
            "median_db": float(np.median(data)) if n else None,
            "thresholds_db": {str(t): {
                "increase": {"cells": int((data >= t).sum()), "km2": int((data >= t).sum())*.0009,
                             "percent": 100*int((data >= t).sum())/n if n else None},
                "decrease": {"cells": int((data <= -t).sum()), "km2": int((data <= -t).sum())*.0009,
                             "percent": 100*int((data <= -t).sum())/n if n else None}}
                for t in (2, 3, 4)}}


def validate(release, catalog):
    assert catalog["release_id"] == RELEASE_ID
    catalog_ids = [row["id"] for row in catalog["observations"]]
    assert len(catalog_ids) == len(set(catalog_ids))
    expected_order = sorted(catalog["observations"], key=lambda row: row["id"])
    expected_order.sort(key=lambda row: row["utc_date"], reverse=True)
    assert catalog_ids == [row["id"] for row in expected_order]
    total_observations = total_pairs = 0
    for region, (_, epsg) in REGIONS.items():
        slug = SLUG[region]
        manifest_path = release / slug / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["release_id"] == RELEASE_ID and manifest["crs"] == f"EPSG:{epsg}"
        assert manifest["difference_display_scale_db"] == [-6.0, 6.0]
        assert manifest["difference_sign_convention"] == "later date minus earlier date"
        assert manifest["missing_pixels"] == "transparent"
        assert manifest["analysis_grid_encoding"] == {"format": "raw-binary", "dtype": "float32",
            "byte_order": "little-endian", "units": "dB", "nodata": "NaN",
            "row_order": "north-to-south", "column_order": "west-to-east"}
        assert len(manifest["dates"]) >= 3 and len(manifest["dates"]) == len(set(manifest["dates"]))
        assert manifest["provenance"]["mask_codes_accepted"] == [1]
        assert manifest["provenance"]["minimum_source_cells"] == 8
        withheld = manifest["withheld_dates"]
        assert not set(withheld).intersection(manifest["dates"])
        for observation in manifest["observations"]:
            assert observation["utc_date"] in manifest["dates"] and observation["parameter"] in ("hh-backscatter", "hv-backscatter")
            raw = release / observation["assets"]["values_f32"]
            png = release / observation["assets"]["map_png"]
            assert raw.stat().st_size == manifest["width"] * manifest["height"] * 4
            assert sha(raw) == observation["checksums"]["values_f32"]
            assert sha(png) == observation["checksums"]["map_png"]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
                with rasterio.open(png) as img:
                    assert (img.height, img.width) == (manifest["display_height"], manifest["display_width"])
            values = np.fromfile(raw, dtype="<f4").reshape(manifest["height"], manifest["width"])
            assert int(np.isfinite(values).sum()) == observation["valid_cells"]
            assert np.isnan(values).any()
            source_values, _, _, _ = read_scene(region, observation["utc_date"], observation["polarization"])
            assert np.array_equal(values, source_values.astype("<f4"), equal_nan=True)
        for pair in manifest["pairs"]:
            assert pair["earlier_date"] in manifest["dates"] and pair["later_date"] in manifest["dates"]
            assert pair["map_sha256"] == sha(release / pair["map_png"])
            assert set(pair["summary"]) == {"All AOI", *[c for c in manifest["contexts"]]}
            for result in pair["summary"].values():
                for threshold in ("2", "3", "4"):
                    item = result["thresholds_db"][threshold]
                    assert item["increase"]["cells"] * .0009 == item["increase"]["km2"]
                    assert item["decrease"]["cells"] * .0009 == item["decrease"]["km2"]
        for context in manifest["contexts"].values():
            assert (release / context["asset"]).is_file()
        total_observations += len(manifest["observations"])
        total_pairs += len(manifest["pairs"])
    assert total_observations == len(catalog["observations"]) == 22
    assert total_pairs == 30
    for row in catalog["observations"]:
        assert row["id"] == f"{row['region_id']}:{row['dataset_id']}:{row['parameter']}:{row['utc_date']}"
        assert row["parameter"] in ("hh-backscatter", "hv-backscatter") and row["units"] == "dB"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["utc_date"])
        expected_manifest = (f"{row['region_id']}/manifest.json" if release.name.startswith(".")
                             else f"releases/{RELEASE_ID}/{row['region_id']}/manifest.json")
        assert row["manifest"] == expected_manifest
        assert (ROOT / "data" / row["manifest"]).is_file() if not release.name.startswith(".") else (release / row["manifest"]).is_file()
    return {"observations": total_observations, "pairs": total_pairs}


def main():
    if RELEASE.exists():
        catalog = json.loads(CATALOG_PATH.read_text())
        counts = validate(RELEASE, catalog)
        print(f"Validated immutable {RELEASE_ID}: {counts['observations']} observations, {counts['pairs']} pairs")
        return
    qa = json.loads((CACHE / "phase-2a/qa.json").read_text())
    source_text = (ROOT / "plans/data-sources.md").read_text()
    granules = {date: (granule, name) for date, granule, name in re.findall(
        r"^\| (?:Santa Rosa|Barataria|Colusa) / .*?\| (\d{4}-\d{2}-\d{2}) \| `(G\d+-ASF)` \| `(NISAR_[^`]+)`", source_text, re.M)}
    assert len(granules) == 12
    stage = RELEASES / f".{RELEASE_ID}.tmp"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    catalog = {"release_id": RELEASE_ID, "observations": []}
    for region, (bounds, epsg) in REGIONS.items():
        slug = SLUG[region]
        out = stage / slug
        out.mkdir()
        dates = qa["regions"][region]["retained_dates"]
        images, transform, grid = {pol: [] for pol in CHANNELS}, None, None
        display_corners = None
        display_width = display_height = None
        for pol in CHANNELS:
            for date in dates:
                image, native, current_transform, size = read_scene(region, date, pol)
                assert grid is None or grid == native
                grid, transform = native, current_transform
                images[pol].append(image)
        aoi = inside([mapping(box(*bounds))], f"EPSG:{epsg}", transform, size)
        contexts = {"All AOI": aoi}
        context_meta = {}
        for filename, label in CONTEXT[region]:
            src = SOURCE / filename
            if filename.endswith("geojson"):
                feature_rows = json.loads(src.read_text())["features"]
                contexts[label] = inside([f["geometry"] for f in feature_rows], f"EPSG:{epsg}", transform, size) & aoi
                shutil.copyfile(src, out / filename)
                context_meta[label] = {"source": SOURCES[region], "asset": f"{slug}/{filename}", "features": len(feature_rows), "sha256": sha(out / filename)}
            else:
                with rasterio.open(src) as cdl:
                    classes = np.zeros(size, dtype="uint8")
                    reproject(rasterio.band(cdl, 1), classes, dst_crs=f"EPSG:{epsg}", dst_transform=transform,
                              resampling=Resampling.nearest, dst_nodata=0)
                contexts[label] = (classes == 3) & aoi
                preview, display_corners = display_grid(rgba(contexts[label].astype(float), 0, 1), transform, f"EPSG:{epsg}")
                display_height, display_width = preview.shape[:2]
                display_filename = next(layer["display_filename"] for layer in REGION_CONFIG[region]["context_layers"]
                                        if layer["filename"] == filename)
                write_png(out / display_filename, preview)
                context_meta[label] = {"source": SOURCES[region], "asset": f"{slug}/{display_filename}", "year": 2025, "class": 3, "source_file_sha256": sha(src), "display_sha256": sha(out / display_filename)}
        scales = {pol: [float(v) for v in np.percentile(np.concatenate([x[np.isfinite(x)] for x in frames]), [2, 98])]
                  for pol, frames in images.items()}
        common = {pol: np.logical_and.reduce([np.isfinite(x) for x in frames]) & aoi for pol, frames in images.items()}
        assert all(common[p].sum() / aoi.sum() >= .8 for p in CHANNELS)
        observations, charts, pairs = [], [], []
        for pol, frames in images.items():
            for date, frame in zip(dates, frames, strict=True):
                parameter = f"{pol.lower()}-backscatter"
                obs_id = f"{slug}:nisar-gcov:{parameter}:{date}"
                png = out / f"{date}-{pol.lower()}.png"
                preview, corners = display_grid(rgba(frame, *scales[pol]), transform, f"EPSG:{epsg}")
                display_corners = corners
                display_height, display_width = preview.shape[:2]
                write_png(png, preview)
                raw = out / f"{date}-{pol.lower()}.f32"
                frame.astype("<f4").tofile(raw)
                granule, full_name = granules[date]
                source_files = list(CACHE.glob(f"phase-[12]/*{date.replace('-', '')}*_{CHANNELS[pol]}_subsetted.tif")) + list(CACHE.glob(f"phase-[12]/*{date.replace('-', '')}*_mask_subsetted.tif"))
                assert len(source_files) == 2
                obs = {"id": obs_id, "region_id": slug, "dataset_id": "nisar-gcov", "parameter": parameter,
                       "polarization": pol, "units": "dB", "utc_date": date,
                       "granule_id": granule, "full_granule_name": full_name,
                       "acquisition_start_utc": re.search(r"(\d{8}T\d{6})", full_name).group(1),
                       "acquisition_end_utc": re.findall(r"(\d{8}T\d{6})", full_name)[1],
                       "source_record": cmr_record_url(granule),
                       "source_checksums": {f.name: sha(f) for f in source_files},
                       "assets": {"map_png": f"{slug}/{png.name}", "values_f32": f"{slug}/{raw.name}"},
                       "checksums": {"map_png": sha(png), "values_f32": sha(raw)},
                       "valid_cells": int(np.isfinite(frame).sum()), "coverage": float(np.isfinite(frame).sum()/aoi.sum())}
                observations.append(obs)
                catalog["observations"].append({"id": obs_id, "region_id": slug, "region": REGION_NAMES[region],
                    "aliases": ALIASES[region], "title": TITLES[region], "dataset_id": "nisar-gcov",
                    "parameter": parameter, "units": "dB", "utc_date": date, "manifest": f"{slug}/manifest.json"})
                for label, mask in contexts.items():
                    if label != "All AOI":
                        n = int((common[pol] & mask).sum())
                        values = frame[common[pol] & mask]
                        charts.append({"date": date, "polarization": pol, "class": label, "valid_cells": n,
                                       "area_km2": n*.0009, "coverage": float(n/mask.sum()) if mask.any() else None,
                                       "median_db": float(np.median(values)) if n else None})
            for i, earlier in enumerate(dates):
                for j in range(i+1, len(dates)):
                    later = dates[j]
                    paired = np.isfinite(frames[i]) & np.isfinite(frames[j]) & aoi
                    delta = frames[j] - frames[i]
                    summary = {name: stats(delta, paired & mask, mask, 3) for name, mask in contexts.items()}
                    filename = f"{earlier}-{later}-{pol.lower()}-difference.png"
                    preview, corners = display_grid(rgba(delta, DIFFERENCE_SCALE_DB, DIFFERENCE_SCALE_DB, difference=True), transform, f"EPSG:{epsg}")
                    assert corners == display_corners
                    write_png(out / filename, preview)
                    pairs.append({"polarization": pol, "earlier_date": earlier, "later_date": later, "units": "dB",
                                  "map_png": f"{slug}/{filename}", "map_sha256": sha(out / filename), "valid_pair_cells": int(paired.sum()),
                                  "valid_pair_area_km2": float(paired.sum()*.0009), "summary": summary})
        manifest = {"release_id": RELEASE_ID, "region_id": slug, "region": REGION_NAMES[region],
                    "aliases": ALIASES[region], "bounds_wgs84": list(bounds), "crs": f"EPSG:{epsg}",
                    "transform": list(transform)[:6], "width": size[1], "height": size[0],
                    "display_crs": "EPSG:3857", "display_width": display_width, "display_height": display_height,
                    "display_corners_wgs84": display_corners, "cell_size_m": 30,
                    "dates": dates, "withheld_dates": WITHHELD.get(region, {}), "display_scales_db": scales,
                    "difference_display_scale_db": [-DIFFERENCE_SCALE_DB, DIFFERENCE_SCALE_DB],
                    "difference_sign_convention": "later date minus earlier date", "missing_pixels": "transparent",
                    "analysis_grid_encoding": {"format": "raw-binary", "dtype": "float32",
                        "byte_order": "little-endian", "units": "dB", "nodata": "NaN",
                        "row_order": "north-to-south", "column_order": "west-to-east"},
                    "observations": observations, "pairs": pairs, "chart_rows": charts, "contexts": context_meta,
                    "provenance": {"collection": "C2854338529-ASF", "product": "NISAR_L2_GCOV_PROVISIONAL_V1",
                                   "crid": "P05023", "mask_codes_accepted": [1], "withheld_dates": WITHHELD.get(region, {}),
                                   "aggregation": "mean valid linear gamma-zero power, then 10 log10",
                                   "minimum_source_cells": 8, "source_qa": "data/cache/phase-2a/qa.json"}}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    catalog["observations"].sort(key=lambda row: row["id"])
    catalog["observations"].sort(key=lambda row: row["utc_date"], reverse=True)
    (stage / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    assert len(catalog["observations"]) == 22
    validate(stage, catalog)
    RELEASES.mkdir(parents=True, exist_ok=True)
    stage.rename(RELEASE)
    catalog["observations"] = [{**row, "manifest": f"releases/{RELEASE_ID}/{row['manifest']}"} for row in catalog["observations"]]
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2) + "\n")
    validate(RELEASE, catalog)
    print(f"Built {RELEASE_ID}: {len(catalog['observations'])} observation entries")


if __name__ == "__main__":
    main()
