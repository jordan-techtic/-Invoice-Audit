"""S3-compatible object storage. MinIO locally, AWS S3 (US region, SSE) in production.

Keys are always prefixed with the client id: ``clients/<client_id>/...`` so a
whole client's raw files can be deleted by prefix.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

import boto3
from botocore.client import Config

from .config import get_settings


@lru_cache
def _s3():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url or None,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket() -> None:
    s = get_settings()
    c = _s3()
    try:
        c.head_bucket(Bucket=s.s3_bucket)
    except Exception:
        kwargs = {"Bucket": s.s3_bucket}
        if s.s3_region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": s.s3_region}
        c.create_bucket(**kwargs)


def client_prefix(client_id: uuid.UUID) -> str:
    return f"clients/{client_id}/"


def put(key: str, data: bytes, content_type: str) -> None:
    s = get_settings()
    extra = {"ServerSideEncryption": s.s3_sse} if s.s3_sse else {}
    _s3().put_object(Bucket=s.s3_bucket, Key=key, Body=data, ContentType=content_type, **extra)


def get(key: str) -> bytes:
    s = get_settings()
    return _s3().get_object(Bucket=s.s3_bucket, Key=key)["Body"].read()


def delete_prefix(prefix: str) -> int:
    s = get_settings()
    c = _s3()
    n = 0
    for page in c.get_paginator("list_objects_v2").paginate(Bucket=s.s3_bucket, Prefix=prefix):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            c.delete_objects(Bucket=s.s3_bucket, Delete={"Objects": objs})
            n += len(objs)
    return n


def delete(key: str) -> None:
    s = get_settings()
    _s3().delete_object(Bucket=s.s3_bucket, Key=key)
