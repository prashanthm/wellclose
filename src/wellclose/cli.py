"""WellClose CLI (matches TASKS.md first-run checklist)."""
from __future__ import annotations
import asyncio
import json
import typer

app = typer.Typer(name="wellclose", no_args_is_help=True,
                  help="WellClose AI — abandonment dossier pipeline (Brief v1.4)")


@app.command()
def init_db() -> None:
    """Create Postgres extensions + schema (T1.4)."""
    from .db import init_db as _init
    _init()
    typer.echo("schema + extensions ready")


@app.command()
def ingest(path: str, source: str = "upload", api: str = "", uwi: str = "",
           jurisdiction: str = "TXRRC") -> None:
    """Ingest a local document (file or directory) and attach to a well."""
    from pathlib import Path
    from .pipeline.acquire import ensure_well, ingest_local
    well_id = ensure_well(api_number=api or None, uwi=uwi or None,
                          jurisdiction=jurisdiction) if (api or uwi) else None
    p = Path(path)
    files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.suffix.lower() == ".pdf")
    for f in files:
        doc_id = ingest_local(str(f), source, well_id)
        typer.echo(f"{f.name} -> {doc_id[:16]}…  well={well_id}")


@app.command()
def acquire(source: str, selector: str, api: str = "", jurisdiction: str = "TXRRC") -> None:
    """Acquire from a source. selector is JSON, e.g. '{"api8":"08531234"}' (T2)."""
    from .pipeline.acquire import acquire as _acq, ensure_well
    well_id = ensure_well(api_number=api or None, jurisdiction=jurisdiction) if api else None
    ids = _acq(source, json.loads(selector), well_id)
    typer.echo(json.dumps({"documents": ids}, indent=2))


@app.command()
def pipeline(document_id: str = "", well_id: str = "") -> None:
    """Run stages B-E directly (no Temporal) for a document or every acquired doc of a well."""
    from sqlalchemy import select
    from .db import session
    from .models import Document
    from .pipeline.classify import classify_document
    from .pipeline.extract import extract_document
    from .pipeline.render import render_document
    from .pipeline.resolve import detect_conflicts, resolve_well, run_validators
    with session() as s:
        if document_id:
            ids = [document_id]
        else:
            ids = list(s.scalars(select(Document.document_id).where(
                Document.well_id == well_id, Document.split_parent_id.is_(None))))
    wells = set()
    for d in ids:
        typer.echo(f"render {d[:12]}… pages={render_document(d)}")
        typer.echo(f"classify -> {classify_document(d)}")
        with session() as s:
            children = list(s.scalars(select(Document.document_id).where(
                Document.split_parent_id == d)))
        for target in (children or [d]):
            n = extract_document(target)
            w = resolve_well(target)
            typer.echo(f"extract {target[:20]}… facts={n} well={w}")
            if w:
                wells.add(w)
    for w in wells | ({well_id} if well_id else set()):
        typer.echo(f"conflicts={detect_conflicts(w)} validator_flags={run_validators(w)}")


@app.command()
def run_w1(well_id: str, source: str, selector: str) -> None:
    """Start W1 Dossier Generation on Temporal (workflow id w1-<well_id>)."""
    from temporalio.client import Client
    from .config import settings
    from .workflows.w1 import DossierGenerationWorkflow

    async def go() -> None:
        s = settings()
        client = await Client.connect(s.temporal_target, namespace=s.temporal_namespace)
        handle = await client.start_workflow(
            DossierGenerationWorkflow.run, args=[well_id, source, selector],
            id=f"w1-{well_id}", task_queue=s.task_queue)
        typer.echo(f"started w1-{well_id} run={handle.result_run_id}")
    asyncio.run(go())


@app.command()
def run_w2(wells_json_path: str) -> None:
    """Start W2 Portfolio Triage; arg = path to JSON [{well_id, source, selector}]."""
    from pathlib import Path
    from temporalio.client import Client
    from .config import settings
    from .workflows.w2 import PortfolioTriageWorkflow

    async def go() -> None:
        s = settings()
        client = await Client.connect(s.temporal_target, namespace=s.temporal_namespace)
        handle = await client.start_workflow(
            PortfolioTriageWorkflow.run, args=[Path(wells_json_path).read_text()],
            id="w2-portfolio", task_queue=s.task_queue)
        typer.echo(await handle.result())
    asyncio.run(go())


@app.command()
def signal(well_id: str, name: str, reviewer: str = "cli") -> None:
    """Send review_complete | sign_off to w1-<well_id> (manual HITL driving)."""
    from temporalio.client import Client
    from .config import settings

    async def go() -> None:
        s = settings()
        client = await Client.connect(s.temporal_target, namespace=s.temporal_namespace)
        handle = client.get_workflow_handle(f"w1-{well_id}")
        await (handle.signal(name, reviewer) if name == "sign_off" else handle.signal(name))
        typer.echo(f"signaled {name}")
    asyncio.run(go())


@app.command()
def gap(well_id: str, jurisdiction: str = "") -> None:
    """Run rubric gap analysis now (§8.5)."""
    from .rubric import gap_analysis
    typer.echo(f"gap_report_id={gap_analysis(well_id, jurisdiction or None)}")


@app.command()
def dossier(well_id: str, signed_off_by: str = "cli") -> None:
    """Compose dossier from approved facts (§8.6 invariant enforced)."""
    from .dossier import compose
    typer.echo(f"dossier_id={compose(well_id, signed_off_by=signed_off_by)}")


@app.command()
def worker() -> None:
    """Run the Temporal worker (ADR-001)."""
    from .workflows.worker import run
    run()


@app.command()
def review_api() -> None:
    """Run the HITL review backend on :8100."""
    from .review.api import main
    main()


@app.command()
def mcp() -> None:
    """Run the MCP tool server on :8000 (§8.7)."""
    from .mcp_server import main
    main()


@app.command()
def agent(spec: str, task: str) -> None:
    """Run a single agent (requires `wellclose mcp` + LiteLLM gateway up)."""
    from .agents.runner import run_agent
    typer.echo(run_agent(spec, task))


@app.command(name="eval")
def eval_cmd(gold_dir: str = "evals/gold", fail_under_precision: float = 0.0,
             fail_under_recall: float = 0.0) -> None:
    """Run the eval harness against gold wells (§10); CI-gateable via thresholds."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path.cwd()))
    from evals.harness import run as run_evals
    report = run_evals(gold_dir)
    typer.echo(json.dumps(report, indent=2))
    if report["aggregate"]["precision"] < fail_under_precision or \
       report["aggregate"]["recall"] < fail_under_recall:
        raise typer.Exit(1)
