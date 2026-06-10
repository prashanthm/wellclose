"""HITL Review API (Brief §9.1.7, §9.4). Serves the reviewer UI:
- queue = proposed facts that are conflicted, diagram-derived, validator-flagged, low-confidence,
  or orphaned (no well) — everything else is batch-approvable at >= T_auto.
- approve / correct / reject; corrections captured as training signal (§9.4).
- page image proxy from MinIO for side-by-side display.
- signals Temporal W1 `review_complete` when a well's queue empties, `sign_off` on reviewer sign-off.
- Keycloak OIDC: set WC_REVIEW_OIDC_ISSUER to enforce bearer tokens (§12); blank = dev mode."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import or_, select
from .. import storage
from ..config import settings
from ..db import session
from ..models import Document, ExtractedFact, GapReport, Well

app = FastAPI(title="WellClose Review API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_jwks_cache: dict[str, Any] = {}


async def auth(request: Request) -> str:
    """OIDC bearer check (Keycloak-ready). Dev mode when issuer unset."""
    issuer = settings().review_oidc_issuer
    if not issuer:
        return request.headers.get("X-Reviewer", "dev-reviewer")
    token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "missing bearer token")
    try:
        import jwt
        from jwt import PyJWKClient
        if "client" not in _jwks_cache:
            meta = httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=10).json()
            _jwks_cache["client"] = PyJWKClient(meta["jwks_uri"])
        key = _jwks_cache["client"].get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], options={"verify_aud": False})
        return claims.get("preferred_username") or claims["sub"]
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, f"token validation failed: {e}") from e


def _fact_out(f: ExtractedFact) -> dict:
    return {"fact_id": f.fact_id, "well_id": f.well_id, "field_path": f.field_path,
            "value": f.value, "corrected_value": f.corrected_value, "unit": f.unit,
            "document_id": f.document_id, "page": f.page, "snippet": f.snippet,
            "confidence": f.extraction_confidence, "verify_confidence": f.verify_confidence,
            "status": f.status, "conflict_group_id": f.conflict_group_id,
            "validation_flags": f.validation_flags, "diagram": f.derived_from_diagram}


@app.get("/api/wells")
def wells(reviewer: str = Depends(auth)) -> list[dict]:
    with session() as s:
        out = []
        for w in s.scalars(select(Well)):
            proposed = s.scalars(select(ExtractedFact.fact_id).where(
                ExtractedFact.well_id == w.well_id, ExtractedFact.status == "proposed")).all()
            out.append({"well_id": w.well_id, "api_number": w.api_number, "uwi": w.uwi,
                        "name": w.name, "jurisdiction": w.jurisdiction,
                        "proposed_facts": len(proposed)})
        return out


def _queue_query(well_id: str):
    t = settings().t_auto
    return select(ExtractedFact).where(
        ExtractedFact.well_id == well_id, ExtractedFact.status == "proposed",
        or_(ExtractedFact.conflict_group_id.is_not(None),
            ExtractedFact.derived_from_diagram.is_(True),
            ExtractedFact.validation_flags.is_not(None),
            ExtractedFact.extraction_confidence < t)).order_by(
        ExtractedFact.conflict_group_id, ExtractedFact.field_path)


@app.get("/api/wells/{well_id}/queue")
def queue(well_id: str, reviewer: str = Depends(auth)) -> dict:
    with session() as s:
        items = [_fact_out(f) for f in s.scalars(_queue_query(well_id))]
        orphans = [_fact_out(f) for f in s.scalars(select(ExtractedFact).where(
            ExtractedFact.well_id.is_(None), ExtractedFact.status == "proposed"))]
        auto = s.scalars(select(ExtractedFact.fact_id).where(
            ExtractedFact.well_id == well_id, ExtractedFact.status == "proposed",
            ExtractedFact.conflict_group_id.is_(None),
            ExtractedFact.derived_from_diagram.is_(False),
            ExtractedFact.validation_flags.is_(None),
            ExtractedFact.extraction_confidence >= settings().t_auto)).all()
        gap = s.scalars(select(GapReport).where(GapReport.well_id == well_id)
                        .order_by(GapReport.created_at.desc())).first()
        return {"queue": items, "orphan_facts": orphans, "batch_approvable": len(auto),
                "t_auto": settings().t_auto,
                "gaps": gap.gaps if gap else []}


class Decision(BaseModel):
    action: str                      # approve | correct | reject
    corrected_value: str | None = None
    note: str | None = None


@app.post("/api/facts/{fact_id}/decision")
async def decide(fact_id: str, d: Decision, reviewer: str = Depends(auth)) -> dict:
    with session() as s:
        f = s.get(ExtractedFact, fact_id)
        if f is None:
            raise HTTPException(404, "unknown fact")
        if d.action == "approve":
            f.status = "approved"
        elif d.action == "correct":
            if not d.corrected_value:
                raise HTTPException(400, "corrected_value required")
            f.status = "corrected"
            f.corrected_value = d.corrected_value   # §9.4 training signal
        elif d.action == "reject":
            f.status = "rejected"
        else:
            raise HTTPException(400, "action must be approve|correct|reject")
        f.reviewer_id = reviewer
        f.review_timestamp = datetime.now(timezone.utc)
        if d.note:
            f.validation_flags = (f.validation_flags or []) + [f"reviewer_note: {d.note[:300]}"]
        well_id = f.well_id
    remaining = await _signal_if_done(well_id) if well_id else None
    return {"ok": True, "queue_remaining": remaining}


@app.post("/api/wells/{well_id}/batch-approve")
async def batch_approve(well_id: str, reviewer: str = Depends(auth)) -> dict:
    """Approve all clean facts >= T_auto (§9.4 batch approval)."""
    n = 0
    with session() as s:
        for f in s.scalars(select(ExtractedFact).where(
                ExtractedFact.well_id == well_id, ExtractedFact.status == "proposed",
                ExtractedFact.conflict_group_id.is_(None),
                ExtractedFact.derived_from_diagram.is_(False),
                ExtractedFact.validation_flags.is_(None),
                ExtractedFact.extraction_confidence >= settings().t_auto)):
            f.status = "approved"
            f.reviewer_id = reviewer
            f.review_timestamp = datetime.now(timezone.utc)
            n += 1
    remaining = await _signal_if_done(well_id)
    return {"approved": n, "queue_remaining": remaining}


@app.post("/api/wells/{well_id}/sign-off")
async def sign_off(well_id: str, reviewer: str = Depends(auth)) -> dict:
    """Final sign-off (§9.1.9) -> Temporal `sign_off` signal; composer then runs."""
    await _signal(well_id, "sign_off", reviewer)
    return {"signed_off_by": reviewer}


async def _signal_if_done(well_id: str) -> int:
    with session() as s:
        remaining = len(s.scalars(_queue_query(well_id)).all())
    if remaining == 0:
        await _signal(well_id, "review_complete")   # §9.1.7 workflow resumes
    return remaining


async def _signal(well_id: str, signal: str, *args: str) -> None:
    """Best-effort signal to W1 (workflow id convention: w1-<well_id>). Silent if no run."""
    try:
        from temporalio.client import Client
        s = settings()
        client = await Client.connect(s.temporal_target, namespace=s.temporal_namespace)
        handle = client.get_workflow_handle(f"w1-{well_id}")
        await handle.signal(signal, *args)
    except Exception:
        pass  # workflow may not be running (e.g., pipeline driven manually)


@app.get("/api/pages/{document_id}/{page}.png")
def page_image(document_id: str, page: int, reviewer: str = Depends(auth)) -> Response:
    data = storage.get_derived(f"pages/{document_id.split(':')[0]}/{page}.png")
    return Response(content=data, media_type="image/png")


def main() -> None:
    import uvicorn
    uvicorn.run("wellclose.review.api:app", host="127.0.0.1", port=8100)
