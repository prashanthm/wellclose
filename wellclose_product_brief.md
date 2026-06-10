# Product Brief: WellClose AI (working name)
## Agentic Well Abandonment & Decommissioning Data Intelligence Platform

**Version:** 1.4 (MVP build specification — open-source stack, Mac-first MVP compute, ADR appendix)
**Status:** Handoff-ready for build agents
**Audience:** Engineering/build agents, founding engineers, design partners
**Stack policy:** The product itself is proprietary, but it is built **exclusively on open-source components** — no AWS managed-service dependencies, no frontier-model API dependencies in the default path. Self-hostable anywhere; the MVP runs entirely on a single Apple Silicon Mac (laptop profile), scaling to GPU clusters later via the same containerized services (cluster profile). See §11 and §16. An optional, config-gated frontier-model escalation tier exists for deployments that permit it (§16.4).

---

## 1. Executive Summary

WellClose AI ingests decades of scattered, messy well records — scanned reports, casing diagrams, cement records, regulatory filings — and uses agentic AI to produce **abandonment-readiness dossiers**: verified, citation-backed compilations of everything required to plan, cost, permit, and execute the plug & abandonment (P&A) of a well.

**The problem:** Before a well can be abandoned, engineers spend 2–6 weeks per well hunting records across regulator archives, internal ECM systems, microfilm scans, and legacy databases. Records are incomplete, contradictory, and paper-era. With 14,000+ inactive Gulf of Mexico wells, 10,000+ North Sea wells scheduled for removal, ~130,000 documented US orphan wells, and $4.7B in federal orphan-well funding, this is a deadline-driven, CFO-visible bottleneck.

**The product:** An agentic pipeline that crawls public regulator archives and customer document stores, extracts well construction/history facts with full provenance, identifies data gaps, and assembles dossiers that a petroleum engineer reviews and approves through a human-in-the-loop (HITL) interface.

**MVP success definition:** Generate a dossier for any well in the MVP corpus (Gulf of Mexico + Texas + Volve) that a domain reviewer rates ≥90% complete relative to manual compilation, in <1 hour of compute and <2 hours of human review, with every extracted fact traceable to a source document page.

**Core economics:** Inference + processing cost per well: target <$300. Price point: $5k–15k/well offshore, $300–1,000/well onshore portfolios. Gross margin on AI work: >95%.

---

## 2. Users and Jobs To Be Done

| Persona | Role | Job to be done | Success metric |
|---|---|---|---|
| **Decommissioning engineer** (primary) | Plans P&A campaigns at an operator | "Give me everything known about this well's construction so I can design the abandonment program" | Dossier time: weeks → hours |
| **Wells/asset records manager** | Owns the data estate | "Tell me which of my 5,000 idle wells have dangerous data gaps" | Portfolio gap report |
| **Regulatory/permitting specialist** | Files abandonment permits | "Draft the permit package with supporting evidence" | Permit draft + evidence bundle |
| **ARO/finance analyst** | Reports asset retirement obligations | "Defensible cost-basis data per well for the balance sheet" | Auditable per-well data confidence score |
| **Government orphan-well program officer** | Prioritizes plugging spend | "Reconstruct records for orphan wells and rank by risk" | Per-well records reconstruction at volume |

**Primary MVP persona:** the decommissioning engineer. Everything else is roadmap.

---

## 3. MVP Scope and Non-Goals

### In scope (MVP)
1. Ingestion of public well records from **BSEE/BOEM (Gulf of Mexico)**, **Texas Railroad Commission (RRC)**, and the **Equinor Volve open dataset**
2. Document processing pipeline: acquisition → OCR → classification → extraction → normalization → storage
3. Canonical well data model (OSDU-aligned, see §5)
4. Five core agents (see §8) orchestrated into the **Dossier Generation Workflow** (see §9)
5. Provenance: every extracted fact links to (document_id, page, bounding box where available, extraction confidence)
6. Gap analysis: per-well report of required-vs-found dossier elements
7. HITL reviewer web UI: side-by-side fact vs. source page, approve/correct/reject per fact
8. Dossier export: PDF report + structured JSON
9. Eval harness with gold-standard wells (see §11)

### Explicit non-goals (MVP)
- No customer-internal data connectors (Phase 2: SharePoint/ECM, Petrel, OpenWorks, PI)
- No P&A engineering design (barrier placement design, cement program design) — we compile inputs, we do not engineer the abandonment
- No cost estimation module (Phase 2)
- No CCUS legacy-well screening (Phase 3)
- No real-time/streaming data
- No multi-tenant SaaS hardening beyond basic org isolation (single-tenant pilot deployments acceptable)
- No automated regulatory submission — drafts only, human files

---

## 4. Data Sources Specification (MVP Corpus)

Target MVP corpus: **~50 GoM offshore wells (BSEE) + ~200 Texas onshore wells (RRC) + Volve field (all wells)**.

### 4.1 BSEE / BOEM — Gulf of Mexico (offshore complexity)
- **Access:** BSEE Data Center (data.bsee.gov) — public, bulk-downloadable datasets and per-well document queries. No authentication required for public records. Respect posted usage terms; throttle politely (≤1 req/sec, exponential backoff).
- **Key datasets to acquire:**
  - Borehole/well master data (API number, surface/bottomhole location, status, operator history)
  - Well Activity Reports (WARs)
  - Applications for Permit to Modify (APMs) — includes P&A permits and procedures
  - End of Operations Reports (EORs)
  - Casing and completion records
  - Platform/structure and decommissioning datasets
  - Sundry notices
- **Formats:** CSV/XLSX bulk tables + scanned PDFs (mixed quality: typed forms, handwritten entries, diagrams)
- **Well selection criteria for the 50-well corpus:** inactive status; mix of shelf-era (1960s–80s, worst records) and modern wells; at least 10 wells with completed P&A (so gold-standard "what the dossier should contain" is verifiable); at least 3 operators currently active in decommissioning (demo relevance).

### 4.2 Texas Railroad Commission — onshore volume and legacy chaos
- **Access:** RRC online research queries (wellbore query, completions query) and the imaged records system. Public. Some imaged documents are fetched per-document; build a polite crawler with caching — never re-fetch.
- **Key record types:**
  - W-2 (oil completion) / G-1 (gas completion) reports
  - W-3 (plugging record) and W-3A (notice of intention to plug)
  - Casing/cementing records embedded in completion filings
  - Wellbore schematics (scanned, often hand-drawn)
  - GAU groundwater protection determinations
  - P-4 operator transfer history
- **Formats:** scanned TIFF/PDF spanning 1930s–present; microfilm-quality images; handwriting; rotated/skewed pages. **This is the OCR/extraction hardening corpus — treat difficulty as the feature.**
- **Well selection criteria for the 200-well corpus:** stratified sample across decades (pre-1960, 1960–1990, post-1990), districts, and statuses (plugged, inactive/idle, orphaned from the RRC orphan list). Include ≥30 wells from the state orphan inventory for the government use case.

### 4.3 Equinor Volve open dataset — clean international reference
- **Access:** Volve data village release (registration may be required; license permits use — verify current license terms at acquisition time and record them in `data/LICENSES.md`).
- **Key content:** end-of-well reports, daily drilling reports, casing/cement reports, well schematics, logs, plus full subsurface context.
- **Role:** polished demo dataset, North Sea document-format coverage, and OSDU-format reference (Volve is widely available in OSDU manifests — use it to validate OSDU alignment of our schema).

### 4.4 Supporting reference data
- DOI/IIJA state orphan well inventories (prioritization dataset)
- BOEM block/lease reference tables (spatial join keys)
- Texas RRC orphan well list (Form-issued)
- Regulator rule texts: BSEE 30 CFR 250 Subpart Q (decommissioning), TX RRC Rule 3.14 (plugging) — used as the **dossier requirements rubric** (see §5.3)

### 4.5 Data acquisition rules (binding on all agents)
1. Public sources only in MVP. No commercial aggregators (Enverus, S&P, TGS, Katalyst content) — licensed, not public.
2. Record provenance at fetch time: source URL, fetch timestamp, HTTP headers, checksum. Store raw bytes immutably (write-once bucket).
3. Respect robots.txt and posted terms; identify the crawler honestly in User-Agent; rate-limit per §4.1/§4.2.
4. Every document gets a stable `document_id = sha256(raw_bytes)` — dedupe on content hash.
5. Maintain `data/LICENSES.md` and `data/SOURCES.md` documenting terms for each source.

---

## 5. Canonical Data Model

### 5.1 Design principles
- **OSDU-aligned, not OSDU-dependent.** Field names and entity boundaries map to OSDU well/wellbore/wellbore-trajectory and work-product-component concepts so future OSDU export is a transformation, not a redesign. MVP storage is Postgres + object store; OSDU manifest export is a Phase 2 adapter.
- **Facts are first-class, with provenance.** The atomic unit is an `ExtractedFact`, not a filled field. Entity records are *materialized views* over approved facts. Conflicting facts coexist with a resolution status.
- **Append-only.** Facts are never destroyed; they are superseded or rejected. Full audit trail.

### 5.2 Core entities

```
Well
  well_id (internal), api_number/uwi, regulator_ids[], name, operator_history[],
  surface_location (lat/lon, CRS, datum), spud_date, status, status_history[],
  water_depth | ground_elevation, lease/block refs

Wellbore (1..n per Well)
  wellbore_id, parent_well_id, sidetrack_flag, td_md, td_tvd, trajectory_summary

CasingString (0..n per Wellbore)
  size_od, weight, grade, top_md, shoe_md, cement_top (and how determined:
  reported | CBL | calculated | unknown), cement_volume, cement_class,
  centralization_notes, pressure_test_records[]

CompletionInterval (0..n)
  top_md, base_md, formation, perforation_records[], status (open|squeezed|isolated)

PluggingRecord (0..n)
  plug_number, type (cement|mechanical|cast_iron_bridge), top_md, base_md,
  volume, verification_method, date, regulator_form_ref

WellboreEvent (0..n)
  type (fish_lost|junk|casing_cut|stuck_pipe|sidetrack|squeeze|integrity_test|...),
  date, depth_range, narrative, severity_flag

Document
  document_id (sha256), source, source_url, fetch_meta, doc_type (classified),
  page_count, ocr_quality_score, raw_uri, normalized_text_uri

ExtractedFact
  fact_id, well_id?, wellbore_id?, entity_type, field_path, value, unit,
  document_id, page, bbox?, snippet, extraction_confidence (0–1),
  extractor_version, status (proposed|approved|corrected|rejected|superseded),
  reviewer_id?, review_timestamp?, conflict_group_id?

DossierRequirement (rubric item, see 5.3)
  requirement_id, jurisdiction (BSEE|TXRRC|NSTA|...), rubric_text, category,
  satisfied_by_entity/field, criticality (blocker|major|minor)

Dossier
  dossier_id, well_id, version, requirement_coverage[], gap_list[],
  confidence_summary, approved_facts_snapshot, generated_artifacts[]
```

### 5.3 The dossier rubric (the product's backbone)
The rubric defines what a complete abandonment dossier must contain, **per jurisdiction**, derived from regulation and operator practice. Initial rubrics to author (human + agent-assisted, then SME-reviewed):

- **BSEE (30 CFR 250 Subpart Q):** well construction summary, all casing strings with cement tops + verification basis, open/perforated intervals, known wellbore obstructions/fish, sustained casing pressure history, current barrier status, lease/structure context, prior P&A attempts, required permit forms list.
- **TX RRC (Rule 3.14 + W-3A requirements):** usable-quality water depth (GAU determination), casing/cement records, perforations, prior plugging, surface equipment, operator-of-record chain (P-4 history).
- Rubric items carry `criticality`: a **blocker** gap (e.g., unknown cement top behind production casing) is the headline of the gap report.

### 5.4 Units, datums, and normalization rules
- Canonical units: depths in feet MD/TVD with explicit reference datum (KB/RT/MSL) — datum MUST be captured or flagged `datum_unknown`; metric preserved as original where source is metric (Volve), with conversion stored alongside, never overwriting.
- Dates normalized to ISO 8601; original string preserved.
- API numbers normalized to 12-digit (US); UWI for international.
- Every normalization records the rule version applied (`normalizer_version`).

---

## 6. System Architecture

### 6.1 Component overview

```
                        ┌─────────────────────────────────────────────┐
                        │                ORCHESTRATOR                  │
                        │   (workflow engine: Temporal OSS;           │
                        │    agent runtime: Strands Agents SDK         │
                        │    inside Temporal activities)               │
                        └───────┬─────────────────────────┬───────────┘
                                │                         │
        ┌───────────────────────┼─────────────┐           │
        ▼                       ▼             ▼           ▼
┌───────────────┐    ┌──────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│ ACQUISITION    │    │ DOCUMENT         │  │ EXTRACTION      │  │ DOSSIER &        │
│ SERVICE        │    │ PIPELINE         │  │ AGENTS          │  │ REVIEW SERVICE   │
│ crawlers per   │───▶│ OCR, classify,   │─▶│ schema-guided   │─▶│ rubric engine,   │
│ source (BSEE,  │    │ split, quality   │  │ fact extraction │  │ gap analysis,    │
│ TXRRC, Volve)  │    │ score, layout    │  │ + provenance    │  │ HITL review UI,  │
└──────┬─────────┘    └──────┬───────────┘  └──────┬──────────┘  │ dossier render   │
       │                     │                     │             └──────┬───────────┘
       ▼                     ▼                     ▼                    ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              STORAGE LAYER                                       │
│  MinIO raw (immutable, versioned, object-lock)  │  MinIO derived (text, images) │
│  PostgreSQL (entities, facts, rubric, review state)                              │
│  OpenSearch + pgvector (keyword + semantic index over normalized text)           │
└──────────────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │  MCP TOOL SERVER    │  ← agents access ALL data through
                     │  (single gateway)   │     typed MCP tools, never raw DB
                     └─────────────────────┘
```

### 6.2 Key architectural decisions and trade-offs

| Decision | Choice | Trade-off accepted |
|---|---|---|
| Agent data access | All agent reads/writes go through an MCP tool server with typed tools | Slight latency overhead; gains: auditability, swappable backends, framework-agnostic agents |
| Workflow engine | Temporal (OSS, self-hosted) owns durability, retries, and the HITL pause/resume; agents are steps within it (ADR-001) | Two systems to learn (Temporal + agent SDK); gains: liability-grade resumability, deterministic stage boundaries, cost control |
| Agent framework | Strands Agents SDK (Apache-2.0) for the agent loop, run inside Temporal activities; MCP-native, model-agnostic (ADR-004). Agent definitions (prompts, tool lists, output schemas) stored as data, not code — framework swap (e.g., to LangGraph) stays a contained refactor. CrewAI evaluated and rejected: autonomy-first crews fit collaborative prototyping, not deterministic regulated pipelines | Younger ecosystem than LangGraph; gains: thinnest possible layer over our MCP gateway, no duplicate state machine alongside Temporal |
| Extraction strategy | Open-weight vision-language models (§16.2) with JSON-schema-constrained output, page-image + OCR text together | Open VLMs trail frontier models on degraded handwriting — mitigated by eval-gated model selection, ensemble/escalation routing (§16.4) |
| Storage | PostgreSQL + MinIO + OpenSearch/pgvector; OSDU export as adapter | Not OSDU-native day one; gains: 10x iteration speed for MVP; OSDU alignment preserved via schema mapping (§5.1) |
| Conflict handling | Facts coexist; resolution is explicit (auto-rules + human) | More complex than last-write-wins; required for liability-grade trust |

### 6.3 Non-functional requirements (MVP)
- **Throughput:** laptop profile (MVP): corpus processed as overnight batch; a 1,000-page well file completes in <12 hrs on a 64GB Apple Silicon Mac; single documents extract interactively (<2 min for a 10-page filing). Cluster profile (pilot): 1,000-page well in <1 hr on one 80GB-class GPU.
- **Cost:** laptop profile: marginal cost ≈ 0 (owned hardware) — still instrument per-well token/time accounting from day one (tag every LLM call with well_id) so cluster-profile economics (<$300 offshore / <$30 onshore per well) are projectable before buying any GPU time.
- **Reliability:** any pipeline stage idempotent and resumable; partial failure of one document never blocks the well's dossier (gap-flag instead).
- **Auditability:** reconstruct any dossier value → fact → document page → raw fetch in one query.
- **Security:** single-tenant deployment per pilot; SSO (OIDC); encrypted at rest/in transit; no customer data in MVP (public corpus) but build as if there will be.

---

## 7. Ingestion & Document Pipeline Specification

Each stage emits events; the orchestrator advances documents through stages independently.

### Stage A — Acquisition
- One crawler module per source implementing a common interface: `discover(well_selector) -> [document_refs]`, `fetch(document_ref) -> raw_bytes + fetch_meta`.
- Politeness: per-source rate limits (§4), retry with exponential backoff + jitter, circuit breaker on repeated 4xx/5xx.
- Output: raw bytes to S3 `raw/{source}/{document_id}`, metadata row in `Document`.
- **Acceptance:** corpus manifest (well list per §4 selection criteria) fully acquired; zero duplicate `document_id`s; `SOURCES.md` and `LICENSES.md` complete.

### Stage B — Normalization & page rendering
- Convert all inputs to per-page PNG (300 DPI target) + PDF; deskew, rotate-detect.
- OCR pass (open-source: PaddleOCR primary; Tesseract and Surya as eval-compared alternates) producing word-level text + coordinates; store as derived artifact. OCR engine sits behind an adapter interface — engine choice is per-corpus config, settled by Stage B evals (ADR-003).
- Compute `ocr_quality_score` per page (confidence distribution + dictionary-hit rate). Pages below threshold flagged `low_quality` — these still go to extraction (vision model) but reviewer UI badges them.
- **Acceptance:** 100% of corpus pages rendered; OCR artifacts stored; quality histogram report generated.

### Stage C — Classification & splitting
- Classify each document (and split multi-record scans — common in RRC files where one PDF contains many filings) into `doc_type` taxonomy:
  `completion_report | plugging_record | casing_record | cement_report | wellbore_schematic | permit | sundry_notice | daily_drilling_report | end_of_well_report | correspondence | map_or_plat | unknown`
- Implementation: LLM classification on first-N pages + layout features; few-shot prompt with examples per source.
- **Acceptance:** ≥95% classification accuracy on a 200-document hand-labeled sample (stratified across sources/eras); split correctness ≥90%.

### Stage D — Schema-guided extraction
- Per `doc_type`, an extraction template defines which entity fields it can yield (e.g., W-3 → PluggingRecord[], casing summary; completion report → CasingString[], CompletionInterval[]).
- Extractor input: page image(s) + OCR text + template JSON schema. Output: `ExtractedFact[]` with confidence, snippet, page, bbox (from OCR alignment where possible).
- Multi-pass strategy: (1) targeted field extraction; (2) "anything missed" sweep for wellbore events/anomalies narrative; (3) self-verification pass — model re-reads its own facts against the page and adjusts confidence (record both scores).
- Schematics/diagrams: vision extraction into structured casing/plug representation; mark `derived_from_diagram=true` (lower default confidence, always human-review-required).
- **Acceptance:** field-level precision/recall vs. gold set per §11; calibration: among facts with confidence ≥0.9, ≥95% correct.

### Stage E — Entity resolution & conflict detection
- Resolve facts to Well/Wellbore: API/UWI matching, lease+name fuzzy matching, location sanity check. Unresolvable facts → `orphan_facts` review queue.
- Conflict detection rules: same field_path, overlapping validity, materially different values → assign `conflict_group_id`. Auto-resolution allowed only for whitelisted cases (e.g., later-superseding regulator form of same series); everything else → human.
- Physical consistency validators (deterministic code, not LLM): casing shoe depths monotonic with hole size; plug intervals within wellbore TD; cement top ≤ shoe; dates ordered. Violations → flagged facts.
- **Acceptance:** 0 silent conflicts (every conflict either auto-resolved-by-whitelisted-rule or queued); validator suite passing on gold wells.

---

## 8. Agent Definitions

All agents run on the orchestrator (Strands loop inside Temporal activities), access data exclusively via MCP tools (§8.7), produce structured outputs, and log every tool call. Model choice per agent is a config, not code — routed via the LiteLLM gateway to self-hosted open-weight models served on vLLM. Defaults: large open VLM for extraction/QC and historian work; small open model for classification and page-relevance filtering where evals permit. Model assignments are eval-gated: any model change must pass §10 regression before promotion.

### 8.1 Acquisition Agent
- **Goal:** given a well selector or jurisdiction, plan and execute acquisition; verify corpus completeness against the source's own index.
- **Tools:** `source_discover`, `source_fetch`, `corpus_status`, `report_gap`
- **Output:** acquisition report (documents found/fetched/failed, suspected missing record types).

### 8.2 Document Intake Agent
- **Goal:** classify, split, and route documents (Stage C owner); escalate unknowns with rationale.
- **Tools:** `get_document_pages`, `classify_submit`, `split_document`, `flag_for_review`

### 8.3 Extraction Agent (the core workhorse)
- **Goal:** schema-guided fact extraction per Stage D, with self-verification.
- **Tools:** `get_document_pages`, `get_ocr_text`, `get_extraction_template`, `submit_facts`, `flag_for_review`
- **Hard rules (system prompt invariants):**
  - Never infer a value not evidenced on the page; absence is a gap, not a guess.
  - Every fact must carry page + snippet. A fact without provenance is invalid and will be rejected by the API.
  - Units and datums copied as written; normalization happens downstream.
  - When handwriting is ambiguous, emit the candidate readings with split confidence rather than choosing silently.

### 8.4 Wellbore Historian Agent
- **Goal:** assemble the well's life narrative: chronology of operations, sidetracks, fish/junk, integrity events, prior P&A attempts — from approved + proposed facts across all documents.
- **Tools:** `query_facts`, `search_documents` (semantic), `submit_facts` (event type), `get_well_summary`
- **Output:** WellboreEvent records + a cited narrative section for the dossier.

### 8.5 Gap & Rubric Agent
- **Goal:** evaluate the well against the jurisdiction rubric (§5.3); produce the gap report with criticality ranking and *suggested next sources* for each gap (e.g., "cement top unknown — check for CBL in sundry notices, or flag for customer internal records in Phase 2").
- **Tools:** `query_facts`, `get_rubric`, `submit_gap_report`

### 8.6 Dossier Composer Agent
- **Goal:** render the final dossier (PDF + JSON) from approved facts only; include the gap report, confidence summary, and full citation appendix.
- **Tools:** `query_facts(status=approved)`, `get_gap_report`, `render_dossier`
- **Hard rule:** the composer may not introduce any well-specific factual claim that is not an approved fact. Template language only.

### 8.7 MCP tool server (single data gateway)
Typed tools, all logged with agent identity + workflow run id:

```
source_discover(source, well_selector) -> document_refs[]
source_fetch(document_ref) -> document_id
get_document_pages(document_id, page_range) -> page_image_uris[]
get_ocr_text(document_id, page_range) -> ocr_blocks[]
get_extraction_template(doc_type, jurisdiction) -> json_schema
submit_facts(facts[]) -> accepted/rejected per fact (validates provenance)
query_facts(filter: well_id, entity_type, status, conflict_only...) -> facts[]
search_documents(query, well_id?, doc_type?) -> ranked passages w/ doc/page
get_rubric(jurisdiction) -> requirement[]
submit_gap_report(well_id, gaps[]) -> gap_report_id
get_well_summary(well_id) -> materialized entity view
render_dossier(well_id, template_id) -> artifact_uris[]
flag_for_review(object_ref, reason) -> queue_item_id
```

Phase 2 adds customer-source tools (`ecm_search`, `petrel_query`, ...) behind the same gateway — agents don't change.

---

## 9. Agentic Workflows

### 9.1 Workflow W1 — Dossier Generation (MVP centerpiece)

```
trigger: user selects well (or batch) ──▶
[1] Acquisition Agent: ensure corpus complete for well ──▶
[2] Document Intake Agent: classify/split new documents ──▶
[3] Extraction Agent: extract per document (parallel fan-out) ──▶
[4] Entity resolution + validators (deterministic stage) ──▶
[5] Wellbore Historian Agent: chronology + events ──▶
[6] Gap & Rubric Agent: coverage + gap report ──▶
[7] ── HITL GATE ── reviewer works the queue:
        conflicts, low-confidence facts, diagram-derived facts,
        validator violations, orphan facts
     (UI requirement: side-by-side fact ↔ source page with bbox highlight;
      single-keystroke approve/correct/reject; batch-approve high-confidence)
[8] Dossier Composer Agent: render v1 dossier ──▶
[9] Reviewer final sign-off ──▶ dossier published (immutable version)
```

- Stages 1–6 fully automated; the workflow pauses at 7 and resumes on reviewer completion.
- Re-runs are incremental: new documents or corrected facts trigger only affected downstream stages.

### 9.2 Workflow W2 — Portfolio Gap Triage
Batch W1 stages 1–6 across a well list (e.g., the 30 orphan wells in the corpus); output a ranked portfolio report: dossier-readiness score per well, blocker gaps, estimated review effort. This is the records-manager and government-program demo.

### 9.3 Workflow W3 — Permit Draft Assist (stretch goal, MVP-optional)
From an approved dossier, draft the jurisdiction permit forms (BSEE APM narrative sections; TX W-3A fields) with every field traced to approved facts; unknown fields rendered as explicit blanks with the gap reference. Output is clearly watermarked DRAFT — filing is human-only (non-goal §3).

### 9.4 HITL and trust requirements (binding)
- No dossier publishes without human sign-off. No exceptions, including demos.
- Reviewer corrections are training signal: persist (original fact, correction, page) tuples for eval-set growth and few-shot improvement.
- Confidence thresholds are config: facts ≥ T_auto (default 0.95 AND validator-clean AND non-diagram) may be batch-approved by the reviewer in one action; never auto-approved silently.
- Every published dossier embeds its citation appendix; the JSON export carries fact ids enabling programmatic audit.

---

## 10. Evaluation Harness & Acceptance Criteria

### 10.1 Gold-standard set
- Hand-build complete dossiers for **10 wells** (5 GoM with completed P&A, 3 Texas mixed-era, 2 Volve) — SME-compiled, field-level ground truth (~40–80 fields/well + event lists). This is the most important artifact of month one; budget real SME time.

### 10.2 Metrics (run on every pipeline change; CI-gated)
| Metric | Target (MVP exit) |
|---|---|
| Field-level extraction precision | ≥0.97 |
| Field-level extraction recall | ≥0.90 |
| Confidence calibration (facts ≥0.9 conf. that are correct) | ≥95% |
| Document classification accuracy | ≥0.95 |
| Rubric coverage agreement vs. SME gap analysis | ≥0.9 F1 on blocker gaps |
| Cost per offshore well file | <$300 |
| Wall-clock per 1,000-page well | <1 hr |
| Reviewer time per offshore dossier | <2 hrs |
| Provenance integrity (facts with valid doc+page) | 100% (hard constraint) |

### 10.3 Eval harness requirements
- Versioned eval sets in-repo; runs tagged with extractor/prompt/model versions; regression report per PR.
- Per-document-era breakdown (pre-1960 / 1960–90 / modern) — improvements must not regress the hard eras.
- Adversarial set: rotated pages, bleed-through scans, conflicting filings, wrong-well pages misfiled in archives (these exist; seed some deliberately).

---

## 11. Technology Stack (open-source components only — defaults; substitutions require an ADR)

| Layer | Component | License | Notes |
|---|---|---|---|
| Orchestration | **Temporal** (self-hosted) | MIT | Durable workflows, retries, HITL pause/resume (ADR-001) |
| Agent framework | **Strands Agents SDK** | Apache-2.0 | Thin agent loop, MCP-native, model-agnostic (ADR-004); agent specs stored as data |
| Model serving | **Ollama / MLX (mlx-vlm)** — laptop profile; **vLLM** — cluster profile | MIT / MIT / Apache-2.0 | Same LiteLLM endpoint contract; quantized weights (GGUF/MLX 4–8 bit) on Mac |
| Model gateway | **LiteLLM** | MIT | Routing, per-call cost metering, provider abstraction, escalation tier flag (§16.4) |
| Models | Open-weight VLM + LLMs (§16.2) | Open weights (check each license) | Eval-gated selection per agent role |
| LLM observability | **Langfuse** (self-hosted) | MIT | Tracing, per-well cost attribution (NFR §6.3) |
| OCR | **Tesseract / docTR** — laptop profile defaults; **PaddleOCR** — cluster profile candidate | Apache-2.0 each | Behind OCR adapter (ADR-003); PaddleOCR is unreliable on Apple Silicon — do not fight it on Mac |
| PDF/image | **Poppler/pdfium, OpenCV, OCRmyPDF** | GPL-2/Apache/MPL | Rendering, deskew, preprocessing |
| Backend | **Python + FastAPI** | MIT | Services + MCP tool server (Python MCP SDK, MIT) |
| Database | **PostgreSQL** + **pgvector** | PostgreSQL/PostgreSQL | Entities, facts, review state; embeddings |
| Object storage | **MinIO** | AGPL-3.0** | S3-compatible, object-lock for immutable raw store; **AGPL is fine for self-hosted internal use; if license posture changes, SeaweedFS/Ceph are the fallbacks (ADR-005) |
| Search | **Postgres FTS + pgvector** — laptop profile; **OpenSearch** — cluster profile | PostgreSQL / Apache-2.0 | Laptop profile keeps the footprint on one machine (resolves ADR-002 for MVP) |
| Reviewer UI | **React + Tailwind** (proprietary app code) | MIT deps | HITL interface per §9.1 |
| AuthN/Z | **Keycloak** | Apache-2.0 | OIDC SSO, per-pilot realms |
| Infra | **docker-compose** — laptop profile; **Kubernetes + OpenTofu + Helm** — cluster profile | Apache-2.0/MPL-2.0/Apache-2.0 | One compose file runs the full MVP on a Mac; Helm charts are the same containers |
| Observability | **Prometheus, Grafana, Loki** | Apache-2.0/AGPL-3.0/AGPL-3.0 | Metrics, dashboards, logs (self-hosted use) |
| CI/CD | **GitHub Actions or Gitea Actions + Argo CD** | — /MIT/Apache-2.0 | GitOps deploys |

**What this buys:** zero cloud lock-in (the same Helm release runs on EKS, AKS, on-prem, or a sovereign enclave — directly reusable thinking for EDI Express sovereign tiers), no per-token vendor dependency, full data custody (no document ever leaves the deployment boundary in the default path), and a bill of materials enterprises and NOCs can security-review.

**What it costs:** laptop-class throughput and quantized-model accuracy during MVP (managed via §16.3 and the dev-time escalation flag §16.4), MLOps surface area when the cluster profile arrives, and an extraction-accuracy gap to manage (§16.3).

---

## 12. Security, Compliance, Legal Guardrails

- MVP corpus is public data; still treat the platform as if customer data is present: encryption at rest (MinIO SSE + Postgres TDE/disk encryption with self-managed keys), TLS in transit, least-privilege RBAC (Kubernetes + Keycloak roles), no data in logs beyond ids/snippets.
- Tenant isolation: account-or-VPC-level separation per pilot customer (Phase 2 design now, enforce later).
- Record source licenses (§4.5); Volve license terms verified and stored before use.
- Disclaimers embedded in every dossier: compiled record summary, not engineering advice; operator remains responsible for verification and regulatory compliance.
- SOC 2 readiness: choose logging/access patterns now that won't need rework (audit trail already required by product design).
- IP hygiene: all code/data in NewCo-designated repos; no reuse of any prior-employer code or internal documents (see spin-out legal track — out of scope for build agents, but binding).

---

## 13. Build Sequence & Milestones

### M0 (Weeks 1–2): Foundations
- Repo, docker-compose laptop stack up end-to-end on the dev Mac (Temporal, Postgres, MinIO, Langfuse, MCP skeleton), Ollama/MLX serving first candidate models, Postgres schema v1 (§5.2), S3 layout, MCP server skeleton with 4 tools, ADR-001/004/008 ratified; ADR-002/003/006 spikes scheduled (see §17 for all ADRs)
- BSEE + RRC crawler spikes: fetch 5 wells each end-to-end raw

### M1 (Weeks 3–6): Pipeline vertical slice
- Stages A–D working for ONE doc type per source (BSEE APM, TX W-3, Volve EOWR)
- First 50 documents through extraction with provenance; crude facts browser
- Begin gold-standard dossier compilation (SME track, parallel)

### M2 (Weeks 7–10): Full corpus + agents
- Full §4 corpus acquired; all doc types classified; Extraction Agent multi-pass live
- Entity resolution + validators; Wellbore Historian Agent v1
- Eval harness running with first gold wells; baseline metrics published

### M3 (Weeks 11–14): Dossier loop closed
- Rubrics authored (BSEE + TXRRC); Gap & Rubric Agent; Dossier Composer; PDF/JSON export
- Reviewer UI v1 with HITL gate wired into W1
- W1 end-to-end on 5 wells with internal reviewers

### M4 (Weeks 15–18): Hardening to demo/pilot grade
- Hit §10.2 targets on gold set; cost + latency NFRs met
- W2 portfolio triage on the 30-well orphan subset
- Demo package: live dossier generation for a prospect-owned GoM well from public data
- Pilot-deployable single-tenant stack

**MVP exit = M4 acceptance criteria met + one design-partner pilot agreement in motion.**

---

## 14. Risks & Open Questions (track as issues from day one)

1. **Extraction accuracy on worst-era documents** — mitigation: vision-first strategy, adversarial evals, human-review routing by quality score. Kill-switch question: if pre-1960 recall stays <0.6, does the product story survive on flagging-and-routing alone? (Likely yes — "we tell you what's unknowable" is still valuable — but pricing changes.)
2. **Source access stability** — regulator portals change without notice; mitigation: raw-bytes archival, crawler contract tests, source-status monitoring.
3. **Rubric correctness** — a wrong rubric produces confidently wrong gap reports; mitigation: SME review of rubrics is a release gate; rubric versioning.
4. **Volve license scope** — verify redistribution/demo terms before any public demo using Volve imagery.
5. **Scope creep toward engineering advice** — the line is compiled facts + gaps, never barrier design; enforce in Composer hard rules and disclaimers.
6. **Per-well cost blowout on huge files** — mitigation: page-relevance pre-filter (cheap model) before frontier-model extraction; cost dashboard alert at $200/well.

---

## 15. Glossary (for build agents without O&G background)

- **P&A:** Plug and Abandonment — permanently sealing a well with cement/mechanical barriers
- **API number / UWI:** unique well identifiers (US 12-digit / international)
- **MD / TVD:** Measured Depth / True Vertical Depth (datum matters: KB=kelly bushing, RT=rotary table, MSL=mean sea level)
- **Casing string:** steel pipe cemented in the wellbore; multiple concentric strings per well
- **Cement top (TOC):** highest point of cement behind a casing string — the single most disputed fact in P&A planning
- **CBL:** Cement Bond Log — wireline measurement verifying cement
- **Fish / junk:** equipment lost downhole, obstructing future operations
- **Sidetrack:** a new wellbore drilled out of an existing one
- **Sundry notice:** regulator filing for miscellaneous well operations
- **W-2/W-3/W-3A/G-1/P-4:** Texas RRC form types (completion, plugging record, plugging intent, gas completion, operator transfer)
- **APM / WAR / EOR:** BSEE filings (permit to modify, well activity report, end of operations report)
- **ARO:** Asset Retirement Obligation — the balance-sheet liability for future decommissioning
- **Orphan well:** a well with no solvent responsible operator; state/federal programs fund plugging

---

## 16. Open-Source Component Strategy: Models, GPUs, and the Accuracy Question

### 16.1 Why an OSS-only default path
1. **Sovereignty as a feature:** target buyers include NOCs and regulators with data-residency and no-external-API mandates. "Your well records never leave your boundary" is a sales weapon, not just an architecture choice.
2. **Unit economics at volume:** government orphan-well programs mean hundreds of thousands of documents; self-hosted batch inference on rented GPUs beats per-token API pricing at that scale.
3. **No platform dependency:** the company's fate is not coupled to any cloud's managed-AI roadmap or pricing.

### 16.2 Model selection (initial candidates — final picks are eval-gated, never asserted)
| Role | Candidate open-weight models | Selection criterion |
|---|---|---|
| Vision extraction (Stage D, core workhorse) | Qwen2.5-VL-72B / -32B; InternVL family; Llama vision variants | §10 field-level P/R on the gold set, by document era |
| Classification & page-relevance filter | Small VLM/LLM (e.g., Qwen 7–14B class) | ≥0.95 classification accuracy at lowest cost |
| Historian / Gap / Composer (text reasoning) | Llama 3.3-70B class; Qwen 72B class; smaller if evals permit | Narrative faithfulness + citation discipline on gold wells |
| Embeddings | Open embedding models (e.g., BGE/GTE family) | Retrieval eval on search_documents queries |

Rules: verify each model's license permits commercial use before adoption; record in ADR-006. Pin model weights by hash; model upgrades go through the §10 regression gate like any code change.

### 16.3 The honest accuracy gap — and the mitigation ladder
Open VLMs measurably trail frontier models on the worst inputs: pre-1960 handwriting, microfilm bleed-through, hand-drawn schematics. The §10.2 targets stand, but the path to hitting them with open models is explicit:
1. **Preprocessing wins first:** aggressive deskew/denoise/super-resolution on low-quality pages (OpenCV pipeline) — often worth more than a bigger model.
2. **Ensemble + OCR fusion:** VLM reads the page image *and* the OCR text; disagreement lowers confidence and routes to review rather than guessing (already a §8.3 invariant).
3. **Multi-sample self-consistency:** N extraction samples on hard pages; agreement raises confidence, divergence routes to human.
4. **Fine-tuning (Phase 2):** reviewer corrections (§9.4) accumulate into a LoRA fine-tune set for the extraction VLM — the open-model strategy gets *stronger* with usage in a way API-only products can't (the fine-tuned weights become proprietary IP).
5. **Human routing is the backstop:** the product's promise is verified facts + honest gaps, not autonomous perfection; a lower auto-approve rate on the 1940s corpus is a cost line, not a product failure.

### 16.4 Optional frontier escalation tier (config-gated, off by default)
A deployment-level flag (`escalation_tier: none | api`) allows routing only pages that fail the confidence/consistency ladder to a frontier API via the same LiteLLM gateway — for customers whose policy permits it. Requirements: per-page consent boundary documented, escalated pages logged distinctly, never enabled in sovereign profiles. This keeps one codebase serving both postures.

### 16.5 Compute model: Mac-first MVP, GPUs deferred
- **MVP (laptop profile):** the entire stack — Temporal, Postgres, MinIO, Langfuse, MCP server, reviewer UI, and model serving via Ollama/MLX — runs on one Apple Silicon Mac via docker-compose (models run natively, not in containers, to use Metal). Practical model tiers by unified memory: 36GB → Qwen2.5-VL-7B class; 64GB → 32B class at 4-bit (recommended MVP floor); 128GB → 72B class possible but slow, use for spot-checking quality headroom only.
- **Batch discipline replaces GPU scheduling:** corpus extraction runs overnight; the pipeline's idempotent, resumable stages (§6.3) make a sleeping laptop a legitimate compute substrate. Demos run from pre-computed dossiers plus one live single-document extraction.
- **Quality expectation setting:** quantized mid-size VLMs lower the auto-approve rate on hard-era documents versus full-precision large models. This is acceptable for MVP because (a) the gold-set evals (§10) tell us precisely how much headroom a GPU buys before we spend on one, and (b) the §16.4 escalation flag covers development-time gaps. Run the ADR-006 bake-off at all three quantization tiers so the accuracy-vs-memory curve is known, not guessed.
- **Cluster profile trigger:** first paying pilot or first >5,000-well portfolio job — then rent GPU capacity per ADR-007 and switch serving to vLLM with the same LiteLLM contract. No application code changes by design.

### 16.6 Risks specific to the OSS-only path
1. **Accuracy targets missed on hard eras with available open models** — mitigation ladder §16.3; commercial fallback §16.4; worst case, re-scope pre-1960 corpus as "flag and route" tier with adjusted pricing (Risk §14.1 kill-switch).
2. **MLOps burden on a 4-person team** — largely deferred by the laptop profile (Ollama/MLX are zero-ops); when the cluster profile arrives, vLLM + LiteLLM + Helm are deliberately boring choices and one engineer owns serving.
3. **License drift** (model weights, MinIO/Grafana AGPL, Surya GPL) — mitigation: license check in CI dependency gate; fallbacks named in ADRs.
4. **Framework bet (Strands) ages badly** — mitigation: agent specs as data (ADR-004), LangGraph named as the designated alternative, migration spike budgeted at ≤2 weeks if triggered.

---

## 17. Architecture Decision Records (Appendix)

Format: Status / Context / Decision / Alternatives / Consequences / Revisit trigger. Statuses: **Accepted** (build on it), **Proposed** (default named, eval spike confirms), **Deferred** (decision date defined).

### ADR-001 — Workflow engine: Temporal
**Status:** Accepted.
**Context:** The pipeline needs durable multi-stage execution, per-stage retries, incremental re-runs, and a workflow that pauses for human review (possibly for days) and resumes — under an OSS-only, self-hostable constraint (§16.1).
**Decision:** Temporal (self-hosted), Python SDK. Each pipeline stage and each agent invocation is a Temporal activity; W1's HITL gate is a workflow signal-wait.
**Alternatives:** *AWS Step Functions* — rejected: managed-service lock-in violates stack policy. *Prefect/Airflow* — batch-job DNA; long-lived human-in-the-loop waits and signal-driven resumption are awkward. *LangGraph-owned durability* — viable, but couples durability to the agent framework (see ADR-004) and gives weaker operational controls than Temporal's task queues/visibility.
**Consequences:** One more stateful service to operate (Temporal server + Postgres persistence — shares our Postgres expertise); deterministic workflow code discipline required; in exchange, liability-grade resumability and a clean HITL primitive.
**Revisit trigger:** If operating Temporal consumes >10% of one engineer's time after M2, evaluate Temporal Cloud (still no code change) or LangGraph checkpointing.

### ADR-002 — Search store: Postgres FTS + pgvector (laptop profile); OpenSearch deferred to cluster profile
**Status:** Accepted for MVP (laptop constraint resolved the spike).
**Context:** `search_documents` needs keyword precision (form numbers, API numbers, exact phrases in OCR text) *and* semantic retrieval (narrative queries like "prior squeeze attempts"). Corpus scale is modest (10⁵–10⁶ pages at pilot).
**Decision:** MVP runs entirely on Postgres: FTS (tsvector/BM25-approximate via pg_trgm where helpful) for keyword + pgvector for embeddings, hybrid fusion in the MCP tool. OpenSearch joins in the cluster profile if pilot-scale retrieval quality or highlight performance demands it — the search MCP tool's contract doesn't change.
**Alternatives:** *pgvector-only* — simplest, but BM25/highlighting in Postgres full-text is weaker for OCR-noisy text. *Qdrant/Weaviate* — excellent vector stores, but adds a service while still needing keyword search somewhere. *OpenSearch-only (k-NN plugin)* — workable; spike compares it against the hybrid as the simplification option.
**Consequences:** Two index paths to keep in sync (pipeline emits both on Stage B completion); fusion logic owned by us.
**Revisit trigger:** Retrieval eval (§10) misses targets on the MVP corpus, or pilot corpus exceeds ~5M pages.

### ADR-003 — OCR engine: PaddleOCR primary, behind an adapter
**Status:** Proposed (default named; Stage B eval on the Texas corpus decides).
**Context:** OCR feeds extraction fusion (§16.3) and bbox provenance. Corpus spans clean modern PDFs to 1940s microfilm. Licenses must permit commercial use.
**Decision:** Behind `OCRAdapter` with a common word/coordinate output schema. Laptop profile defaults: Tesseract and docTR (PyTorch-MPS) — PaddleOCR is unreliable on Apple Silicon and is not worth fighting on Mac. Cluster profile: PaddleOCR re-enters the bake-off. Per-corpus engine selection by eval in both profiles.
**Alternatives:** *Tesseract-primary* — most battle-tested, weaker on degraded/rotated scans without heavy preprocessing. *Surya* — strong results but GPL-3.0; excluded unless legal clears its use in a proprietary service (likely fine server-side, but decide deliberately). *docTR* — viable Apache-2.0 alternate, include in the bake-off if time permits.
**Consequences:** Eval harness must score OCR independently (word accuracy on a labeled sample) so OCR regressions aren't misattributed to extraction models.
**Revisit trigger:** Any corpus tier where best OCR word accuracy <80% — escalate that tier to vision-model-only extraction (skip fusion).

### ADR-004 — Agent framework: Strands Agents SDK inside Temporal activities
**Status:** Accepted.
**Context:** Agents need a model-driven tool loop, structured outputs, and MCP-native tool calling. Durability/HITL already belong to Temporal (ADR-001), so the framework should be thin. Stack must be OSS and model-agnostic.
**Decision:** Strands Agents SDK (Apache-2.0). Agent definitions (system prompt, tool allowlist, output schema, model assignment) are **data** (versioned YAML/JSON in-repo), loaded by a thin runner inside a Temporal activity.
**Alternatives:** *LangGraph* — strongest ecosystem and the designated migration target; rejected as primary because adopting it fully duplicates Temporal's state machine, and using it thinly negates its advantages. *CrewAI* — role-based autonomous crews fit collaborative prototyping, not deterministic regulated pipelines with hard stage boundaries; rejected. *No framework (raw API loop)* — tempting given how thin our needs are; rejected to avoid re-implementing tool-call plumbing, retries-on-malformed-output, and MCP wiring.
**Consequences:** Younger ecosystem risk accepted; mitigations: agent-specs-as-data, LangGraph migration spike pre-budgeted at ≤2 weeks.
**Revisit trigger:** Strands lags on a needed capability (e.g., structured-output enforcement for a new model family) for >1 release cycle, or the team hits 2+ workarounds per month.

### ADR-005 — Object storage: MinIO, with named AGPL fallback
**Status:** Accepted (with fallback).
**Context:** Need S3-compatible, self-hostable object storage with versioning and object-lock (immutable raw store, §5.1 append-only principle).
**Decision:** MinIO. AGPL-3.0 is acceptable for self-hosted internal use (we are not redistributing MinIO or offering it as the service).
**Alternatives:** *SeaweedFS* (Apache-2.0) — designated fallback; *Ceph/Rook* — heavyweight for a 4-person team; *cloud S3* — violates stack policy as a dependency, though S3-compatibility means customer-cloud deployments can point at native S3 if *they* choose.
**Consequences:** Legal posture on AGPL documented; storage interface is plain S3 API so the fallback swap is config-level.
**Revisit trigger:** MinIO license/edition changes affecting self-hosted use, or a customer's legal team blocks AGPL components.

### ADR-006 — Model selection & licensing process
**Status:** Proposed (process accepted; specific picks eval-gated).
**Context:** §16.2 names candidate open-weight models per role; final picks must be earned on the gold set, and model licenses vary (some "open" weights restrict commercial use).
**Decision:** (1) License gate: before any model enters evals, record its license and commercial-use determination here. (2) Eval gate: promotion to a role requires passing §10.2 targets for that role, by document era, plus cost/throughput on reference hardware. (3) Pinning: weights pinned by hash; upgrades are PRs that re-run the full regression. (4) Initial bake-off (M0–M1), run on the MVP Mac at realistic quantizations: Qwen2.5-VL-7B vs 32B-4bit (vs 72B if 128GB hardware is available, as the quality-headroom reference) on 50 stratified pages including 1950s RRC scans — this single spike de-risks the OSS-model bet (§16.6 risk 1) AND produces the accuracy-vs-memory curve that prices the eventual GPU decision (ADR-007).
**Alternatives:** Frontier APIs as default — violates stack policy; available only via the §16.4 escalation tier.
**Consequences:** Model changes are slow and deliberate; that is the point.
**Revisit trigger:** A new open-weight release claiming material document-understanding gains → schedule bake-off within one sprint.

### ADR-007 — Compute: Mac-first MVP; rented GPUs at first pilot; buy-vs-rent at pilot #2
**Status:** Accepted (Mac-first); GPU step Deferred (trigger-based).
**Context:** No GPU hardware is assumed for MVP. The MVP corpus (~250 wells) is small enough for overnight laptop batch; pilots are not.
**Decision:** MVP runs on a single Apple Silicon Mac (64GB recommended minimum; see §16.5 model tiers). First paying pilot or first >5,000-well portfolio job triggers rented GPU capacity (cloud spot/reserved or neocloud) serving via vLLM behind the unchanged LiteLLM contract. Buy-vs-rent is modeled with real utilization data at pilot #2.
**Alternatives:** *Rent GPUs from day one* — unnecessary spend before evals justify model sizes; *buy now* — worst option: capex before knowing the accuracy-vs-memory curve.
**Consequences:** MVP throughput is laptop-bound (accepted, §16.5); the ADR-006 bake-off doubles as GPU sizing input; demo discipline (pre-computed dossiers) required.
**Revisit trigger:** Pilot signing, a portfolio job >5,000 wells, or gold-set evals proving a 72B-class model is required to hit §10 targets (in which case rent immediately for eval confirmation before any pilot commitment).

### ADR-008 — Implementation language: Python, with a gated Go exception
**Status:** Accepted.
**Context:** Candidate languages: Python, Go, Rust. The system is LLM/document-pipeline-centric; team is 4–5 engineers; iteration speed on extraction quality is the competitive variable.
**Decision:** Python 3.12+ for all services (FastAPI), the MCP tool server, pipeline stages, and agent runners. Enforced quality bar: full type hints + mypy strict, ruff, pydantic models at every service boundary, uv for dependency management.
**Rationale:** Every load-bearing dependency is Python-first: Strands, MCP SDK, Temporal SDK, LiteLLM, PaddleOCR, OpenCV, Langfuse, pgvector tooling. The compute-heavy paths (OCR, image preprocessing, inference) execute in C++/CUDA beneath Python bindings — application code is orchestration glue, not the hot path, so Go/Rust performance advantages don't materialize where it matters. A polyglot codebase at this team size taxes every hire, review, and deploy.
**Alternatives:** *Go* — genuinely better for high-concurrency crawling and lean service binaries; rejected as primary for ecosystem reasons, but pre-approved as a contained exception for the Acquisition Service **iff** measured crawl throughput in Python asyncio becomes the bottleneck (trigger below). *Rust* — maximum performance and safety, slowest iteration, near-zero ecosystem overlap with our dependencies; no justified role in MVP; reconsider only for a future high-volume parsing core if profiling ever shows Python orchestration itself as the cost driver (unlikely).
**Consequences:** Single-language CI/CD, docs, and onboarding; accepted costs: Python service memory footprint, GIL-aware concurrency design (asyncio + process pools for CPU-bound preprocessing).
**Revisit trigger for the Go exception:** Acquisition Service unable to sustain required polite-crawl concurrency (>500 concurrent fetches across sources) within 2× expected resource budget after asyncio tuning.

— END OF BRIEF —
