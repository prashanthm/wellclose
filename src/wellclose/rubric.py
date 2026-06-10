"""Rubric engine + gap analysis (Brief §5.3, agent §8.5). Coverage = approved/proposed facts
satisfying each requirement; blocker gaps headline the report; each gap carries suggested sources."""
from __future__ import annotations
import json
from pathlib import Path
import yaml
from sqlalchemy import select
from .db import session
from .models import ExtractedFact, GapReport, Well

_RUBRIC_DIR = Path(__file__).parent / "rubrics"
_CRIT_ORDER = {"blocker": 0, "major": 1, "minor": 2}


def load_rubric(jurisdiction: str) -> dict:
    p = _RUBRIC_DIR / f"{jurisdiction.lower()}.yaml"
    if not p.exists():
        raise ValueError(f"No rubric for jurisdiction {jurisdiction}")
    return yaml.safe_load(p.read_text())


def gap_analysis(well_id: str, jurisdiction: str | None = None) -> str:
    with session() as s:
        well = s.get(Well, well_id)
        if well is None:
            raise ValueError(f"unknown well {well_id}")
        jur = jurisdiction or well.jurisdiction
        facts = s.scalars(select(ExtractedFact).where(
            ExtractedFact.well_id == well_id,
            ExtractedFact.status.in_(("proposed", "approved", "corrected")))).all()
    rubric = load_rubric(jur)
    coverage, gaps = [], []
    for req in rubric["requirements"]:
        matches = [f for f in facts if f.field_path == req["satisfied_by"]]
        if fw := req.get("field_within"):
            def has_inner(f: ExtractedFact) -> bool:
                try:
                    return json.loads(f.value or "{}").get(fw) not in (None, "", "unknown")
                except json.JSONDecodeError:
                    return False
            matches = [f for f in matches if has_inner(f)]
        if vc := req.get("value_contains"):
            matches = [f for f in matches if vc.lower() in (f.value or "").lower()]
        entry = {"requirement_id": req["id"], "rubric": req["rubric"],
                 "criticality": req["criticality"], "satisfied": bool(matches),
                 "fact_ids": [f.fact_id for f in matches],
                 "max_confidence": max((f.extraction_confidence for f in matches), default=0.0),
                 "any_approved": any(f.status in ("approved", "corrected") for f in matches)}
        coverage.append(entry)
        if not matches:
            gaps.append({"requirement_id": req["id"], "rubric": req["rubric"],
                         "criticality": req["criticality"],
                         "suggested_sources": req.get("suggested_sources", [])})
    gaps.sort(key=lambda g: _CRIT_ORDER[g["criticality"]])
    with session() as s:
        report = GapReport(well_id=well_id, jurisdiction=jur, coverage=coverage, gaps=gaps)
        s.add(report)
        s.flush()
        return report.gap_report_id
