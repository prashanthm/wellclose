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


def _coerce_segments(result: object) -> list[dict]:
    """The small model's JSON shape varies: {'segments': [...]}, a bare [...], or a single
    segment object {'doc_type':...}. Normalize all to a list of segment dicts."""
    if isinstance(result, dict):
        if isinstance(result.get("segments"), list):
            return result["segments"]
        if "doc_type" in result:          # a lone segment returned unwrapped
            return [result]
        # some other single-key wrapper around the list
        for v in result.values():
            if isinstance(v, list):
                return v
        return []
    if isinstance(result, list):
        return result
    return []


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
    segments = _coerce_segments(result)
    segments = [_norm_segment(s, total) for s in segments]
    if not segments:   # model gave nothing usable — treat whole doc as one unknown segment
        segments = [{"doc_type": "unknown", "first_page": 1, "last_page": total, "confidence": 0.3}]
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


def _norm_segment(seg: dict, total: int) -> dict:
    """Fill missing fields and clamp page ranges so a sloppy model segment can't crash
    or create a child doc with a bad range."""
    dt = seg.get("doc_type") if isinstance(seg, dict) else None
    first = seg.get("first_page", 1) if isinstance(seg, dict) else 1
    last = seg.get("last_page", total) if isinstance(seg, dict) else total
    try:
        first = max(1, min(int(first), total))
        last = max(first, min(int(last), total))
    except (TypeError, ValueError):
        first, last = 1, total
    try:
        conf = float(seg.get("confidence", 0.5)) if isinstance(seg, dict) else 0.5
    except (TypeError, ValueError):
        conf = 0.5
    return {"doc_type": dt if dt in TAXONOMY else "unknown",
            "first_page": first, "last_page": last, "confidence": conf}
