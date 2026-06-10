"""Stage B — Normalization & page rendering (Brief §7B): 300dpi PNGs, OCR, quality scoring,
embeddings for semantic search (ADR-002)."""
from __future__ import annotations
import io
import json
import pypdfium2 as pdfium
from PIL import Image
from sqlalchemy import select
from .. import storage
from ..config import settings
from ..db import session
from ..llm import embed
from ..models import Document, DocumentPage
from ..ocr import get_adapter


def render_document(document_id: str) -> int:
    with session() as s:
        doc = s.get(Document, document_id)
        if doc is None:
            raise ValueError(f"unknown document {document_id}")
        if doc.stage not in ("acquired",):  # idempotent re-entry (§6.3)
            existing = s.scalars(select(DocumentPage).where(
                DocumentPage.document_id == document_id)).all()
            if existing:
                return len(existing)
        source = doc.source
    raw = storage.get_raw(source, document_id)
    ocr = get_adapter()
    scale = settings().render_dpi / 72.0
    pdf = pdfium.PdfDocument(raw)
    qualities: list[float] = []
    n = len(pdf)
    page_rows = []
    for i in range(n):
        page = pdf[i]
        pil: Image.Image = page.render(scale=scale).to_pil()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        img_uri = storage.put_derived(f"pages/{document_id}/{i+1}.png", buf.getvalue(), "image/png")
        result = ocr.run(pil)
        blocks_uri = storage.put_derived(f"ocr/{document_id}/{i+1}.json",
                                         json.dumps(result.blocks).encode(), "application/json")
        qualities.append(result.quality)
        page_rows.append(dict(document_id=document_id, page_number=i + 1, image_uri=img_uri,
                              ocr_text=result.text, ocr_blocks_uri=blocks_uri,
                              ocr_quality=result.quality, low_quality=result.quality < 0.45))
    pdf.close()
    vectors = embed([r["ocr_text"][:4000] or " " for r in page_rows])
    with session() as s:
        for r, v in zip(page_rows, vectors):
            s.add(DocumentPage(**r, embedding=v))
        doc = s.get(Document, document_id)
        doc.page_count = n
        doc.ocr_quality_score = round(sum(qualities) / n, 3) if n else 0.0
        doc.stage = "rendered"
    return n
