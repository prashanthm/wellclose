"""W1 — Dossier Generation (Brief §9.1). Deterministic workflow; pauses at the HITL gate
(signal `review_complete`) and at final sign-off (signal `sign_off`). Incremental re-runs:
re-executing on the same well skips completed stages via idempotent activities."""
from __future__ import annotations
from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from . import activities as A

SHORT = timedelta(minutes=10)
LONG = timedelta(hours=4)
RETRY = None  # Temporal default retry policy; activities are idempotent (§6.3)


@workflow.defn
class DossierGenerationWorkflow:
    def __init__(self) -> None:
        self._review_complete = False
        self._signed_off_by: str | None = None

    @workflow.signal
    def review_complete(self) -> None:           # sent by review API when queue empties (§9.1.7)
        self._review_complete = True

    @workflow.signal
    def sign_off(self, reviewer: str) -> None:   # §9.1.9 final human sign-off
        self._signed_off_by = reviewer

    @workflow.run
    async def run(self, well_id: str, source: str, selector_json: str) -> str:
        rid = workflow.info().run_id
        # [1] Acquisition
        doc_ids: list[str] = await workflow.execute_activity(
            A.act_acquire, args=[source, selector_json, well_id],
            start_to_close_timeout=LONG)
        # [2-4] per-document fan-out: render -> classify -> extract -> resolve
        for d in doc_ids:
            await workflow.execute_activity(A.act_render, args=[d], start_to_close_timeout=LONG)
            await workflow.execute_activity(A.act_classify, args=[d], start_to_close_timeout=SHORT)
        for d in doc_ids:
            await workflow.execute_activity(A.act_extract, args=[d], start_to_close_timeout=LONG)
            await workflow.execute_activity(A.act_resolve, args=[d], start_to_close_timeout=SHORT)
        await workflow.execute_activity(A.act_conflicts_and_validators, args=[well_id],
                                        start_to_close_timeout=SHORT)
        # [5] Historian
        await workflow.execute_activity(A.act_historian, args=[well_id, rid],
                                        start_to_close_timeout=LONG)
        # [6] Gap & rubric
        await workflow.execute_activity(A.act_gap_analysis, args=[well_id],
                                        start_to_close_timeout=SHORT)
        # [7] HITL GATE — wait for reviewer (days are fine; Temporal durably persists)
        queue = await workflow.execute_activity(A.act_review_queue_size, args=[well_id],
                                                start_to_close_timeout=SHORT)
        if queue > 0:
            await workflow.wait_condition(lambda: self._review_complete)
        # [9] sign-off gate, then [8] compose from approved facts only
        await workflow.wait_condition(lambda: self._signed_off_by is not None)
        return await workflow.execute_activity(
            A.act_compose, args=[well_id, self._signed_off_by or ""],
            start_to_close_timeout=LONG)
