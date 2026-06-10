"""Stage C — Classification & splitting (Brief §7C). LLM classification on first-N pages;
multi-record RRC scans split into logical documents (split children share raw bytes,
own page ranges via split_parent_id + meta)."""
from __future__ import annotations
from sqlalchemy import select
from ..config import settings
from ..db import session
from ..llm import complete_json, image_part, text_part
from ..models import Document, DocumentPage

TAXONOMY = ["completion_report", "plugging_record", "casing_record", "cement_report",
            "wellbore_schematic", "permit", "sundry_notice", "daily_drilling_report",
            "end_of_well_report", "correspondence", "map_or_plat", "unknown"]

_SYS = ("You classify oil & gas well record documents. Taxonomy: " + ", ".join(TAXONOMY) +
        ". A single scanned file may contain MULTIPLE distinct filings; detect boundaries. "
        "Use both the page images and OCR text. Forms: TX RRC W-3 = plugging_record, "
        "W-2/G-1 = completion_report; BSEE APM = permit; sundry = sundry_notice.")

_SCHEMA = {"type": "object", "properties": {"segments": {"type": "array", "items": {
    "type": "object", "properties": {
        "doc_type": {"enum": TAXONOMY}, "first_page": {"type": "integer"},
        "last_page": {"type": "integer"}, "confidence": {"type": "number"}},
    "required": ["doc_type", "first_page", "last_page", "confidence"]}}},
    "required": ["segments"]}


def classify_document(document_id: str, max_pages: int = 6) -> list[dict]:
    from .. import storage
    s_ = settings()
    with session() as s:
        pages = s.scalars(select(DocumentPage).where(DocumentPage.document_id == document_id)
                          .order_by(DocumentPage.page_number)).all()
        if not pages:
            raise ValueError(f"document {document_id} not rendered")
        total = len(pages)
        sample = pages[:max_pages]
        parts = [text_part(f"Document has {total} pages. Sampled first {len(sample)} pages. "
                           "Return segments covering pages 1..%d." % total)]
        for p in sample:
            key = p.image_uri.split(f"{s_.bucket_derived}/")[-1]
            parts.append(image_part(storage.get_derived(key)))
            parts.append(text_part(f"[page {p.page_number} OCR]\n{(p.ocr_text or '')[:2500]}"))
    result, _ = complete_json(s_.model_small, _SYS, parts, schema_hint=_SCHEMA,
                              tags={"stage": "classify", "document_id": document_id},
                              allow_escalation=True)
    segments = result["segments"] if isinstance(result, dict) else result
    with session() as s:
        doc = s.get(Document, document_id)
        if len(segments) == 1:
            doc.doc_type = segments[0]["doc_type"]
            doc.doc_type_confidence = float(segments[0]["confidence"])
        else:
            doc.doc_type = "multi"
            for seg in segments:
                child_id = f"{document_id}:{seg['first_page']}-{seg['last_page']}"
                if not s.get(Document, child_id):
                    s.add(Document(document_id=child_id, source=doc.source,
                                   source_url=doc.source_url, well_id=doc.well_id,
                                   doc_type=seg["doc_type"],
                                   doc_type_confidence=float(seg["confidence"]),
                                   raw_uri=doc.raw_uri, split_parent_id=document_id,
                                   stage="rendered",
                                   fetch_meta={"page_range": [seg["first_page"], seg["last_page"]]},
                                   page_count=seg["last_page"] - seg["first_page"] + 1))
        doc.stage = "classified"
    return segments
