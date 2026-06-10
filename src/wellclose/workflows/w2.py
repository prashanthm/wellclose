"""W2 — Portfolio Gap Triage (Brief §9.2): stages 1-6 across a well list; ranked readiness report."""
from __future__ import annotations
import json
from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from . import activities as A

LONG = timedelta(hours=4)
SHORT = timedelta(minutes=10)


@workflow.defn
class PortfolioTriageWorkflow:
    @workflow.run
    async def run(self, wells_json: str) -> str:
        """wells_json: [{well_id, source, selector}] -> ranked gap summary."""
        wells = json.loads(wells_json)
        results = []
        for w in wells:
            doc_ids = await workflow.execute_activity(
                A.act_acquire, args=[w["source"], json.dumps(w["selector"]), w["well_id"]],
                start_to_close_timeout=LONG)
            for d in doc_ids:
                await workflow.execute_activity(A.act_render, args=[d], start_to_close_timeout=LONG)
                await workflow.execute_activity(A.act_classify, args=[d], start_to_close_timeout=SHORT)
                await workflow.execute_activity(A.act_extract, args=[d], start_to_close_timeout=LONG)
                await workflow.execute_activity(A.act_resolve, args=[d], start_to_close_timeout=SHORT)
            await workflow.execute_activity(A.act_conflicts_and_validators, args=[w["well_id"]],
                                            start_to_close_timeout=SHORT)
            gap_id = await workflow.execute_activity(A.act_gap_analysis, args=[w["well_id"]],
                                                     start_to_close_timeout=SHORT)
            queue = await workflow.execute_activity(A.act_review_queue_size, args=[w["well_id"]],
                                                    start_to_close_timeout=SHORT)
            results.append({"well_id": w["well_id"], "gap_report_id": gap_id,
                            "review_queue": queue, "documents": len(doc_ids)})
        results.sort(key=lambda r: r["review_queue"])  # readiness proxy; refine with gap weights
        return json.dumps(results)
