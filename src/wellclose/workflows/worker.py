"""Temporal worker (ADR-001). Run: `wellclose worker`."""
from __future__ import annotations
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from ..config import settings
from . import activities as A
from .w1 import DossierGenerationWorkflow
from .w2 import PortfolioTriageWorkflow

ACTIVITIES = [A.act_acquire, A.act_render, A.act_classify, A.act_extract, A.act_resolve,
              A.act_conflicts_and_validators, A.act_historian, A.act_gap_analysis,
              A.act_review_queue_size, A.act_compose]


async def main() -> None:
    s = settings()
    client = await Client.connect(s.temporal_target, namespace=s.temporal_namespace)
    worker = Worker(client, task_queue=s.task_queue,
                    workflows=[DossierGenerationWorkflow, PortfolioTriageWorkflow],
                    activities=ACTIVITIES)
    print(f"WellClose worker on {s.temporal_target} queue={s.task_queue}")
    await worker.run()


def run() -> None:
    asyncio.run(main())
