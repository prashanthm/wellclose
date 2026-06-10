"""Stage D — Schema-guided extraction (Brief §7D). Three passes:
(1) targeted per-template fields, (2) 'anything missed' sweep for wellbore events,
(3) self-verification re-read adjusting confidence (both scores stored).
Hard invariants (§8.3): no provenance -> fact rejected at submission; never infer absent values;
ambiguous handwriting -> candidate readings with split confidence; diagrams flagged."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import yaml
from sqlalchemy import select
from .. import storage
from ..config import settings
from ..db import session
from ..llm import EXTRACTOR_VERSION, complete_json, image_part, text_part
from ..models import Document, DocumentPage, ExtractedFact

log = logging.getLogger(__name__)

_TPL_DIR = Path(__file__).parent.parent / "templates"


def load_template(doc_type: str) -> dict | None:
    p = _TPL_DIR / f"{doc_type}.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


_FACT_SCHEMA = {"type": "object", "properties": {"facts": {"type": "array", "items": {
    "type": "object", "properties": {
        "field_path": {"type": "string"}, "value": {"type": "string"},
        "unit": {"type": "string"}, "page": {"type": "integer"},
        "snippet": {"type": "string"}, "confidence": {"type": "number"},
        "candidates": {"type": "array", "items": {"type": "object"}}},
    "required": ["field_path", "value", "page", "snippet", "confidence"]}}},
    "required": ["facts"]}

_SYS_TARGETED = """You extract facts from oil & gas well records for abandonment dossiers.
HARD RULES (violations make output unusable):
1. NEVER infer a value not visibly evidenced on the page. Absence is a gap, not a guess.
2. Every fact MUST include the page number and a verbatim snippet copied from the page.
3. Copy units and datums exactly as written. Do not convert or normalize.
4. If handwriting is ambiguous, emit BOTH readings as separate facts with split confidence
   (e.g. 0.45/0.35) and note 'ambiguous handwriting' in the snippet context.
5. Confidence reflects legibility AND certainty the value answers the field. Calibrate honestly."""

_SYS_SWEEP = """Second pass over the same well record: list anything operationally significant the
targeted extraction may have missed — fish/junk lost, casing cut/pulled, squeezes, sustained casing
pressure, sidetracks, prior P&A attempts, integrity tests. Same hard rules: page + verbatim snippet
required; never infer; copy as written. Emit as facts with field_path 'wellbore_event.event' and
value as JSON {event_type, date, depth_top_ft, depth_base_ft, narrative}."""

_SYS_VERIFY = """You are verifying previously extracted facts against the same source pages.
For each fact, re-read the page region around its snippet and return verify_confidence (0-1):
1.0 = snippet present and value correct; ~0.5 = present but value questionable; 0 = not found.
Return JSON {"verifications": [{"index": <input index>, "verify_confidence": <float>}]}."""


def _page_parts(doc: Document, pages: list[DocumentPage]) -> list[dict]:
    s_ = settings()
    parts = []
    for p in pages:
        key = p.image_uri.split(f"{s_.bucket_derived}/")[-1]
        parts.append(text_part(f"--- PAGE {p.page_number}" +
                               (" [LOW OCR QUALITY — rely on the image]" if p.low_quality else "") + " ---"))
        parts.append(image_part(storage.get_derived(key)))
        parts.append(text_part(f"[page {p.page_number} OCR text]\n{(p.ocr_text or '')[:3000]}"))
    return parts


def _page_range(doc: Document) -> tuple[int, int] | None:
    if doc.split_parent_id and doc.fetch_meta and "page_range" in doc.fetch_meta:
        a, b = doc.fetch_meta["page_range"]
        return int(a), int(b)
    return None


def extract_document(document_id: str, batch_pages: int = 4) -> int:
    """Run all three passes; returns count of submitted facts."""
    s_ = settings()
    with session() as s:
        doc = s.get(Document, document_id)
        if doc is None or doc.doc_type in (None, "multi", "unknown"):
            return 0
        tpl = load_template(doc.doc_type)
        if tpl is None:  # correspondence/maps etc.: sweep-only
            tpl = {"doc_type": doc.doc_type, "fields": [], "diagram": False}
        source_doc_id = doc.split_parent_id or doc.document_id
        q = select(DocumentPage).where(DocumentPage.document_id == source_doc_id) \
            .order_by(DocumentPage.page_number)
        pages = s.scalars(q).all()
        if rng := _page_range(doc):
            pages = [p for p in pages if rng[0] <= p.page_number <= rng[1]]
    if not pages:
        return 0
    is_diagram = bool(tpl.get("diagram"))
    field_desc = "\n".join(f"- {f['field_path']}" + (" (multi)" if f.get("multi") else "") +
                           f": {f['description']}" for f in tpl["fields"])
    all_facts: list[dict] = []
    for i in range(0, len(pages), batch_pages):
        chunk = pages[i:i + batch_pages]
        parts = [text_part(f"Document type: {doc.doc_type}. Extract these fields:\n{field_desc}"
                           if field_desc else "No targeted fields; sweep only.")]
        parts += _page_parts(doc, chunk)
        if field_desc:
            out, _ = complete_json(s_.model_vision, _SYS_TARGETED, parts, schema_hint=_FACT_SCHEMA,
                                   tags={"stage": "extract.p1", "document_id": document_id},
                                   allow_escalation=True)
            all_facts += out.get("facts", []) if isinstance(out, dict) else out
        out2, _ = complete_json(s_.model_vision, _SYS_SWEEP, _page_parts(doc, chunk),
                                schema_hint=_FACT_SCHEMA,
                                tags={"stage": "extract.p2", "document_id": document_id},
                                allow_escalation=True)
        all_facts += out2.get("facts", []) if isinstance(out2, dict) else out2
    # Pass 3 — self-verify
    verify_scores: dict[int, float] = {}
    if all_facts:
        listing = json.dumps([{"index": i, "field_path": f["field_path"], "value": f["value"],
                               "page": f["page"], "snippet": f["snippet"][:200]}
                              for i, f in enumerate(all_facts)])
        for i in range(0, len(pages), batch_pages):
            chunk = pages[i:i + batch_pages]
            pages_in = {p.page_number for p in chunk}
            sub = [f for f in all_facts if f["page"] in pages_in]
            if not sub:
                continue
            parts = [text_part("Facts to verify:\n" + listing)] + _page_parts(doc, chunk)
            out, _ = complete_json(s_.model_vision, _SYS_VERIFY, parts,
                                   tags={"stage": "extract.p3", "document_id": document_id})
            for v in (out.get("verifications", []) if isinstance(out, dict) else out):
                try:
                    verify_scores[int(v["index"])] = float(v["verify_confidence"])
                except (KeyError, TypeError, ValueError):
                    continue
    return submit_facts(document_id, doc.well_id, all_facts, verify_scores, is_diagram)


def has_provenance(fact: dict[str, object]) -> bool:
    """The §8.3 hard rule: a fact is only admissible with a page number and verbatim snippet."""
    return bool(fact.get("snippet")) and bool(fact.get("page"))


def submit_facts(document_id: str, well_id: str | None, facts: list[dict],
                 verify_scores: dict[int, float], diagram: bool) -> int:
    """Provenance validation gate (§8.3/§8.7 submit_facts): page+snippet mandatory."""
    accepted = 0
    with session() as s:
        for i, f in enumerate(facts):
            if not has_provenance(f):
                log.warning("rejected fact without provenance (§8.3) doc=%s field=%s page=%r",
                            document_id, f.get("field_path"), f.get("page"))
                continue
            conf = max(0.0, min(1.0, float(f.get("confidence", 0))))
            s.add(ExtractedFact(
                well_id=well_id, entity_type=f["field_path"].split(".")[0],
                field_path=f["field_path"], value=str(f.get("value", "")),
                unit=f.get("unit"), document_id=document_id, page=int(f["page"]),
                snippet=f["snippet"][:2000], extraction_confidence=conf,
                verify_confidence=verify_scores.get(i),
                derived_from_diagram=diagram, extractor_version=EXTRACTOR_VERSION))
            accepted += 1
        doc = s.get(Document, document_id)
        if doc:
            doc.stage = "extracted"
    return accepted
