"""Content-addressed publication of prepared assets to S3-compatible storage."""

import os
import mimetypes
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from nasa_explorer.processing.gcov import sha256


def client():
    return boto3.client(
        "s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def publish(path: Path, *, bucket: str, s3=None) -> dict:
    """Upload once under a SHA-256 key; reject a conflicting existing object."""
    path = Path(path)
    digest = sha256(path)
    suffix = path.suffix.lower() or ".bin"
    key = f"sha256/{digest[:2]}/{digest}{suffix}"
    s3 = s3 or client()
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as error:
        code = str(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
        if code != "404" and error.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        s3.create_bucket(Bucket=bucket)
    try:
        existing = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = str(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
        if code != "404" and error.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
        with path.open("rb") as body:
            s3.put_object(Bucket=bucket, Key=key, Body=body,
                          ContentType=("image/tiff; application=geotiff; profile=cloud-optimized"
                                       if suffix in {".tif", ".tiff"} else mimetypes.guess_type(path.name)[0]
                                       or "application/octet-stream"),
                          Metadata={"sha256": digest})
    else:
        metadata = existing.get("Metadata", {})
        if metadata.get("sha256") != digest or existing.get("ContentLength") != path.stat().st_size:
            raise ValueError(f"Content-addressed key contains conflicting object: s3://{bucket}/{key}")
    return {"bucket": bucket, "key": key, "href": f"s3://{bucket}/{key}", "sha256": digest,
            "size": path.stat().st_size}
