# WellClose AI — MVP

Agentic well abandonment & decommissioning data intelligence. Implements **Product Brief v1.4**
end to end: acquisition → render/OCR → classify → extract (3-pass) → resolve/validate →
historian → gap/rubric → HITL review → composed dossier with full provenance.

**Stack (OSS-only, Brief §11 / ADRs):** Temporal (durability + HITL, ADR-001) · Postgres FTS +
pgvector (ADR-002) · Tesseract/docTR adapter (ADR-003) · Strands Agents over MCP (ADR-004) ·
MinIO (ADR-005) · hash-pinned open models via LiteLLM→Ollama (ADR-006) · Mac-first (ADR-007) ·
Python, mypy strict (ADR-008).

## Quickstart (Apple Silicon, 64GB recommended; 36GB → use :7b model tags)

```bash
./scripts/setup_mac.sh          # brew deps, ollama pull, docker compose up, pip install -e ., init-db
wellclose worker &              # Temporal worker
wellclose mcp &                 # MCP tool server :8000 (agents' only data path, §8.7)
wellclose review-api &          # HITL backend :8100
cd ui && npm install && npm run dev &   # reviewer UI :5173
```

### Drive a well end-to-end

```bash
# Option A (recommended first run): local documents — drop PDFs in a folder
wellclose ingest ./my-well-pdfs --api 42-085-31234 --jurisdiction TXRRC
wellclose pipeline --well-id <well_id>          # stages B–E without Temporal
wellclose gap <well_id>                          # rubric coverage + gaps
# → review queue in the UI (http://localhost:5173): a/c/r keys, batch-approve, sign off
wellclose dossier <well_id>                      # composes from APPROVED facts only

# Option B: full W1 via Temporal (acquisition included; verify endpoints first — TASKS.md T2.6)
wellclose run-w1 <well_id> txrrc '{"api8":"08531234"}'
# workflow pauses at HITL; the review UI signals review_complete + sign_off automatically
# manual signals if needed:
wellclose signal <well_id> review_complete
wellclose signal <well_id> sign_off --reviewer you@co
```

### Evals (§10 targets: P≥0.97, R≥0.90, calibration@0.9 ≥0.95)
```bash
wellclose eval --gold-dir evals/gold --fail-under-precision 0.97 --fail-under-recall 0.90
```
Build gold wells per `evals/gold/SCHEMA.md` (10 SME-verified wells is the month-one goal, T7.3).

## Layout
`src/wellclose/` pipeline · agents (YAML specs + Strands runner) · workflows (Temporal W1/W2) ·
mcp_server (13 tools) · review (HITL API) · rubrics · templates — `ui/` React+Tailwind reviewer —
`evals/` harness — `TASKS.md` full ledger incl. **first-run checklist and [R] items you must
exercise locally** (Docker, Ollama, portal endpoint verification).

## Invariants you can rely on (and tests assert)
- No fact without page + verbatim snippet — rejected at `submit_facts` (§8.3).
- Dossier composes **approved/corrected facts only**; zero approved facts → hard error (§8.6).
- Raw documents immutable, content-hash addressed; facts append-only, superseded not deleted (§5.1).
- Diagram-derived facts always route to human review (§7D); escalation tier off by default (§16.4).

Pilot security posture per §12: single-tenant, OIDC-ready review API (set `WC_REVIEW_OIDC_ISSUER`),
all services local; no data leaves the machine with `WC_ESCALATION_TIER=none`.
