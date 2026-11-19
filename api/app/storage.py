"""File storage: PostgreSQL blobs by default (local dev), AWS S3 in production (STORAGE_BACKEND=s3)."""

from __future__ import annotations

import uuid
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy import delete as sql_delete, select  # not 'delete': this module defines its own delete(key)

from .config import get_settings
from .db import system_session


def _use_postgres() -> bool:
    return get_settings().storage_backend == "postgres"


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
    if _use_postgres():
        return
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
    if _use_postgres():
        from .models import StoredObject

        with system_session() as db:
            row = db.get(StoredObject, key)
            if row:
                row.data = data
                row.content_type = content_type
            else:
                db.add(StoredObject(key=key, data=data, content_type=content_type))
            db.commit()
        return
    s = get_settings()
    extra = {"ServerSideEncryption": s.s3_sse} if s.s3_sse else {}
    _s3().put_object(Bucket=s.s3_bucket, Key=key, Body=data, ContentType=content_type, **extra)


def get(key: str) -> bytes:
    if _use_postgres():
        from .models import StoredObject

        with system_session() as db:
            row = db.get(StoredObject, key)
            if row is None:
                raise ClientError({"Error": {"Code": "NoSuchKey", "Message": key}}, "GetObject")
            return row.data
    s = get_settings()
    return _s3().get_object(Bucket=s.s3_bucket, Key=key)["Body"].read()


def delete_prefix(prefix: str) -> int:
    if _use_postgres():
        from .models import StoredObject

        with system_session() as db:
            rows = db.scalars(select(StoredObject.key).where(StoredObject.key.startswith(prefix))).all()
            if not rows:
                return 0
            db.execute(sql_delete(StoredObject).where(StoredObject.key.startswith(prefix)))
            db.commit()
            return len(rows)
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
    if _use_postgres():
        from .models import StoredObject

        with system_session() as db:
            if row := db.get(StoredObject, key):
                db.delete(row)
                db.commit()
        return
    s = get_settings()
    _s3().delete_object(Bucket=s.s3_bucket, Key=key)