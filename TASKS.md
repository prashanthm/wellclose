# WellClose AI — Build Task Ledger (maps to Product Brief v1.4)

Legend: [x] implemented in this repo | [R] implemented, requires local runtime to exercise (Docker/Ollama/network) | [ ] post-MVP per brief

## T0 Foundations (Brief §11, §13-M0)
- [x] T0.1 Repo layout, pyproject (uv-compatible), ruff+mypy strict config
- [x] T0.2 docker-compose laptop profile: Postgres+pgvector, MinIO, Temporal+UI, Langfuse, LiteLLM proxy (ADR-001/005, §11)
- [x] T0.3 LiteLLM gateway config routing to Ollama (Qwen2.5-VL tiers per §16.5)
- [x] T0.4 .env.example with every setting documented
- [x] T0.5 scripts/setup_mac.sh (brew: ollama, tesseract; ollama pull; docker compose up; db init)
- [R] T0.6 First-run verification of stack on Mac (Docker Desktop/colima required)

## T1 Data layer (Brief §5)
- [x] T1.1 SQLAlchemy 2.0 models: Well, Wellbore, CasingString, CompletionInterval, PluggingRecord, WellboreEvent, Document, ExtractedFact, Dossier (+ append-only fact status machine §5.1)
- [x] T1.2 MinIO object store: immutable raw (sha256 ids), derived artifacts (§4.5, §6.1)
- [x] T1.3 Postgres FTS (tsvector) + pgvector columns/indexes (ADR-002)
- [x] T1.4 Alembic-free init-db CLI (schema create + extensions)

## T2 Acquisition (Brief §4, Stage A)
- [x] T2.1 Source interface discover/fetch + politeness framework: 1 rps, backoff+jitter, circuit breaker, honest UA, robots check (§4.5)
- [x] T2.2 BSEE source module (bulk datasets + per-document fetch; endpoint constants in sources.yaml)
- [x] T2.3 TXRRC source module (wellbore/imaged-records fetch; endpoint constants in sources.yaml)
- [x] T2.4 Volve local-path adapter (no redistribution per §16.4 data rules)
- [x] T2.5 Provenance at fetch: url, timestamp, headers, checksum; SOURCES.md/LICENSES.md
- [x] T2.6 Endpoint constants verified against live portals 2026-06-10; `wellclose corpus verify-endpoints` re-probes on demand (Risk §14.2). Dead URLs replaced: BSEE per-report-type zips, TXRRC Neubus SPA flow, monthly orphan zip
- [x] T2.7 Corpus manifest builder + acquire driver: `wellclose corpus build|acquire|status` (src/wellclose/corpus.py). §4.1 GoM selection from BSEE borehole bulk, §4.2 TX from orphan inventory (CMPL search not crawled — robots Disallow). BSEE scanned files + Volve are manual per SOURCES.md

## T3 Document pipeline (Brief §7 Stages B–E)
- [x] T3.1 Stage B: pypdfium2 page render 300dpi, deskew hook, OCR adapter (Tesseract default, docTR optional ADR-003), ocr_quality_score
- [x] T3.2 Stage C: LLM classification + multi-record splitting, taxonomy per §7C
- [x] T3.3 Stage D: schema-guided extraction templates per doc_type; 3-pass (targeted, sweep, self-verify); diagram flag; provenance enforced at submit
- [x] T3.4 Stage E: entity resolution (API12/UWI, fuzzy), conflict groups, deterministic physical validators
- [R] T3.5 Run full corpus through pipeline (needs Ollama + acquired corpus)

## T4 Agents & MCP (Brief §8, ADR-004)
- [x] T4.1 MCP tool server (FastMCP): all 13 tools per §8.7, agent-identity logging
- [x] T4.2 Agent specs as data (YAML): acquisition, intake, extraction, historian, gap_rubric, composer — prompts, tool allowlists, output schemas, model assignment, hard rules (§8.3 invariants)
- [x] T4.3 Strands runner: loads spec → Agent with LiteLLM model + MCP tools
- [R] T4.4 Agent smoke runs against live LiteLLM/Ollama

## T5 Workflows & HITL (Brief §9, ADR-001)
- [x] T5.1 Temporal activities wrapping stages + agent invocations (idempotent, resumable §6.3)
- [x] T5.2 W1 Dossier Generation workflow with HITL signal-wait gate, incremental re-run
- [x] T5.3 W2 Portfolio Gap Triage (batch stages 1–6, ranked report)
- [x] T5.4 Review API (FastAPI): queue (conflicts, low-conf, diagram, validator, orphan), approve/correct/reject/batch-approve, signals Temporal on completion; correction capture for §9.4 training signal
- [x] T5.5 Reviewer UI (React+Tailwind, Vite): side-by-side fact ↔ page image, single-keystroke a/c/r, batch-approve ≥T_auto
- [ ] T5.6 W3 Permit Draft Assist (stretch, §9.3)

## T6 Rubric, gaps, dossier (Brief §5.3, §8.5–8.6)
- [x] T6.1 Rubric engine + BSEE Subpart Q and TXRRC 3.14 reference rubrics (criticality: blocker/major/minor)
- [x] T6.2 Gap analysis with suggested next sources
- [x] T6.3 Composer: approved-facts-only invariant, citation appendix, JSON + HTML→PDF render, immutable dossier versions
- [R] T6.4 SME review of rubrics (release gate, Risk §14.3)

## T7 Evals (Brief §10)
- [x] T7.1 Harness: field-level P/R, calibration, classification accuracy, per-era breakdown, cost/latency capture; CI-gateable CLI
- [x] T7.2 Gold-well JSON schema + 1 worked example + adversarial set scaffolding
- [ ] T7.3 Build 10 gold-standard wells (SME track, §10.1 — month-one priority)
- [R] T7.4 ADR-006 model bake-off on Mac at 7B/32B(/72B) quantizations

## T8 Observability & security (Brief §6.3, §12)
- [x] T8.1 Langfuse tracing with run/well/document correlation ids + per-call cost tags
- [x] T8.2 Keycloak-ready OIDC config stubs on review API (single-tenant pilot posture)
- [ ] T8.3 SOC2-track logging review

## First local run (your checklist)
1. ./scripts/setup_mac.sh   2. cp .env.example .env   3. docker compose up -d
4. wellclose init-db        5. ollama pull qwen2.5vl:32b (or :7b)   6. wellclose worker &
7. wellclose acquire --source txrrc --api 42-XXX-XXXXX (after T2.6)  8. wellclose run-w1 --well <id>
9. wellclose review-api & cd ui && npm i && npm run dev   10. approve queue → dossier renders
