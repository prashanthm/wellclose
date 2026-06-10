"""MinIO object store (Brief §6.1, §4.5). Raw bucket is write-once (versioned, never overwritten);
derived bucket holds page images / OCR artifacts / dossier renders."""
import hashlib
import io
import json
from functools import lru_cache
from minio import Minio
from .config import settings


@lru_cache
def client() -> Minio:
    s = settings()
    c = Minio(s.minio_endpoint, access_key=s.minio_access_key,
              secret_key=s.minio_secret_key, secure=s.minio_secure)
    for b in (s.bucket_raw, s.bucket_derived):
        if not c.bucket_exists(b):
            c.make_bucket(b)
    return c


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_raw(data: bytes, source: str) -> tuple[str, str]:
    """Store raw document bytes immutably; returns (document_id, uri). Dedupe on content hash (§4.5)."""
    s, c = settings(), client()
    doc_id = sha256(data)
    key = f"{source}/{doc_id}"
    found = list(c.list_objects(s.bucket_raw, prefix=key, recursive=False))
    if not found:
        c.put_object(s.bucket_raw, key, io.BytesIO(data), len(data))
    return doc_id, f"s3://{s.bucket_raw}/{key}"


def get_raw(source: str, document_id: str) -> bytes:
    s = settings()
    return client().get_object(s.bucket_raw, f"{source}/{document_id}").read()


def put_derived(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    s = settings()
    client().put_object(s.bucket_derived, key, io.BytesIO(data), len(data), content_type=content_type)
    return f"s3://{s.bucket_derived}/{key}"


def get_derived(key: str) -> bytes:
    s = settings()
    return client().get_object(s.bucket_derived, key).read()


def put_json(key: str, obj: object) -> str:
    return put_derived(key, json.dumps(obj, default=str).encode(), "application/json")
