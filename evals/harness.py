"""Eval harness (Brief §10): runs gold wells against DB state (post-pipeline) and reports
field-level P/R, calibration, classification accuracy, per-era breakdown. CI gate via
`wellclose eval --fail-under-precision 0.97 --fail-under-recall 0.90`.

Gold layout: evals/gold/<well>.json  (see gold/SCHEMA.md); adversarial/ holds §10.3 traps —
they are ordinary gold wells whose 'gold_facts' assert what must NOT be extracted via
expected absence (omit the field; spurious extraction then counts as FP)."""
from __future__ import annotations
import json
from pathlib import Path
from .metrics import calibration, classification_accuracy, field_prf


def _load_pred_for_well(api_number: str | None, uwi: str | None) -> tuple[list[dict], dict]:
    from sqlalchemy import select
    from wellclose.db import session
    from wellclose.models import Document, ExtractedFact, Well
    with session() as s:
        q = select(Well)
        if api_number:
            q = q.where(Well.api_number == api_number)
        elif uwi:
            q = q.where(Well.uwi == uwi)
        well = s.scalars(q).first()
        if well is None:
            return [], {}
        facts = [{"field_path": f.field_path, "value": f.corrected_value or f.value,
                  "confidence": f.extraction_confidence}
                 for f in s.scalars(select(ExtractedFact).where(
                     ExtractedFact.well_id == well.well_id,
                     ExtractedFact.status.in_(("proposed", "approved", "corrected"))))]
        doc_types = {d.document_id: d.doc_type for d in s.scalars(
            select(Document).where(Document.well_id == well.well_id))}
        return facts, doc_types


def run(gold_dir: str = "evals/gold") -> dict:
    gold_paths = sorted(Path(gold_dir).rglob("*.json"))
    per_well, eras = [], {}
    agg = {"tp": 0, "fp": 0, "fn": 0}
    for gp in gold_paths:
        gold = json.loads(gp.read_text())
        pred_facts, pred_types = _load_pred_for_well(gold.get("api_number"), gold.get("uwi"))
        prf = field_prf(pred_facts, gold["gold_facts"])
        cal = calibration(pred_facts, gold["gold_facts"])
        cls = classification_accuracy(pred_types, gold.get("gold_doc_types", {}))
        per_well.append({"gold": gp.name, "era": gold.get("era", "unknown"),
                         "prf": prf, "calibration": cal, "classification": cls})
        for k in ("tp", "fp", "fn"):
            agg[k] += prf[k]
        e = eras.setdefault(gold.get("era", "unknown"), {"tp": 0, "fp": 0, "fn": 0})
        for k in ("tp", "fp", "fn"):
            e[k] += prf[k]

    def _pr(d: dict) -> dict:
        p = d["tp"] / (d["tp"] + d["fp"]) if (d["tp"] + d["fp"]) else 1.0
        r = d["tp"] / (d["tp"] + d["fn"]) if (d["tp"] + d["fn"]) else 1.0
        return {"precision": round(p, 4), "recall": round(r, 4), **d}

    return {"wells": per_well, "aggregate": _pr(agg),
            "per_era": {k: _pr(v) for k, v in eras.items()},
            "targets": {"precision": 0.97, "recall": 0.90, "calibration@0.9": 0.95,
                        "classification": 0.95}}  # §10.2
