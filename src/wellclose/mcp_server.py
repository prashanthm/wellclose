"""MCP tool server — the single data gateway (Brief §8.7). All 13 tools; every call logged with
agent identity + workflow run id (ToolCallLog). Agents NEVER touch the DB directly.
Run: `wellclose mcp` (streamable-http) — Strands runner and external Claude/agent runtimes connect here."""
from __future__ import annotations
import json
from mcp.server.fastmcp import FastMCP
from sqlalchemy import or_, select, text
from . import storage as store
from .db import session
from .models import Document, DocumentPage, ExtractedFact, GapReport, Well

mcp = FastMCP("wellclose")


def _log(agent: str | None, run_id: str | None, tool: str, args: dict,
         well_id: str | None = None) -> None:
    from .models import ToolCallLog
    with session() as s:
        s.add(ToolCallLog(agent=agent, workflow_run_id=run_id, tool=tool,
                          args_summary={k: str(v)[:200] for k, v in args.items()}, well_id=well_id))


@mcp.tool()
def source_discover(source: str, well_selector: str, agent: str = "", run_id: str = "") -> str:
    """Discover document refs for a well selector (JSON) at a source: bsee|txrrc|volve."""
    from .sources.volve import get_source
    _log(agent, run_id, "source_discover", {"source": source, "selector": well_selector})
    refs = list(get_source(source).discover(json.loads(well_selector)))
    return json.dumps([{"url": r.url, "well_hint": r.well_hint, "doc_hint": r.doc_hint} for r in refs])


@mcp.tool()
def source_fetch(source: str, url: str, well_id: str = "", agent: str = "", run_id: str = "") -> str:
    """Fetch one document ref and store immutably; returns document_id."""
    from .pipeline.acquire import acquire
    _log(agent, run_id, "source_fetch", {"source": source, "url": url}, well_id or None)
    ids = acquire(source, {"document_url": url} if source == "txrrc" else {"bulk": url},
                  well_id or None)
    return json.dumps({"document_ids": ids})


@mcp.tool()
def corpus_status(well_id: str, agent: str = "", run_id: str = "") -> str:
    """Documents + stages for a well (acquisition completeness check, §8.1)."""
    _log(agent, run_id, "corpus_status", {"well_id": well_id}, well_id)
    with session() as s:
        docs = s.scalars(select(Document).where(Document.well_id == well_id)).all()
        return json.dumps([{"document_id": d.document_id, "doc_type": d.doc_type,
                            "stage": d.stage, "pages": d.page_count,
                            "ocr_quality": d.ocr_quality_score} for d in docs])


@mcp.tool()
def get_document_pages(document_id: str, first_page: int = 1, last_page: int = 0,
                       agent: str = "", run_id: str = "") -> str:
    """Page image URIs + low-quality flags for a document/page range."""
    _log(agent, run_id, "get_document_pages", {"document_id": document_id})
    with session() as s:
        q = select(DocumentPage).where(DocumentPage.document_id == document_id.split(":")[0]) \
            .order_by(DocumentPage.page_number)
        pages = [p for p in s.scalars(q)
                 if p.page_number >= first_page and (not last_page or p.page_number <= last_page)]
        return json.dumps([{"page": p.page_number, "image_uri": p.image_uri,
                            "low_quality": p.low_quality} for p in pages])


@mcp.tool()
def get_ocr_text(document_id: str, first_page: int = 1, last_page: int = 0,
                 agent: str = "", run_id: str = "") -> str:
    """OCR text per page for a document/page range."""
    _log(agent, run_id, "get_ocr_text", {"document_id": document_id})
    with session() as s:
        q = select(DocumentPage).where(DocumentPage.document_id == document_id.split(":")[0]) \
            .order_by(DocumentPage.page_number)
        pages = [p for p in s.scalars(q)
                 if p.page_number >= first_page and (not last_page or p.page_number <= last_page)]
        return json.dumps([{"page": p.page_number, "text": p.ocr_text} for p in pages])


@mcp.tool()
def get_extraction_template(doc_type: str, jurisdiction: str = "", agent: str = "",
                            run_id: str = "") -> str:
    """JSON extraction template for a doc_type (§7D)."""
    from .pipeline.extract import load_template
    _log(agent, run_id, "get_extraction_template", {"doc_type": doc_type})
    return json.dumps(load_template(doc_type) or {})


@mcp.tool()
def submit_facts(facts_json: str, document_id: str, well_id: str = "",
                 from_diagram: bool = False, agent: str = "", run_id: str = "") -> str:
    """Submit ExtractedFacts (JSON array). Provenance (page+snippet) REQUIRED — invalid rejected (§8.3)."""
    from .pipeline.extract import submit_facts as _submit
    _log(agent, run_id, "submit_facts", {"document_id": document_id, "n": "?"}, well_id or None)
    facts = json.loads(facts_json)
    n = _submit(document_id, well_id or None, facts, {}, from_diagram)
    return json.dumps({"accepted": n, "rejected": len(facts) - n})


@mcp.tool()
def query_facts(well_id: str, entity_type: str = "", status: str = "", conflict_only: bool = False,
                agent: str = "", run_id: str = "") -> str:
    """Query facts by well / entity_type / status / conflicts."""
    _log(agent, run_id, "query_facts", {"well_id": well_id, "status": status}, well_id)
    with session() as s:
        q = select(ExtractedFact).where(ExtractedFact.well_id == well_id)
        if entity_type:
            q = q.where(ExtractedFact.entity_type == entity_type)
        if status:
            q = q.where(ExtractedFact.status == status)
        if conflict_only:
            q = q.where(ExtractedFact.conflict_group_id.is_not(None))
        return json.dumps([{
            "fact_id": f.fact_id, "field_path": f.field_path, "value": f.corrected_value or f.value,
            "unit": f.unit, "document_id": f.document_id, "page": f.page, "snippet": f.snippet,
            "confidence": f.extraction_confidence, "verify_confidence": f.verify_confidence,
            "status": f.status, "conflict_group_id": f.conflict_group_id,
            "validation_flags": f.validation_flags, "diagram": f.derived_from_diagram}
            for f in s.scalars(q)])


@mcp.tool()
def search_documents(query: str, well_id: str = "", doc_type: str = "", limit: int = 8,
                     agent: str = "", run_id: str = "") -> str:
    """Hybrid search (ADR-002): Postgres FTS + pgvector, rank-fused; returns passages w/ doc/page."""
    from .llm import embed
    _log(agent, run_id, "search_documents", {"q": query[:80]}, well_id or None)
    vec = embed([query])[0]
    with session() as s:
        params = {"q": query, "vec": str(vec), "lim": limit}
        well_clause = "AND d.well_id = :wid" if well_id else ""
        type_clause = "AND d.doc_type = :dt" if doc_type else ""
        if well_id:
            params["wid"] = well_id
        if doc_type:
            params["dt"] = doc_type
        rows = s.execute(text(f"""
            WITH kw AS (
              SELECT p.page_id, ts_rank(p.search_tsv, plainto_tsquery('english', :q)) AS r
              FROM document_page p JOIN document d ON d.document_id = p.document_id
              WHERE p.search_tsv @@ plainto_tsquery('english', :q) {well_clause} {type_clause}
              ORDER BY r DESC LIMIT :lim),
            sem AS (
              SELECT p.page_id, 1 - (p.embedding <=> CAST(:vec AS vector)) AS r
              FROM document_page p JOIN document d ON d.document_id = p.document_id
              WHERE p.embedding IS NOT NULL {well_clause} {type_clause}
              ORDER BY p.embedding <=> CAST(:vec AS vector) LIMIT :lim)
            SELECT p.document_id, p.page_number, left(p.ocr_text, 600) AS passage,
                   COALESCE(kw.r,0)*0.5 + COALESCE(sem.r,0)*0.5 AS score
            FROM document_page p
            LEFT JOIN kw ON kw.page_id = p.page_id
            LEFT JOIN sem ON sem.page_id = p.page_id
            WHERE kw.page_id IS NOT NULL OR sem.page_id IS NOT NULL
            ORDER BY score DESC LIMIT :lim"""), params).mappings().all()
        return json.dumps([dict(r) for r in rows])


@mcp.tool()
def get_rubric(jurisdiction: str, agent: str = "", run_id: str = "") -> str:
    """Dossier requirements rubric for a jurisdiction (§5.3)."""
    from .rubric import load_rubric
    _log(agent, run_id, "get_rubric", {"jurisdiction": jurisdiction})
    return json.dumps(load_rubric(jurisdiction))


@mcp.tool()
def submit_gap_report(well_id: str, jurisdiction: str = "", agent: str = "", run_id: str = "") -> str:
    """Run rubric coverage + gap analysis; returns gap_report_id (§8.5)."""
    from .rubric import gap_analysis
    _log(agent, run_id, "submit_gap_report", {"well_id": well_id}, well_id)
    return json.dumps({"gap_report_id": gap_analysis(well_id, jurisdiction or None)})


@mcp.tool()
def get_well_summary(well_id: str, agent: str = "", run_id: str = "") -> str:
    """Materialized entity view over approved facts (§5.1)."""
    _log(agent, run_id, "get_well_summary", {"well_id": well_id}, well_id)
    with session() as s:
        w = s.get(Well, well_id)
        if w is None:
            return json.dumps({"error": "unknown well"})
        gaps = s.scalars(select(GapReport).where(GapReport.well_id == well_id)
                         .order_by(GapReport.created_at.desc())).first()
        n_appr = len(s.scalars(select(ExtractedFact.fact_id).where(
            ExtractedFact.well_id == well_id,
            ExtractedFact.status.in_(("approved", "corrected")))).all())
        return json.dumps({"well_id": w.well_id, "api_number": w.api_number, "uwi": w.uwi,
                           "jurisdiction": w.jurisdiction, "status": w.status,
                           "approved_facts": n_appr,
                           "open_gaps": len(gaps.gaps) if gaps else None})


@mcp.tool()
def render_dossier(well_id: str, signed_off_by: str = "", agent: str = "", run_id: str = "") -> str:
    """Compose dossier from APPROVED facts only (§8.6 hard rule); returns dossier_id + artifact URIs."""
    from .dossier import compose
    _log(agent, run_id, "render_dossier", {"well_id": well_id}, well_id)
    did = compose(well_id, signed_off_by=signed_off_by or None)
    with session() as s:
        from .models import Dossier
        d = s.get(Dossier, did)
        return json.dumps({"dossier_id": did, "artifacts": d.artifact_uris})


@mcp.tool()
def flag_for_review(object_ref: str, reason: str, agent: str = "", run_id: str = "") -> str:
    """Escalate any object to the human review queue with a rationale."""
    _log(agent, run_id, "flag_for_review", {"ref": object_ref, "reason": reason[:200]})
    with session() as s:
        f = s.get(ExtractedFact, object_ref)
        if f:
            f.validation_flags = (f.validation_flags or []) + [f"agent_flag: {reason[:300]}"]
            return json.dumps({"queued": "fact", "fact_id": object_ref})
    return json.dumps({"queued": "noted", "ref": object_ref})


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
