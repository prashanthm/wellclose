"""Stage A — Acquisition (Brief §7A). Idempotent: content-hash dedupe; raw bytes immutable."""
from __future__ import annotations
import logging
from sqlalchemy import select
from .. import storage
from ..db import session
from ..models import Document, Well
from ..sources.volve import get_source

log = logging.getLogger(__name__)


def ensure_well(api_number: str | None = None, uwi: str | None = None,
                jurisdiction: str = "TXRRC", name: str | None = None) -> str:
    with session() as s:
        q = select(Well)
        if api_number:
            q = q.where(Well.api_number == api_number)
        elif uwi:
            q = q.where(Well.uwi == uwi)
        else:
            q = q.where(Well.name == name)
        well = s.scalars(q).first()
        if well:
            return well.well_id
        well = Well(api_number=api_number, uwi=uwi, jurisdiction=jurisdiction, name=name)
        s.add(well)
        s.flush()
        return well.well_id


def acquire(source_name: str, well_selector: dict, well_id: str | None = None) -> list[str]:
    """Discover + fetch + store. Returns new/known document_ids. Failures on one doc never
    block others (§6.3) — they're collected and reported."""
    src = get_source(source_name)
    doc_ids, errors = [], []
    for ref in src.discover(well_selector):
        try:
            data, meta = src.fetch(ref)
            doc_id, raw_uri = storage.put_raw(data, source_name)
            with session() as s:
                if not s.get(Document, doc_id):
                    s.add(Document(document_id=doc_id, source=source_name, source_url=ref.url,
                                   fetch_meta=meta, well_id=well_id, raw_uri=raw_uri,
                                   stage="acquired"))
            doc_ids.append(doc_id)
        except Exception as e:  # noqa: BLE001 — gap-flag, don't block (§6.3)
            errors.append({"url": ref.url, "error": str(e)})
            log.warning("acquire: fetch failed for %s: %s", ref.url, e)
    return doc_ids


def ingest_local(path: str, source: str = "upload", well_id: str | None = None) -> str:
    """Manual/local document ingestion (also the Volve path and dev workflow)."""
    from pathlib import Path
    data = Path(path).read_bytes()
    doc_id, raw_uri = storage.put_raw(data, source)
    with session() as s:
        if not s.get(Document, doc_id):
            s.add(Document(document_id=doc_id, source=source, source_url=Path(path).as_uri(),
                           fetch_meta={"fetched_at": "local"}, well_id=well_id,
                           raw_uri=raw_uri, stage="acquired"))
    return doc_id
