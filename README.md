# WellClose AI — MVP

Agentic well abandonment & decommissioning data intelligence. Implements **Product Brief v1.4**
end to end: acquisition → render/OCR → classify → extract (3-pass) → resolve/validate →
historian → gap/rubric → HITL review → composed dossier with full provenance.

**Stack (OSS-only, Brief §11 / ADRs):** Temporal (durability + HITL, ADR-001) · Postgres FTS +
pgvector (ADR-002) · Tesseract/docTR adapter (ADR-003) · Strands Agents over MCP (ADR-004) ·
MinIO (ADR-005) · hash-pinned open models via LiteLLM→Ollama (ADR-006) · Mac-first (ADR-007) ·
Python, mypy strict (ADR-008).

## How to run

### Prerequisites

| Requirement | Why | Check |
|---|---|---|
| macOS on Apple Silicon, 64GB RAM (36GB works with `:7b` model tags) | local model inference | — |
| Homebrew | installs ollama + tesseract | `brew --version` |
| Docker Desktop or colima | Postgres, MinIO, Temporal, LiteLLM, Langfuse | `docker info` |
| Python 3.12+ | the pipeline | `python3 --version` |
| Node 18+ | reviewer UI | `node --version` |

### 1. One-time setup

```bash
git clone https://github.com/prashanthm/wellclose && cd wellclose

./scripts/setup_mac.sh
# This does, in order:
#   brew install ollama tesseract        (if missing)
#   ollama pull qwen2.5vl:32b qwen2.5:32b  (falls back to :7b on smaller machines)
#   docker compose up -d --wait          (waits for healthchecks — Postgres, MinIO, Temporal, LiteLLM, Langfuse)
#   pip install -e ".[dev]"
#   cp .env.example .env                 (edit if your ports/credentials differ)
#   wellclose init-db                    (creates schema + pg extensions)
```

Prefer a virtualenv? Create one first — the script's `pip install` will use it:

```bash
python3 -m venv .venv && source .venv/bin/activate   # or: uv venv && source .venv/bin/activate
```

### 2. Start the services (each in its own terminal, or background them)

```bash
wellclose worker        # Temporal worker — runs pipeline activities + agents
wellclose mcp           # MCP tool server :8000 — the agents' ONLY data path (§8.7)
wellclose review-api    # HITL review backend :8100
cd ui && npm install && npm run dev    # reviewer UI -> http://localhost:5173
```

Consoles you get from docker compose:

| Service | URL |
|---|---|
| Reviewer UI | http://localhost:5173 |
| Temporal UI | http://localhost:8233 |
| MinIO console | http://localhost:9001 (wellclose / wellclose-secret) |
| Langfuse traces | http://localhost:3000 |
| LiteLLM gateway | http://localhost:4000 |

### 3. Drive a well end-to-end

**Option A (recommended first run): local PDFs, no Temporal.** Drop any well-record PDFs in a folder:

```bash
wellclose ingest ./my-well-pdfs --api 42-085-31234 --jurisdiction TXRRC
wellclose pipeline --well-id <well_id>    # stages B–E: render/OCR -> classify -> extract -> resolve
wellclose gap <well_id>                   # rubric coverage + gap report
```

Then open http://localhost:5173 — review the queue (keys: **a** approve, **c** correct, **r** reject;
batch-approve clears everything clean ≥ T_auto), sign off, and compose:

```bash
wellclose dossier <well_id>               # composes from APPROVED facts only (§8.6)
```

**Option B: full W1 workflow via Temporal** (includes acquisition; verify portal endpoints first — TASKS.md T2.6):

```bash
wellclose run-w1 <well_id> txrrc '{"api8":"08531234"}'
# pauses at the HITL gate; the review UI signals review_complete + sign_off automatically
# manual signals if needed:
wellclose signal <well_id> review_complete
wellclose signal <well_id> sign_off --reviewer you@co
```

### 4. Tests and evals

```bash
pytest tests/ -q          # 14 unit/invariant tests, no services needed (CI runs these + ruff)
ruff check src tests evals
mypy src                  # strict; pre-existing debt is report-only in CI for now

# Eval harness (§10 targets: P>=0.97, R>=0.90, calibration@0.9 >=0.95) — needs a populated DB:
wellclose eval --gold-dir evals/gold --fail-under-precision 0.97 --fail-under-recall 0.90
```

Gold wells are the month-one priority (T7.3): build them per `evals/gold/SCHEMA.md` —
only a synthetic worked example ships today, so eval numbers are not meaningful yet.

### Troubleshooting

- **`docker compose up --wait` hangs** — check `docker compose ps`; Temporal's healthcheck needs
  Postgres healthy first and can take ~60s on first boot.
- **Agent calls fail** — Ollama runs natively (not in Docker) for Metal access: `brew services start ollama`,
  then confirm the gateway sees it: `curl localhost:4000/health`. On 36GB machines edit `.env` to the `:7b` tags.
- **`wellclose: command not found`** — re-run `pip install -e ".[dev]"` inside your active venv.
- **UI shows no wells** — facts only appear after `wellclose pipeline` ran and `resolve` attached them to a well;
  orphan facts (no API/UWI found) show in the queue's orphan section.

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
- Conflict groups and pass-3 verify scores survive Temporal retries (deterministic ids, inline plumbing).

Pilot security posture per §12: single-tenant, OIDC-ready review API (set `WC_REVIEW_OIDC_ISSUER`),
all services local; no data leaves the machine with `WC_ESCALATION_TIER=none`.
