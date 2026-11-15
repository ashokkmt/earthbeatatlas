"""Build bounded Harmony requests from the reviewed product registry."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

import earthaccess
from harmony import BBox, Collection, Request
from harmony import Client


def harmony_request(product: dict, region: dict, granule_id: str, parameter_ids: list[str], *,
                    polarization: str = "HH", layer: str = "layer1") -> Request:
    if not granule_id or not parameter_ids or len(parameter_ids) > 6:
        raise ValueError("Select one source granule and between 1 and 6 output parameters")
    if polarization not in {"HH", "VV"} or layer not in {"layer1", "layer2", "layer3"}:
        raise ValueError("Unsupported NISAR polarization or GOFF offset layer")
    parameters = product.get("parameters", {})
    missing = set(parameter_ids) - set(parameters)
    if missing:
        raise ValueError(f"Unsupported parameters for {product['dataset_id']}: {sorted(missing)}")
    variables = []
    for key in parameter_ids:
        variable = parameters[key].get("harmony_variable")
        if not variable:
            raise ValueError(f"No verified Harmony variable configured for {product['dataset_id']}:{key}")
        variables.append(variable.format(polarization=polarization, layer=layer))
    west, south, east, north = region["bounds_wgs84"]
    return Request(
        Collection(product["collection_concept_id"]),
        granule_id=[granule_id], spatial=BBox(west, south, east, north),
        variables=variables, max_results=1, skip_preview=True,
    )


def utc_from_metadata(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("CMR acquisition times must include a timezone")
    return parsed.astimezone(timezone.utc)


def earthdata_auth_strategy(token: str | None = None) -> str:
    return "environment" if (os.getenv("EARTHDATA_TOKEN", "") if token is None else token).strip() else "netrc"


def harmony_bearer_token(auth) -> str:
    token = auth.token.get("access_token") if isinstance(auth.token, dict) else auth.token
    if not isinstance(token, str) or not token:
        raise RuntimeError("Earthdata Login did not provide a bearer token")
    return token


def fetch_harmony_cogs(product: dict, region: dict, granule_id: str, parameters: list[str],
                       output_dir: Path, *, polarization: str = "HH", layer: str = "layer1") -> dict:
    request = harmony_request(product, region, granule_id, parameters,
                              polarization=polarization, layer=layer)
    auth = earthaccess.login(strategy=earthdata_auth_strategy())
    if not auth.authenticated:
        raise RuntimeError("Earthdata Login is not authenticated")
    client = Client(token=harmony_bearer_token(auth))
    job_id = client.submit(request)
    if isinstance(job_id, dict):
        result = job_id
    else:
        client.wait_for_processing(job_id)
        result = list(client.result_urls(job_id))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for url in (result if isinstance(result, list) else []):
        downloaded.append(str(client.download(url, str(output_dir)).result()))
    manifest = {
        "product_id": product["dataset_id"], "collection_concept_id": product["collection_concept_id"],
        "region": region["name"], "region_bounds_wgs84": region["bounds_wgs84"],
        "source_granule_concept_id": granule_id, "parameters": parameters,
        "polarization": polarization, "goff_layer": layer if product["dataset_id"] == "nisar-goff" else None,
        "harmony_job_id": job_id if isinstance(job_id, str) else None,
        "harmony_output_urls": len(result) if isinstance(result, list) else None,
        "local_files": downloaded, "token_written": False,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
