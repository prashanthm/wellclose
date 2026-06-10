"""Dossier Composer (Brief §8.6). HARD RULE: no well-specific factual claim that is not an
APPROVED fact — composer assembles approved facts + gap report into template language only.
Outputs: immutable versioned JSON + HTML (print-to-PDF ready) with full citation appendix."""
from __future__ import annotations
from datetime import datetime, timezone
from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy import func, select
from . import storage
from .db import session
from .models import Document, Dossier, ExtractedFact, GapReport, Well, WellboreEvent

DISCLAIMER = ("This dossier is a compiled record summary with cited provenance. It is not "
              "engineering advice; abandonment design and regulatory compliance remain the "
              "operator's responsibility. (Brief §12)")


def compose(well_id: str, gap_report_id: str | None = None, signed_off_by: str | None = None) -> str:
    with session() as s:
        well = s.get(Well, well_id)
        if well is None:
            raise ValueError(f"unknown well {well_id}")
        facts = s.scalars(select(ExtractedFact).where(
            ExtractedFact.well_id == well_id,
            ExtractedFact.status.in_(("approved", "corrected")))
            .order_by(ExtractedFact.field_path)).all()
        if not facts:
            raise ValueError("Composer invariant: no approved facts — review queue first (§9.1).")
        gap = s.get(GapReport, gap_report_id) if gap_report_id else \
            s.scalars(select(GapReport).where(GapReport.well_id == well_id)
                      .order_by(GapReport.created_at.desc())).first()
        events = s.scalars(select(WellboreEvent).where(WellboreEvent.well_id == well_id)).all()
        docs = {d.document_id: d for d in s.scalars(
            select(Document).where(Document.well_id == well_id)).all()}
        version = (s.scalar(select(func.max(Dossier.version)).where(
            Dossier.well_id == well_id)) or 0) + 1

        def fact_dict(f: ExtractedFact) -> dict:
            return {"fact_id": f.fact_id, "field_path": f.field_path,
                    "value": f.corrected_value or f.value, "unit": f.unit,
                    "document_id": f.document_id, "page": f.page, "snippet": f.snippet,
                    "confidence": f.extraction_confidence, "status": f.status,
                    "diagram": f.derived_from_diagram}

        snapshot = [fact_dict(f) for f in facts]
        sections: dict[str, list[dict]] = {}
        for fd in snapshot:
            sections.setdefault(fd["field_path"].split(".")[0], []).append(fd)
        conf = [f.extraction_confidence for f in facts]
        confidence_summary = {"facts": len(facts), "mean_confidence": round(sum(conf) / len(conf), 3),
                              "diagram_derived": sum(1 for f in facts if f.derived_from_diagram),
                              "corrected": sum(1 for f in facts if f.status == "corrected")}
        payload = {
            "well": {"well_id": well.well_id, "api_number": well.api_number, "uwi": well.uwi,
                     "name": well.name, "jurisdiction": well.jurisdiction,
                     "lease_block": well.lease_block},
            "version": version, "generated_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": DISCLAIMER, "confidence_summary": confidence_summary,
            "sections": sections,
            "events": [{"type": e.event_type, "date": e.date, "top_ft": e.depth_top_ft,
                        "base_ft": e.depth_base_ft, "narrative": e.narrative,
                        "source_fact_ids": e.source_fact_ids} for e in events],
            "gap_report": {"coverage": gap.coverage, "gaps": gap.gaps} if gap else None,
            "citations": [{"fact_id": fd["fact_id"], "document_id": fd["document_id"],
                           "source": docs.get(fd["document_id"].split(":")[0],
                                              docs.get(fd["document_id"])).source
                           if (docs.get(fd["document_id"].split(":")[0]) or docs.get(fd["document_id"])) else "?",
                           "page": fd["page"], "snippet": fd["snippet"]} for fd in snapshot],
        }
        json_uri = storage.put_json(f"dossiers/{well_id}/v{version}.json", payload)
        env = Environment(loader=PackageLoader("wellclose", "templates"),
                          autoescape=select_autoescape())
        html = env.get_template("dossier.html.j2").render(**payload)
        html_uri = storage.put_derived(f"dossiers/{well_id}/v{version}.html",
                                       html.encode(), "text/html")
        d = Dossier(well_id=well_id, version=version,
                    gap_report_id=gap.gap_report_id if gap else None,
                    confidence_summary=confidence_summary,
                    approved_facts_snapshot=snapshot,
                    artifact_uris=[json_uri, html_uri], signed_off_by=signed_off_by)
        s.add(d)
        s.flush()
        return d.dossier_id
