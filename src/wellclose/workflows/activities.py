"""Temporal activities (ADR-001): idempotent, resumable wrappers over pipeline stages and agents
(Brief §6.3, §9.1). All heavy lifting lives here; workflow code stays deterministic."""
from __future__ import annotations
import json
from temporalio import activity


@activity.defn
async def act_acquire(source: str, selector_json: str, well_id: str | None) -> list[str]:
    from ..pipeline.acquire import acquire
    return acquire(source, json.loads(selector_json), well_id)


@activity.defn
async def act_render(document_id: str) -> int:
    from ..pipeline.render import render_document
    return render_document(document_id)


@activity.defn
async def act_classify(document_id: str) -> str:
    from ..pipeline.classify import classify_document
    return json.dumps(classify_document(document_id))


@activity.defn
async def act_extract(document_id: str) -> int:
    from ..pipeline.extract import extract_document
    return extract_document(document_id)


@activity.defn
async def act_resolve(document_id: str) -> str | None:
    from ..pipeline.resolve import resolve_well
    return resolve_well(document_id)


@activity.defn
async def act_conflicts_and_validators(well_id: str) -> dict:
    from ..pipeline.resolve import detect_conflicts, run_validators
    return {"conflicts": detect_conflicts(well_id), "validator_flags": run_validators(well_id)}


@activity.defn
async def act_historian(well_id: str, run_id: str) -> str:
    """Wellbore Historian agent (§8.4) -> persists WellboreEvent rows from its JSON output."""
    from ..agents.runner import run_agent
    from ..db import session
    from ..models import WellboreEvent
    out = run_agent("historian_agent",
                    f"Assemble the wellbore history for well_id={well_id}. run_id={run_id}. "
                    "Return ONLY the JSON array of events.")
    try:
        start, end = out.find("["), out.rfind("]")
        events = json.loads(out[start:end + 1]) if start >= 0 else []
    except json.JSONDecodeError:
        events = []
    with session() as s:
        for e in events:
            s.add(WellboreEvent(well_id=well_id, event_type=str(e.get("event_type", "other"))[:32],
                                date=e.get("date"), depth_top_ft=e.get("depth_top_ft"),
                                depth_base_ft=e.get("depth_base_ft"),
                                narrative=e.get("narrative"),
                                severity_flag=bool(e.get("severity_flag")),
                                source_fact_ids=e.get("source_fact_ids")))
    return json.dumps({"events": len(events)})


@activity.defn
async def act_gap_analysis(well_id: str) -> str:
    from ..rubric import gap_analysis
    return gap_analysis(well_id)


@activity.defn
async def act_review_queue_size(well_id: str) -> int:
    from sqlalchemy import or_, select
    from ..config import settings
    from ..db import session
    from ..models import ExtractedFact
    with session() as s:
        q = select(ExtractedFact.fact_id).where(
            ExtractedFact.well_id == well_id, ExtractedFact.status == "proposed",
            or_(ExtractedFact.conflict_group_id.is_not(None),
                ExtractedFact.derived_from_diagram.is_(True),
                ExtractedFact.validation_flags.is_not(None),
                ExtractedFact.extraction_confidence < settings().t_auto))
        return len(s.scalars(q).all())


@activity.defn
async def act_compose(well_id: str, signed_off_by: str) -> str:
    from ..agents.runner import run_agent
    out = run_agent("composer_agent",
                    f"Compose the dossier for well_id={well_id}; signed_off_by={signed_off_by}.")
    return out
