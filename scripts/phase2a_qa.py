"""Recheck the cached GCOV inputs and build the local Santa Rosa pilot."""
import json
import re
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_geom
from shapely.geometry import box, mapping, shape
from nasa_explorer.catalog.registry import load_regions

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/cache"
OUT = CACHE / "phase-2a"
REGIONS = {name: (tuple(row["bounds_wgs84"]), row["analysis_epsg"])
           for name, row in load_regions().items()}
POLARIZATIONS = {"HH": "HHHH", "HV": "HVHV"}
WITHHELD = {"Santa Rosa": {"2026-05-17": "Broad, reversing radiometric shift in both channels"}}
REFERENCES = {
    "santa-rosa-perimeter-clipped.geojson": 1,
    "barataria-nwi-emergent.geojson": 82,
    "barataria-nwi-forested-shrub.geojson": 268,
}


def inside(geometries, crs, transform, size, all_touched=False):
    projected = [transform_geom("EPSG:4326", crs, geom) for geom in geometries]
    return geometry_mask(projected, size, transform, invert=True, all_touched=all_touched)


def target_grid(transform, size):
    left = int(transform.c // 30 * 30)
    top = int(-(-transform.f // 30) * 30)
    x_pad = int((transform.c - left) / 10)
    y_pad = int((top - transform.f) / 10)
    assert (transform.a, transform.b, transform.d, transform.e) == (10, 0, 0, -10)
    assert (left + x_pad * 10, top - y_pad * 10) == (transform.c, transform.f)
    height, width = size
    return from_origin(left, top, 30, 30), ((height + y_pad + 2) // 3,
                                            (width + x_pad + 2) // 3), (y_pad, x_pad)


def aggregate(power, valid, target_size, padding):
    """On the aligned grids, every source cell contributes exactly 100 m²."""
    rows, cols = target_size
    padded = np.full((rows * 3, cols * 3), np.nan, dtype=np.float64)
    y, x = padding
    height, width = power.shape
    padded[y:y + height, x:x + width] = np.where(valid, power, np.nan)
    blocks = padded.reshape(rows, 3, cols, 3)
    counts = np.isfinite(blocks).sum(axis=(1, 3))
    sums = np.nansum(blocks, axis=(1, 3))
    db = np.full(target_size, np.nan)
    good = counts >= 8
    db[good] = 10 * np.log10(sums[good] / counts[good])
    return db


def metrics(delta, selected):
    values = delta[selected & np.isfinite(delta)]
    count = int(values.size)
    report = {"eligible_cells": int(selected.sum()), "valid_cells": count,
              "valid_km2": count * 0.0009,
              "coverage": count / int(selected.sum()) if selected.any() else None,
              "median_db": float(np.median(values)) if count else None, "thresholds": {}}
    if count:
        for threshold in (2, 3, 4):
            channels = {}
            for name, matches in (("increase", values >= threshold), ("decrease", values <= -threshold)):
                hits = int(matches.sum())
                channels[name] = {"cells": hits, "km2": hits * 0.0009, "percent": 100 * hits / count}
            report["thresholds"][threshold] = channels
    return report


def previews(frames, perimeter):
    """Grayscale source views and signed differences with an optional green outline."""
    border = np.zeros_like(perimeter)
    border[1:] |= perimeter[1:] != perimeter[:-1]
    border[:, 1:] |= perimeter[:, 1:] != perimeter[:, :-1]
    low, high = np.percentile(np.concatenate([f[np.isfinite(f)] for f in frames]), [2, 98])
    deltas = [b - a for a, b in zip(frames, frames[1:])] + [frames[-1] - frames[0]]
    tiles = []
    for idx, grid in enumerate(frames + deltas):
        if idx < len(frames):
            level = np.nan_to_num(np.clip((grid - low) / (high - low), 0, 1))
            pixels = np.stack([level] * 3)
        else:
            scaled = np.nan_to_num(np.clip(grid / 6, -1, 1))
            pixels = np.stack([1 - np.maximum(-scaled, 0), 1 - abs(scaled),
                               1 - np.maximum(scaled, 0)])
        pixels[:, ~np.isfinite(grid)] = 0
        pixels[:, border & np.isfinite(grid)] = np.array([0.1, 0.8, 0.25])[:, None]
        tiles.append(np.uint8(pixels * 255))
    return np.concatenate([np.concatenate(tiles[:4], axis=2),
                           np.concatenate(tiles[4:], axis=2)], axis=1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source_notes = (ROOT / "plans/data-sources.md").read_text()
    pins = re.findall(r"^\| (Santa Rosa|Barataria|Colusa) / .*?\| (\d{4}-\d\d-\d\d) \| "
                      r"`(G\d+-ASF)` \| `(NISAR_[^`]+)`", source_notes, re.M)
    assert len(pins) == 12
    jobs = json.loads((CACHE / "phase-1/jobs.json").read_text())
    jobs += json.loads((CACHE / "phase-2/results.json").read_text())
    assert len(jobs) == 36
    references = {}
    for name, count in REFERENCES.items():
        features = json.loads((CACHE / "phase-2" / name).read_text())["features"]
        assert len(features) == count
        assert all(shape(f["geometry"]).is_valid and not shape(f["geometry"]).is_empty for f in features)
        references[name] = features
    fire = references["santa-rosa-perimeter-clipped.geojson"][0]
    assert fire["properties"]["attr_UniqueFireIdentifier"] == "2026-CACNP-001159"
    classes = ("Freshwater Emergent Wetland", "Freshwater Forested/Shrub Wetland")
    for features, name in zip(list(references.values())[1:], classes, strict=True):
        assert all(f["properties"]["WETLAND_TYPE"] == name for f in features)
    cdl_path = CACHE / "phase-2/colusa-cdl-2025.tif"
    with rasterio.open(cdl_path) as cdl:
        rice = cdl.read(1, masked=True)
        assert cdl.crs.to_epsg() == 5070 and (rice == 3).sum() == 522276

    report = {"mask_codes_accepted_for_this_inventory": [1],
              "reference_counts": REFERENCES, "cdl_rice_cells": 522276, "regions": {}}
    for region, (bounds, epsg) in REGIONS.items():
        aoi = mapping(box(*bounds))
        frames = {key: [] for key in POLARIZATIONS}
        native_valid = {key: [] for key in POLARIZATIONS}
        inventory = []
        region_pins = [pin for pin in pins if pin[0] == region]
        assert len(region_pins) == 4
        native_grid = None
        for _, date, granule, name in region_pins:
            entry = {"date": date, "granule": granule, "files": {}}
            for variable in ("mask", *POLARIZATIONS.values()):
                paths = list(CACHE.glob(f"phase-[12]/*_{name}_science_LSAR_GCOV_grids_frequencyA_{variable}_subsetted.tif"))
                matches = [job for job in jobs if (job["date"], job["granule"], job["variable"]) ==
                           (date, granule, variable)]
                assert len(paths) == len(matches) == 1, (granule, variable)
                path = paths[0]
                if "file" in matches[0]:
                    assert Path(matches[0]["file"]).name == path.name
                entry["files"][variable] = {"path": str(path.relative_to(ROOT)),
                                            "job": matches[0].get("harmony_job") or matches[0]["job"]}
                with rasterio.open(path) as src:
                    assert src.count == 1 and src.crs.to_epsg() == epsg
                    grid = (src.transform, src.shape)
                    if native_grid is None:
                        native_grid = grid
                        target_transform, target_size, padding = target_grid(*grid)
                        native_aoi = inside([aoi], src.crs, *grid, all_touched=True)
                        eligible = inside([aoi], src.crs, target_transform, target_size)
                    assert grid == native_grid, path
                    values = src.read(1, masked=True)
                if variable == "mask":
                    codes, counts = np.unique(values.data, return_counts=True)
                    assert set(codes).issubset({0, 1, 255}) and 1 in codes
                    entry["mask_counts"] = dict(zip(map(int, codes), map(int, counts), strict=True))
                    valid_mask = (values.data == 1) & ~np.ma.getmaskarray(values)
                else:
                    pol = "HH" if variable == "HHHH" else "HV"
                    assert values.dtype.kind == "f", path
                    valid = valid_mask & ~np.ma.getmaskarray(values) & np.isfinite(values.data) & (values.data > 0)
                    native_valid[pol].append(valid & native_aoi)
                    db = aggregate(values.data, valid, target_size, padding)
                    db[~eligible] = np.nan
                    frames[pol].append(db)
            inventory.append(entry)
        crs = f"EPSG:{epsg}"
        context = {}
        for name, features in references.items():
            if name.startswith(region.split()[0].lower()):
                context[name] = inside([f["geometry"] for f in features], crs, target_transform, target_size)
        if region == "Colusa":
            with rasterio.open(cdl_path) as cdl:
                labels = np.zeros(target_size, dtype=np.uint8)
                reproject(rasterio.band(cdl, 1), labels, dst_crs=crs, dst_transform=target_transform,
                          resampling=Resampling.nearest, dst_nodata=0)
            context["2025 CDL rice"] = labels == 3
        record = {"inventory": inventory, "crs": crs, "grid_transform": list(target_transform)[:6],
                  "shape": target_size, "aoi_cells": int(eligible.sum()), "channels": {}}
        withheld = WITHHELD.get(region, {})
        retained = [i for i, entry in enumerate(inventory) if entry["date"] not in withheld]
        assert len(retained) >= 3
        record["withheld"] = withheld
        record["retained_dates"] = [inventory[i]["date"] for i in retained]
        report["regions"][region] = record
        for pol, images in frames.items():
            shared = np.logical_and.reduce([np.isfinite(img) for img in images])
            retained_shared = np.logical_and.reduce([np.isfinite(images[i]) for i in retained])
            native_shared = np.logical_and.reduce(native_valid[pol])
            channel = {"native_common_coverage": float(native_shared.sum() / native_aoi.sum()),
                       "all_dates_common_coverage": float(shared.sum() / eligible.sum()),
                       "retained_common_coverage": float(retained_shared.sum() / eligible.sum()),
                       "per_date_coverage": [float(np.isfinite(img).sum() / eligible.sum()) for img in images],
                       "common_context_cells": {name: int((cells & retained_shared).sum()) for name, cells in context.items()}}
            assert len(channel["per_date_coverage"]) == 4 and channel["retained_common_coverage"] >= .8
            assert channel["common_context_cells"] and all(channel["common_context_cells"].values())
            record["channels"][pol] = channel
            perimeter = np.zeros(target_size, dtype=bool)
            if region == "Santa Rosa":
                perimeter = next(iter(context.values()))
                channel["adjacent_pairs_inside_perimeter"] = [
                    metrics(b - a, perimeter & eligible) for a, b in zip(images, images[1:])
                ]
                delta = images[-1] - images[0]
                channel["pilot"] = {"aoi": metrics(delta, eligible),
                                    "inside_perimeter": metrics(delta, perimeter & eligible),
                                    "outside_perimeter": metrics(delta, ~perimeter & eligible)}
                with rasterio.open(OUT / f"santa-rosa-{pol}-delta.tif", "w", driver="GTiff",
                                   count=1, height=target_size[0], width=target_size[1],
                                   dtype="float32", crs=crs, transform=target_transform, nodata=np.nan) as src:
                    src.write(delta.astype("float32"), 1)
            pixels = previews(images, perimeter)
            with rasterio.open(OUT / f"{region.lower().replace(' ', '-')}-{pol}.png", "w",
                               driver="PNG", count=3, height=pixels.shape[1],
                               width=pixels.shape[2], dtype="uint8",
                               transform=from_origin(1, 1, 1, 1)) as png:
                png.write(pixels)
    (OUT / "qa.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
